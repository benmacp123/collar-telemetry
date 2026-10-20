"""Notifier Lambda: email ``likely_death`` incidents from the incidents
table's stream.

Notifying from the stream (an outbox), not from the processor, means an
alert cannot be lost by a crash between saving it and sending it: the
stream record stays until the notifier succeeds. The notifier publishes to
SNS and then marks the incident ``notified_at``, so a crash after the
publish and before the mark sends one duplicate email on retry; a crash
before the publish sends it on retry. At least once, then, and rarely
twice.

An incident is notified the first time it is seen, open or already
resolved (a slice can open and resolve one), and only if
``NOTIFY_ENABLED`` is ``true``, so bulk replays send nothing.
"""

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache

import boto3

from cloud.store import Tables, mark_notified, was_notified

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

NOTIFIED_DETECTOR = "likely_death"


def handler(event: dict, context) -> dict:
    """Lambda entry point for a DynamoDB Streams batch.

    Args:
        event: The stream event (``Records``).
        context: The Lambda context; unused.

    Returns:
        dict: ``batchItemFailures`` for partial batch responses.
    """
    del context
    if os.environ.get("NOTIFY_ENABLED", "false").lower() != "true":
        return {"batchItemFailures": []}
    clients = _clients()
    return notify_records(
        event["Records"], clients[0], clients[1], Tables.from_env(), _topic()
    )


@lru_cache(maxsize=1)
def _clients():
    """DynamoDB and SNS clients, kept across warm invocations.

    Returns:
        tuple: A boto3 DynamoDB client and a boto3 SNS client.
    """
    return boto3.client("dynamodb"), boto3.client("sns")


def _topic() -> str:
    """The SNS topic ARN, from ``TOPIC_ARN``.

    Returns:
        str: The ARN.
    """
    return os.environ["TOPIC_ARN"]


def notify_records(
    records: list[dict], dynamodb, sns, tables: Tables, topic: str, clock=None
) -> dict:
    """Notify each new ``likely_death`` incident in a batch of stream records.

    Args:
        records: DynamoDB stream records, in stream order.
        dynamodb: A boto3 DynamoDB client.
        sns: A boto3 SNS client.
        tables: Table names.
        topic: SNS topic ARN.
        clock: Wall-clock function returning an aware datetime, for tests.

    Returns:
        dict: ``batchItemFailures`` naming the first record that failed;
        Lambda retries from there, so later records are retried too.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    for record in records:
        try:
            notify_record(record, dynamodb, sns, tables, topic, clock)
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.exception("failed on stream record %s", record["eventID"])
            return {
                "batchItemFailures": [
                    {"itemIdentifier": record["dynamodb"]["SequenceNumber"]}
                ]
            }
    return {"batchItemFailures": []}


def notify_record(record: dict, dynamodb, sns, tables: Tables, topic: str, clock):
    """Notify one stream record's incident if it needs it.

    Args:
        record: A DynamoDB stream record.
        dynamodb: A boto3 DynamoDB client.
        sns: A boto3 SNS client.
        tables: Table names.
        topic: SNS topic ARN.
        clock: Wall-clock function returning an aware datetime.

    Returns:
        bool: True if a notification was published.
    """
    image = record["dynamodb"].get("NewImage")
    if image is None or image.get("detector", {}).get("S") != NOTIFIED_DETECTOR:
        return False
    # The mark's own write comes back through the stream with notified_at
    # set; skip it without a read.
    if "notified_at" in image:
        return False
    run_id = image["run_id"]["S"]
    incident_id = image["incident_id"]["S"]
    if was_notified(dynamodb, tables, run_id, incident_id):
        return False
    sns.publish(
        TopicArn=topic,
        Subject=f"Likely death: {image['deployment_id']['S']}"[:100],
        Message=_body(image),
        MessageAttributes={
            "detector": {"DataType": "String", "StringValue": NOTIFIED_DETECTOR}
        },
    )
    mark_notified(dynamodb, tables, run_id, incident_id, clock())
    return True


def _body(image: dict) -> str:
    """The email text for an incident item.

    Args:
        image: The incident item, as a stream image.

    Returns:
        str: Plain text.
    """
    incident = json.loads(image["incident"]["S"])
    return (
        f"{incident['message']}\n\n"
        f"Deployment: {incident['deployment_id']}\n"
        f"Status: {incident['status']}\n"
        f"Evidence from: {incident['opened_at']}\n"
        f"Raised (replay clock): {incident['raised_at']}\n"
        f"Run: {image['run_id']['S']}\n"
        f"Incident: {incident['incident_id']}\n"
    )
