"""Cost of runs on the deployed stack, from metered usage and list prices.

Two halves, so the report reproduces without an account. ``fetch_usage``
(workstation, needs credentials) reads per-minute CloudWatch metrics for
the stack's functions, queue, tables, log groups and topic, which AWS
keeps after ``terraform destroy``. Everything else is offline: totals for
a run's time window, the bill at a committed price snapshot, the cost
while idle, and a projection to live mode.

The replay publishes everything up front, so the queue trigger hands the
processor batches of up to ten slices. Live, each collar's daily slice
arrives alone and gets its own invocation, so per-invocation overheads
(start-up work, Lambda's own log lines) repeat per slice. The projection
brackets that: per slice as measured (low) and per invocation as
measured (high).
"""

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cloud.local import QUEUE, TABLES, TOPIC

FUNCTIONS = {"processor": "collar-processor", "notifier": "collar-notifier"}
# Must match infra/terraform/functions.tf (tests/cloud/test_cost.py checks).
MEMORY_MB = {"processor": 512, "notifier": 256}
# SQS bills each 64 KB of a request's payload as one request.
SQS_CHUNK_BYTES = 64 * 1024
MINUTES_PER_MONTH = 365.25 * 24 * 60 / 12
DAYS_PER_MONTH = 365.25 / 12
PERIOD_S = 60


@dataclass(frozen=True)
class Metric:
    """One CloudWatch metric to fetch, named by a dimension the stack set.

    Attributes:
        key: Name in the usage file, ``<resource>.<metric>``.
        namespace: CloudWatch namespace, such as ``AWS/Lambda``.
        name: Metric name.
        dimension: The identifying dimension's name.
        value: Its value (a resource name).
    """

    key: str
    namespace: str
    name: str
    dimension: str
    value: str


def metrics() -> list[Metric]:
    """Every metric the cost report reads, all as per-minute sums.

    Returns:
        list[Metric]: Lambda calls and run time, queue traffic, table
        request units, log bytes and notifications.
    """
    wanted = []
    for role, function in FUNCTIONS.items():
        for name in ("Invocations", "Duration", "Errors"):
            wanted.append(
                Metric(f"{role}.{name}", "AWS/Lambda", name, "FunctionName", function)
            )
        wanted.append(
            Metric(
                f"{role}_logs.IncomingBytes",
                "AWS/Logs",
                "IncomingBytes",
                "LogGroupName",
                f"/aws/lambda/{function}",
            )
        )
    for name in (
        "NumberOfMessagesSent",
        "NumberOfMessagesReceived",
        "NumberOfMessagesDeleted",
        "NumberOfEmptyReceives",
    ):
        wanted.append(Metric(f"slices.{name}", "AWS/SQS", name, "QueueName", QUEUE))
    for role, table in (("state", TABLES.state), ("incidents", TABLES.incidents)):
        for name in ("ConsumedWriteCapacityUnits", "ConsumedReadCapacityUnits"):
            wanted.append(
                Metric(f"{role}.{name}", "AWS/DynamoDB", name, "TableName", table)
            )
    for name in ("NumberOfMessagesPublished", "NumberOfNotificationsDelivered"):
        wanted.append(Metric(f"alerts.{name}", "AWS/SNS", name, "TopicName", TOPIC))
    return wanted


def resolve(cloudwatch, metric: Metric) -> list[dict] | None:
    """The exact dimension set to query a metric by.

    CloudWatch only returns data for an exact dimension match, and some
    services publish one metric under several sets (Lambda adds versions,
    DynamoDB a ``Source``). The set with fewest dimensions is the
    resource total; where DynamoDB splits by ``Source``, the table's own
    writes are ``Customer``.

    Args:
        cloudwatch: A boto3 CloudWatch client.
        metric: The metric.

    Returns:
        list[dict] | None: The dimensions, or None if CloudWatch lists no
        such metric (nothing was recorded in the last two weeks).

    Raises:
        LookupError: If more than one set is equally small.
    """
    found = []
    for page in cloudwatch.get_paginator("list_metrics").paginate(
        Namespace=metric.namespace,
        MetricName=metric.name,
        Dimensions=[{"Name": metric.dimension, "Value": metric.value}],
    ):
        found.extend(page["Metrics"])
    if not found:
        return None
    fewest = min(len(m["Dimensions"]) for m in found)
    smallest = [m["Dimensions"] for m in found if len(m["Dimensions"]) == fewest]
    if len(smallest) > 1:
        smallest = [
            dims for dims in smallest if {"Name": "Source", "Value": "Customer"} in dims
        ]
    if len(smallest) != 1:
        raise LookupError(f"{metric.key}: ambiguous dimensions {smallest}")
    return sorted(smallest[0], key=lambda d: d["Name"])


def fetch_usage(cloudwatch, start: datetime, end: datetime) -> dict:
    """Per-minute sums of every metric between two times.

    CloudWatch keeps one-minute points for 15 days, so fetch within that
    of the run.

    Args:
        cloudwatch: A boto3 CloudWatch client in the stack's region.
        start: Start of the span, aware.
        end: End of the span, aware.

    Returns:
        dict: The span and, per metric key, its dimensions and points
        (ISO minute to sum); a metric CloudWatch does not list has no
        dimensions and no points.
    """
    out = {}
    queries = []
    for index, metric in enumerate(metrics()):
        dimensions = resolve(cloudwatch, metric)
        out[metric.key] = {
            "namespace": metric.namespace,
            "metric": metric.name,
            "dimensions": dimensions,
            "points": {},
        }
        if dimensions is None:
            continue
        queries.append(
            {
                "Id": f"m{index}",
                "Label": metric.key,
                "MetricStat": {
                    "Metric": {
                        "Namespace": metric.namespace,
                        "MetricName": metric.name,
                        "Dimensions": dimensions,
                    },
                    "Period": PERIOD_S,
                    "Stat": "Sum",
                },
            }
        )
    if queries:
        for page in cloudwatch.get_paginator("get_metric_data").paginate(
            MetricDataQueries=queries, StartTime=start, EndTime=end
        ):
            for result in page["MetricDataResults"]:
                points = out[result["Label"]]["points"]
                for stamp, value in zip(result["Timestamps"], result["Values"]):
                    points[_minute(stamp)] = points.get(_minute(stamp), 0) + value
    for entry in out.values():
        entry["points"] = dict(sorted(entry["points"].items()))
    return {
        "start": _minute(start),
        "end": _minute(end),
        "period_s": PERIOD_S,
        "metrics": out,
    }


def _minute(stamp: datetime) -> str:
    """An aware time as an ISO string in UTC, to the minute.

    Args:
        stamp: The time.

    Returns:
        str: Such as ``2026-10-22T11:11:00+00:00``.
    """
    return stamp.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()


def window(started_at: str, drained_at: str) -> tuple[str, str]:
    """A run's span in whole minutes, from its results file's times.

    The end is two minutes past the drain reading, so the minute holding
    the last writes is included even if its point is stamped late.

    Args:
        started_at: ISO time the run started publishing.
        drained_at: ISO time the queue was seen empty.

    Returns:
        tuple[str, str]: Start (inclusive) and end (exclusive) minutes.
    """
    end = datetime.fromisoformat(drained_at) + timedelta(minutes=2)
    return _minute(datetime.fromisoformat(started_at)), _minute(end)


def total(usage: dict, key: str, span: tuple[str, str]) -> float:
    """Sum of one metric's points in a span.

    Args:
        usage: As written by ``fetch_usage``.
        key: The metric key.
        span: Start (inclusive) and end (exclusive) minutes.

    Returns:
        float: The sum; 0 if nothing was recorded.
    """
    start, end = (datetime.fromisoformat(t) for t in span)
    return sum(
        value
        for stamp, value in usage["metrics"][key]["points"].items()
        if start <= datetime.fromisoformat(stamp) < end
    )


def metered(usage: dict, span: tuple[str, str]) -> dict:
    """What a run used, totalled from the per-minute points.

    Args:
        usage: As written by ``fetch_usage``.
        span: The run's minutes.

    Returns:
        dict: Calls, run time (ms), queue traffic, request units, log
        bytes and notifications.
    """

    def get(key):
        return total(usage, key, span)

    return {
        "processor_invocations": get("processor.Invocations"),
        "processor_ms": get("processor.Duration"),
        "processor_errors": get("processor.Errors"),
        "notifier_invocations": get("notifier.Invocations"),
        "notifier_ms": get("notifier.Duration"),
        "messages_sent": get("slices.NumberOfMessagesSent"),
        "messages_received": get("slices.NumberOfMessagesReceived"),
        "messages_deleted": get("slices.NumberOfMessagesDeleted"),
        "empty_receives": get("slices.NumberOfEmptyReceives"),
        "write_request_units": get("state.ConsumedWriteCapacityUnits")
        + get("incidents.ConsumedWriteCapacityUnits"),
        "read_request_units": get("state.ConsumedReadCapacityUnits")
        + get("incidents.ConsumedReadCapacityUnits"),
        "state_write_request_units": get("state.ConsumedWriteCapacityUnits"),
        "log_bytes": get("processor_logs.IncomingBytes")
        + get("notifier_logs.IncomingBytes"),
        "sns_published": get("alerts.NumberOfMessagesPublished"),
        "emails": get("alerts.NumberOfNotificationsDelivered"),
    }


def idle(usage: dict, busy: Iterable[tuple[str, str]]) -> dict:
    """Queue polling while nothing runs, from the quiet minutes.

    Lambda's pollers keep long-polling an empty queue, and every empty
    receive is a billed request. A minute counts as quiet when the queue
    reported in it, nothing was sent or received, the processor did not
    run, and it lies outside every known run. Minutes before the first
    empty receive do not count: until the queue trigger exists (a stack
    still being created) nothing polls, so the queue reports zero, which
    is not what an idle deployed stack costs.

    Args:
        usage: As written by ``fetch_usage``.
        busy: Spans of known runs.

    Returns:
        dict: Quiet minutes found, the median empty receives per quiet
        minute, and that rate over a month.
    """
    spans = [tuple(datetime.fromisoformat(t) for t in span) for span in busy]
    points = {key: entry["points"] for key, entry in usage["metrics"].items()}
    empties = points["slices.NumberOfEmptyReceives"]
    polled = [stamp for stamp, empty in empties.items() if empty > 0]
    quiet = []
    for stamp, empty in empties.items():
        moment = datetime.fromisoformat(stamp)
        if not polled or moment < datetime.fromisoformat(min(polled)):
            continue
        if any(start <= moment < end for start, end in spans):
            continue
        if any(
            points[key].get(stamp, 0)
            for key in (
                "slices.NumberOfMessagesSent",
                "slices.NumberOfMessagesReceived",
                "processor.Invocations",
            )
        ):
            continue
        quiet.append(empty)
    if not quiet:
        return {"quiet_minutes": 0, "empty_receives_per_minute": None}
    rate = _median(quiet)
    return {
        "quiet_minutes": len(quiet),
        "empty_receives_per_minute": rate,
        "requests_per_month": rate * MINUTES_PER_MONTH,
    }


def _median(values: list[float]) -> float:
    """Median of a non-empty list.

    Args:
        values: The values.

    Returns:
        float: The median.
    """
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


class SendCounter:
    """Stands in for the SQS client in ``publisher.publish`` and counts
    what the queue would bill, without sending anything.

    Attributes:
        batches: ``send_message_batch`` calls.
        billed: Requests billed for them (64 KB chunks per call).
        messages: Messages sent.
        message_chunks: Requests the messages would be billed one by one,
            as live collars send them.
        message_bytes: Total body bytes.
    """

    def __init__(self):
        """Start every count at zero."""
        self.batches = self.billed = self.messages = 0
        self.message_chunks = self.message_bytes = 0

    def send_message_batch(self, QueueUrl, Entries):  # pylint: disable=invalid-name
        """Count one batch, as SQS would bill it.

        Args:
            QueueUrl: Ignored.
            Entries: The batch.

        Returns:
            dict: A response with no failures.
        """
        del QueueUrl
        sizes = [len(entry["MessageBody"].encode("utf-8")) for entry in Entries]
        self.batches += 1
        self.billed += _chunks(sum(sizes))
        self.messages += len(sizes)
        self.message_chunks += sum(_chunks(size) for size in sizes)
        self.message_bytes += sum(sizes)
        return {"Successful": [{"Id": entry["Id"]} for entry in Entries]}

    def counts(self) -> dict:
        """The counts so far.

        Returns:
            dict: Each attribute by name.
        """
        return dict(vars(self))


def _chunks(size: int) -> int:
    """Requests SQS bills for a payload.

    Args:
        size: Payload bytes.

    Returns:
        int: One per started 64 KB.
    """
    return max(1, math.ceil(size / SQS_CHUNK_BYTES))


def watched_days(timeline) -> float:
    """Days a deployment is watched in a replay: first arrival to end of
    watch.

    Args:
        timeline: A ``replay.Timeline``.

    Returns:
        float: Days; 0 for a deployment with no arrivals.
    """
    if not timeline.arrivals:
        return 0.0
    return (timeline.until - timeline.arrivals[0].time).total_seconds() / 86400


def load_prices(path) -> dict:
    """Read a price snapshot written by ``scripts/fetch_prices.py``.

    Args:
        path: The snapshot.

    Returns:
        dict: The snapshot.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def _gb_seconds(milliseconds: float, role: str) -> float:
    """Lambda compute for a function's run time.

    Args:
        milliseconds: Summed duration.
        role: ``processor`` or ``notifier``.

    Returns:
        float: GB-seconds at the function's memory.
    """
    return milliseconds / 1000 * MEMORY_MB[role] / 1024


def run_bill(used: dict, sent: dict, prices: dict) -> dict:
    """A run's bill at list price, line by line.

    SQS calls are not metered per call, so receives and deletes are
    counted as one each per processor invocation (one receive per batch,
    one batch delete), with receives billed the same extra 64 KB chunks
    as the sends that carried those messages. Empty receives are metered.

    Args:
        used: ``metered`` for the run.
        sent: ``SendCounter.counts`` for the run's messages, published as
            the run published them.
        prices: The price snapshot.

    Returns:
        dict: Per line: quantity, unit price, USD and how the quantity was
        found; and the total.
    """
    price = {name: entry["usd"] for name, entry in prices["prices"].items()}
    invocations = used["processor_invocations"]
    extra_chunks = sent["billed"] - sent["batches"]
    sqs_requests = {
        "send": sent["billed"],
        "receive": invocations + extra_chunks,
        "delete": invocations,
        "empty_receive": used["empty_receives"],
    }
    lines = {
        "lambda_requests": (
            invocations + used["notifier_invocations"],
            price["lambda_request"],
            "metered",
        ),
        "lambda_compute_gb_s": (
            _gb_seconds(used["processor_ms"], "processor")
            + _gb_seconds(used["notifier_ms"], "notifier"),
            price["lambda_gb_second"],
            "metered duration x configured memory",
        ),
        "sqs_requests": (
            sum(sqs_requests.values()),
            price["sqs_fifo_request"],
            "sends counted from the messages; receives and deletes one per "
            "invocation (assumed); empty receives metered",
        ),
        "dynamodb_write_units": (
            used["write_request_units"],
            price["dynamodb_write_request_unit"],
            "metered (includes transactions' double writes)",
        ),
        "dynamodb_read_units": (
            used["read_request_units"],
            price["dynamodb_read_request_unit"],
            "metered",
        ),
        "log_ingestion_gb": (
            used["log_bytes"] / 2**30,
            price["logs_ingested_gb"],
            "metered",
        ),
        "sns_requests": (used["sns_published"], price["sns_request"], "metered"),
        "sns_emails": (used["emails"], price["sns_email"], "metered"),
    }
    bill = {
        name: {
            "quantity": quantity,
            "unit_usd": unit,
            "usd": quantity * unit,
            "basis": basis,
        }
        for name, (quantity, unit, basis) in lines.items()
    }
    return {
        "lines": bill,
        "sqs_requests": sqs_requests,
        "total_usd": sum(line["usd"] for line in bill.values()),
    }


def live_projection(used: dict, sent: dict, prices: dict, months: float) -> dict:
    """Usage and cost per animal-month if every slice had its own
    invocation, as in live mode. Provisional: built from the replay's
    totals, not measured live.

    Per-invocation costs are bracketed: low spreads the run's processor
    time and log bytes over slices, high charges every slice a whole
    invocation's worth. Each slice is sent, received and deleted alone,
    billed by its own 64 KB chunks. Request units, the notifier and SNS
    scale with slices as measured. Idle polling is a fixed monthly cost,
    reported separately.

    Args:
        used: ``metered`` for the run.
        sent: ``SendCounter.counts`` for the run's messages.
        prices: The price snapshot.
        months: Animal-months the run covered.

    Returns:
        dict: Slices per animal-month, and low and high usage and cost per
        animal-month.
    """
    price = {name: entry["usd"] for name, entry in prices["prices"].items()}
    slices = sent["messages"]
    per_month = slices / months
    chunks = sent["message_chunks"] / slices
    shared = {
        "lambda_requests": 1 + used["notifier_invocations"] / slices,
        "sqs_requests": 2 * chunks + 1,
        "dynamodb_write_units": used["write_request_units"] / slices,
        "dynamodb_read_units": used["read_request_units"] / slices,
        "sns_requests": used["sns_published"] / slices,
        "sns_emails": used["emails"] / slices,
    }
    notifier_gb_s = _gb_seconds(used["notifier_ms"], "notifier") / slices
    bounds = {"low": slices, "high": used["processor_invocations"]}
    units = {
        "lambda_requests": price["lambda_request"],
        "lambda_compute_gb_s": price["lambda_gb_second"],
        "sqs_requests": price["sqs_fifo_request"],
        "dynamodb_write_units": price["dynamodb_write_request_unit"],
        "dynamodb_read_units": price["dynamodb_read_request_unit"],
        "log_ingestion_gb": price["logs_ingested_gb"],
        "sns_requests": price["sns_request"],
        "sns_emails": price["sns_email"],
    }
    out = {"slices_per_animal_month": per_month}
    for bound, spread_over in bounds.items():
        per_slice = shared | {
            "lambda_compute_gb_s": _gb_seconds(used["processor_ms"], "processor")
            / spread_over
            + notifier_gb_s,
            "log_ingestion_gb": used["log_bytes"] / 2**30 / spread_over,
        }
        usage = {name: per_slice[name] * per_month for name in units}
        out[bound] = {
            "usage": usage,
            "usd": {name: usage[name] * units[name] for name in usage},
            "total_usd": sum(usage[name] * units[name] for name in usage),
        }
    return out


def free_tier_animals(projection: dict, prices: dict, idle_requests: float = 0) -> dict:
    """How many animals the always-free allowances cover, per service,
    on the high projection. Idle polling uses SQS's allowance first.
    DynamoDB on-demand request units have no free tier, so they are paid
    from the first animal.

    Args:
        projection: ``live_projection``.
        prices: The price snapshot, with its ``free_tier``.
        idle_requests: SQS requests a month spent polling an empty queue.

    Returns:
        dict: Animals each allowance covers, and the smallest.
    """
    usage = projection["high"]["usage"]
    allowances = {
        "lambda_requests": "lambda_request",
        "lambda_compute_gb_s": "lambda_gb_second",
        "sqs_requests": "sqs_fifo_request",
        "log_ingestion_gb": "logs_ingested_gb",
    }
    covered = {
        name: (
            prices["free_tier"][free]["free_per_month"]
            - (idle_requests if name == "sqs_requests" else 0)
        )
        / usage[name]
        for name, free in allowances.items()
        if usage[name]
    }
    return {"animals": covered, "limit": min(covered.values())}
