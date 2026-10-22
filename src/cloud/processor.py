"""Processor Lambda: apply slice messages from the FIFO queue to state.

For each message the handler loads the deployment's state, builds the
deployment's stream with ``stream_for`` (the replay runner's settings),
runs the slice through ``advance`` and saves the new state and changed
incidents with one conditional write (``store.commit``).

Retries are safe. The state item records the sequence number of the last
message applied, so a message seen again (an SQS redelivery after a crash
between the write and the delete, or a publisher retry) is skipped, and a
message that arrives before its predecessor fails, to be retried once the
predecessor is in. A batch is processed in order; on the first failure the
rest of the batch is reported failed too, since later messages may belong
to the same deployment and must not overtake it.
"""

import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import boto3

from telemetry.core.detectors.geofence import EXIT, Fence
from telemetry.core.pipeline import stream_for

from cloud.messages import Message
from cloud.store import Tables, commit, load_state

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)

# Boundary files are bundled with the handler; locally they are read from
# the committed data.
DEFAULT_BOUNDARIES = Path(__file__).resolve().parents[2] / "data/raw/boundaries"

APPLIED = "applied"
DUPLICATE = "duplicate"


class OutOfOrder(Exception):
    """A message arrived before the one it follows."""


def handler(event: dict, context) -> dict:
    """Lambda entry point for an SQS batch.

    Args:
        event: The SQS event (``Records``).
        context: The Lambda context; unused.

    Returns:
        dict: ``batchItemFailures`` for partial batch responses.
    """
    del context
    return process_records(event["Records"], _client(), Tables.from_env())


@lru_cache(maxsize=1)
def _client():
    """A DynamoDB client, kept across warm invocations.

    ``AWS_ENDPOINT_URL`` (honoured by boto3 itself) points it at moto
    locally.

    Returns:
        A boto3 DynamoDB client.
    """
    return boto3.client("dynamodb")


def process_records(records: list[dict], client, tables: Tables) -> dict:
    """Apply a batch of SQS records in order.

    Args:
        records: SQS records, in queue order.
        client: A boto3 DynamoDB client.
        tables: Table names.

    Returns:
        dict: ``batchItemFailures``: the first record that failed and
        every record after it, so none overtakes a failed predecessor.
    """
    for index, record in enumerate(records):
        try:
            outcome = process_message(Message.from_json(record["body"]), client, tables)
        except Exception:  # pylint: disable=broad-exception-caught
            # Any failure leaves the message in the queue to be retried (and
            # dead-lettered after the queue's retry limit).
            LOG.exception("failed on message %s", record.get("messageId"))
            return {
                "batchItemFailures": [
                    {"itemIdentifier": later["messageId"]} for later in records[index:]
                ]
            }
        LOG.info("%s message %s", outcome, record.get("messageId"))
    return {"batchItemFailures": []}


def process_message(message: Message, client, tables: Tables, clock=None) -> str:
    """Apply one message, or skip it if it was already applied.

    Args:
        message: The message.
        client: A boto3 DynamoDB client.
        tables: Table names.
        clock: Wall-clock function returning an aware datetime, for tests;
            defaults to UTC now.

    Returns:
        str: ``APPLIED`` or ``DUPLICATE``.

    Raises:
        OutOfOrder: If the message's predecessor has not been applied.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    processed_at = clock()
    saved = load_state(client, tables, message.key)
    applied = -1 if saved is None else saved.seq
    if message.seq <= applied:
        return DUPLICATE
    if message.seq != applied + 1:
        raise OutOfOrder(
            f"{message.key}: message {message.seq} arrived after {applied}"
        )
    stream = stream_for(message.taxon, message.uploads, fence=_fence(message.boundary))
    if saved is not None:
        stream.states[message.deployment_id] = saved.state
    # An incident changed twice in one slice is written once, in its
    # newest form, as the replay runner keeps it.
    latest = {}
    for incident in stream.advance(
        message.deployment_id, list(message.slice.arrivals), message.slice.until
    ):
        latest[incident.incident_id] = incident
    commit(
        client,
        tables,
        message,
        stream.states[message.deployment_id],
        list(latest.values()),
        processed_at,
        clock(),
    )
    return APPLIED


@lru_cache(maxsize=8)
def _fence(boundary: str | None) -> Fence | None:
    """The named bundled boundary as an exit fence, loaded once per
    container.

    Args:
        boundary: Boundary file stem, or None.

    Returns:
        Fence | None: The fence, or None for no geofence.
    """
    if boundary is None:
        return None
    root = Path(os.environ.get("BOUNDARIES_DIR", DEFAULT_BOUNDARIES))
    return Fence.from_file(root / f"{boundary}.geojson", EXIT)
