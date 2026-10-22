"""Tests for the cost report: reading CloudWatch, totalling a run's
minutes, counting SQS requests, and pricing the run and live mode."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from cloud import cost, publisher
from cloud_helpers import messages

T0 = datetime(2026, 10, 22, 11, 0, tzinfo=timezone.utc)
PRICES = {
    "prices": {
        "lambda_request": {"usd": 0.2e-6},
        "lambda_gb_second": {"usd": 16.6667e-6},
        "sqs_fifo_request": {"usd": 0.5e-6},
        "dynamodb_write_request_unit": {"usd": 0.7423e-6},
        "dynamodb_read_request_unit": {"usd": 0.1487e-6},
        "logs_ingested_gb": {"usd": 0.5985},
        "sns_request": {"usd": 0.5e-6},
        "sns_email": {"usd": 20e-6},
    },
    "free_tier": {
        "lambda_request": {"free_per_month": 1_000_000},
        "lambda_gb_second": {"free_per_month": 400_000},
        "sqs_fifo_request": {"free_per_month": 1_000_000},
        "logs_ingested_gb": {"free_per_month": 5},
    },
}


def _minute(offset: int) -> str:
    """An ISO minute key, ``offset`` minutes after T0.

    Args:
        offset: Minutes after T0.

    Returns:
        str: The key as ``fetch_usage`` writes it.
    """
    return (T0 + timedelta(minutes=offset)).isoformat()


def _usage(points: dict) -> dict:
    """A usage file with the given points and every other metric empty.

    Args:
        points: Metric key to {minute offset: value}.

    Returns:
        dict: As ``fetch_usage`` writes it.
    """
    return {
        "metrics": {
            metric.key: {
                "points": {_minute(m): v for m, v in points.get(metric.key, {}).items()}
            }
            for metric in cost.metrics()
        }
    }


def _used(**changes) -> dict:
    """A run's metered usage: 100 slices in 20 invocations, unless changed.

    Args:
        **changes: Fields to override.

    Returns:
        dict: As ``metered`` returns it.
    """
    used = dict.fromkeys(cost.metered(_usage({}), (_minute(0), _minute(1))), 0.0)
    used |= {
        "processor_invocations": 20,
        "processor_ms": 20_000,
        "write_request_units": 1_000,
        "read_request_units": 300,
        "log_bytes": 2**20,
        "messages_sent": 100,
    }
    return used | changes


SENT = {
    "batches": 10,
    "billed": 12,
    "messages": 100,
    "message_chunks": 101,
    "message_bytes": 500_000,
}


def test_metric_keys_are_unique():
    """Each metric has its own key, so no two overwrite each other in the
    usage file."""
    keys = [metric.key for metric in cost.metrics()]
    assert len(keys) == len(set(keys))


@pytest.fixture(name="cloudwatch")
def fixture_cloudwatch(monkeypatch):
    """A moto CloudWatch client.

    Yields:
        CloudWatch client in eu-west-2.
    """
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        yield boto3.client("cloudwatch", region_name="eu-west-2")


def _put(cloudwatch, namespace, name, dimensions, when, value):
    """Record one data point.

    Args:
        cloudwatch: The client.
        namespace: Metric namespace.
        name: Metric name.
        dimensions: {name: value}.
        when: Timestamp.
        value: The value.
    """
    cloudwatch.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": name,
                "Dimensions": [{"Name": k, "Value": v} for k, v in dimensions.items()],
                "Timestamp": when,
                "Value": value,
            }
        ],
    )


def test_resolve_prefers_the_resource_total_and_customer_writes(cloudwatch):
    """With a metric published under several dimension sets, the smallest
    set is the resource total, and DynamoDB's own writes beat replication."""
    when = T0 + timedelta(seconds=30)
    for source in ("Customer", "GlobalTable"):
        _put(
            cloudwatch,
            "AWS/DynamoDB",
            "ConsumedWriteCapacityUnits",
            {"TableName": "collar-state", "Source": source},
            when,
            1,
        )
    _put(
        cloudwatch,
        "AWS/Lambda",
        "Invocations",
        {"FunctionName": "collar-processor"},
        when,
        1,
    )
    _put(
        cloudwatch,
        "AWS/Lambda",
        "Invocations",
        {"FunctionName": "collar-processor", "Resource": "collar-processor:1"},
        when,
        1,
    )
    by_key = {metric.key: metric for metric in cost.metrics()}
    assert cost.resolve(cloudwatch, by_key["state.ConsumedWriteCapacityUnits"]) == [
        {"Name": "Source", "Value": "Customer"},
        {"Name": "TableName", "Value": "collar-state"},
    ]
    assert cost.resolve(cloudwatch, by_key["processor.Invocations"]) == [
        {"Name": "FunctionName", "Value": "collar-processor"}
    ]
    assert cost.resolve(cloudwatch, by_key["alerts.NumberOfMessagesPublished"]) is None


def test_fetch_usage_sums_each_minute(cloudwatch):
    """Points land on their UTC minute, points in one minute add up, and a
    metric CloudWatch never recorded comes back empty, not missing."""
    for seconds, value in ((5, 2), (40, 3), (65, 4)):
        _put(
            cloudwatch,
            "AWS/SQS",
            "NumberOfEmptyReceives",
            {"QueueName": "collar-slices.fifo"},
            T0 + timedelta(seconds=seconds),
            value,
        )
    usage = cost.fetch_usage(cloudwatch, T0, T0 + timedelta(minutes=10))
    assert usage["metrics"]["slices.NumberOfEmptyReceives"]["points"] == {
        _minute(0): 5,
        _minute(1): 4,
    }
    assert usage["metrics"]["processor.Duration"] == {
        "namespace": "AWS/Lambda",
        "metric": "Duration",
        "dimensions": None,
        "points": {},
    }


def test_window_includes_the_minute_after_the_drain():
    """A run's span starts on its first minute and runs two minutes past
    the drain reading, so late-stamped last writes count."""
    assert cost.window("2026-10-22T11:11:27+00:00", "2026-10-22T12:06:16+00:00") == (
        "2026-10-22T11:11:00+00:00",
        "2026-10-22T12:08:00+00:00",
    )


def test_metered_counts_only_the_run_minutes():
    """Minutes outside a run's span, such as another run's, are left out."""
    usage = _usage({"processor.Invocations": {0: 5, 3: 7, 9: 100}})
    used = cost.metered(usage, (_minute(1), _minute(9)))
    assert used["processor_invocations"] == 7


def test_idle_skips_runs_and_active_minutes():
    """Quiet minutes exclude known runs and any minute with traffic, so
    polling under load does not count as idle."""
    usage = _usage(
        {
            "slices.NumberOfEmptyReceives": {0: 10, 1: 12, 2: 50, 3: 11, 4: 90},
            "slices.NumberOfMessagesSent": {2: 1},
        }
    )
    quiet = cost.idle(usage, [(_minute(4), _minute(5))])
    assert quiet["quiet_minutes"] == 3
    assert quiet["empty_receives_per_minute"] == 11
    assert quiet["requests_per_month"] == pytest.approx(11 * cost.MINUTES_PER_MONTH)


def test_send_counter_bills_by_64_kb_chunk():
    """A batch is one request per started 64 KB of its payload, and a
    message sent alone is billed by its own chunks."""
    counter = cost.SendCounter()
    small, large = "x" * 1000, "x" * (cost.SQS_CHUNK_BYTES + 1)
    counter.send_message_batch(
        QueueUrl="q", Entries=[{"Id": "0", "MessageBody": small}] * 3
    )
    counter.send_message_batch(
        QueueUrl="q",
        Entries=[{"Id": "0", "MessageBody": large}, {"Id": "1", "MessageBody": small}],
    )
    assert counter.counts() == {
        "batches": 2,
        "billed": 1 + 2,
        "messages": 5,
        "message_chunks": 4 + 2,
        "message_bytes": 4000 + cost.SQS_CHUNK_BYTES + 1,
    }


def test_send_counter_counts_what_the_publisher_sends():
    """The publisher accepts the counter as its client, so the cost report
    counts the run's real batches."""
    counter = cost.SendCounter()
    sent = publisher.publish(counter, "q", messages())
    assert sent == counter.messages > 0
    assert counter.batches == -(-sent // publisher.MAX_BATCH)


def test_run_bill_counts_receives_and_deletes_per_invocation():
    """Receives and deletes are one per invocation, receives carry the
    sends' extra chunks, and empty receives are added as metered."""
    bill = cost.run_bill(_used(empty_receives=50), SENT, PRICES)
    assert bill["sqs_requests"] == {
        "send": 12,
        "receive": 20 + 2,
        "delete": 20,
        "empty_receive": 50,
    }
    assert bill["lines"]["lambda_compute_gb_s"]["quantity"] == pytest.approx(10)
    assert bill["total_usd"] == pytest.approx(
        sum(line["quantity"] * line["unit_usd"] for line in bill["lines"].values())
    )


def test_live_projection_brackets_per_invocation_costs():
    """Charging each slice a whole invocation costs more than spreading
    the run over slices; with one slice per invocation they agree."""
    batched = cost.live_projection(_used(), SENT, PRICES, months=10)
    assert batched["slices_per_animal_month"] == 10
    assert batched["low"]["total_usd"] < batched["high"]["total_usd"]
    assert batched["low"]["usage"]["lambda_requests"] == 10
    assert batched["low"]["usage"]["sqs_requests"] == pytest.approx(10 * (2 * 1.01 + 1))
    alone = cost.live_projection(_used(processor_invocations=100), SENT, PRICES, 10)
    assert alone["low"] == alone["high"]


def test_free_tier_limit_is_the_tightest_allowance():
    """The animals the free tier covers is set by whichever allowance runs
    out first, after idle polling has used part of SQS's."""
    projection = {
        "high": {
            "usage": {
                "lambda_requests": 100,
                "lambda_compute_gb_s": 1,
                "sqs_requests": 1_000,
                "log_ingestion_gb": 0,
            }
        }
    }
    free = cost.free_tier_animals(projection, PRICES)
    assert free["limit"] == 1_000
    assert "log_ingestion_gb" not in free["animals"]
    polled = cost.free_tier_animals(projection, PRICES, idle_requests=500_000)
    assert polled["animals"]["sqs_requests"] == 500


def test_watched_days_runs_from_first_arrival_to_end_of_watch():
    """A deployment is watched from its first arrival; one with none adds
    nothing."""
    arrivals = [SimpleNamespace(time=T0), SimpleNamespace(time=T0 + timedelta(1))]
    timeline = SimpleNamespace(arrivals=arrivals, until=T0 + timedelta(days=3))
    assert cost.watched_days(timeline) == 3
    assert cost.watched_days(SimpleNamespace(arrivals=[], until=T0)) == 0
