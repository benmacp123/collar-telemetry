"""Tests for the deployed-stack helpers: reading Terraform's outputs,
waiting for the queue and the notifier, and finding what ``destroy`` left
behind."""

import json

import boto3
import pytest
from moto import mock_aws

from cloud import deployed, local, publisher
from cloud_helpers import RUN, expected, messages, poller

QUEUE_URL = "https://sqs.eu-west-2.amazonaws.com/000000000000/collar-slices.fifo"


def test_load_stack_reads_terraform_output_json(tmp_path):
    """The saved ``terraform output -json`` gives the queues, tables and
    region."""
    names = {
        "queue_url": QUEUE_URL,
        "dead_letter_queue_url": "dlq",
        "notify_failures_url": "failures",
        "state_table": "collar-state",
        "incidents_table": "collar-incidents",
        "topic_arn": "arn",
    }
    path = tmp_path / "outputs.json"
    path.write_text(
        json.dumps({k: {"sensitive": False, "value": v} for k, v in names.items()})
    )
    stack = deployed.load_stack(path)
    assert stack.region == "eu-west-2"
    assert stack.dead_letter_queue_url == "dlq"
    assert stack.tables == local.TABLES


def test_queue_depth_counts_messages_in_flight(aws):
    """A message a consumer holds but has not deleted still counts, so the
    drain wait cannot end while a Lambda is working."""
    url = aws["resources"].queue_url
    assert deployed.queue_depth(aws["sqs"], url) == 0
    publisher.publish(aws["sqs"], url, messages()[:3])
    aws["sqs"].receive_message(QueueUrl=url, MaxNumberOfMessages=1)
    assert deployed.queue_depth(aws["sqs"], url) == 3


def test_wait_for_drain_needs_several_empty_readings(aws):
    """The wait ends only after the queue reads empty several times in a
    row, while the consumer works between readings."""
    url = aws["resources"].queue_url
    publisher.publish(aws["sqs"], url, messages())
    drain = poller(aws).drain
    depths = []
    readings = deployed.wait_for_drain(
        aws["sqs"],
        url,
        quiet_polls=3,
        sleep=lambda seconds: drain(),
        report=depths.append,
    )
    assert depths[0] > 0
    assert depths[-3:] == [0, 0, 0]
    assert readings == len(depths)


def test_wait_for_drain_times_out_on_a_stuck_queue(aws):
    """A queue nobody consumes raises rather than waiting forever."""
    url = aws["resources"].queue_url
    publisher.publish(aws["sqs"], url, messages()[:1])
    with pytest.raises(TimeoutError):
        deployed.wait_for_drain(
            aws["sqs"], url, poll_seconds=10, timeout_seconds=30, sleep=lambda s: None
        )


def test_wait_for_notified_reports_what_is_missing(aws):
    """Incidents the notifier has marked are found; unknown ones are
    returned as missing once the wait gives up."""
    local.feed(aws["sqs"], aws["resources"], poller(aws), messages("gsm"))
    potential = {
        incident_id
        for incident_id, incident in expected("gsm").items()
        if incident["detector"] == "potential_death"
    }
    assert potential
    found = deployed.wait_for_notified(
        aws["dynamodb"], local.TABLES, RUN, potential, sleep=lambda s: None
    )
    assert not found
    missing = deployed.wait_for_notified(
        aws["dynamodb"],
        local.TABLES,
        RUN,
        potential | {"never"},
        poll_seconds=10,
        timeout_seconds=30,
        sleep=lambda s: None,
    )
    assert missing == {"never"}


@pytest.fixture(name="account")
def fixture_account(monkeypatch):
    """moto clients for the leftovers check, with nothing created.

    Yields:
        dict: Clients by service name.
    """
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "eu-west-2",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        yield {
            name: boto3.client(name)
            for name in (
                "resourcegroupstaggingapi",
                "logs",
                "iam",
                "budgets",
                "sts",
                "sqs",
            )
        }


def test_leftovers_is_empty_for_a_clean_account(account):
    """Nothing of the project's in the account: nothing reported."""
    assert deployed.leftovers(account, "collar-telemetry", "collar") == []


def test_leftovers_finds_tagged_and_untagged_remains(account):
    """A tagged queue, an untagged log group a late Lambda recreated, a
    role and the budget are all reported."""
    account["sqs"].create_queue(
        QueueName="collar-notify-failures", tags={"Project": "collar-telemetry"}
    )
    account["sqs"].create_queue(QueueName="other", tags={"Project": "other"})
    account["logs"].create_log_group(logGroupName="/aws/lambda/collar-processor")
    account["logs"].create_log_group(logGroupName="/aws/lambda/someone-else")
    account["iam"].create_role(
        RoleName="collar-notifier", AssumeRolePolicyDocument="{}"
    )
    account_id = account["sts"].get_caller_identity()["Account"]
    account["budgets"].create_budget(
        AccountId=account_id,
        Budget={
            "BudgetName": "collar-monthly",
            "BudgetLimit": {"Amount": "5", "Unit": "USD"},
            "TimeUnit": "MONTHLY",
            "BudgetType": "COST",
        },
    )
    found = deployed.leftovers(account, "collar-telemetry", "collar")
    assert found == sorted(
        [
            next(name for name in found if name.endswith(":collar-notify-failures")),
            "/aws/lambda/collar-processor",
            "iam role collar-notifier",
            "budget collar-monthly",
        ]
    )
