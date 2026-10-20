"""Publisher: turn a study's replay timelines into FIFO queue messages.

Runs on a workstation, not in Lambda. It reads the same timelines as the
replay runner (``replay.timelines``) and cuts each into the same daily
slices (``slice_timeline``), so the cloud sees exactly the replay's input.
Each deployment is its own message group, so the queue releases one batch
at a time per animal and keeps its slices in order; different animals run
in parallel.
"""

import hashlib
from dataclasses import replace
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

from telemetry.core.slices import slice_timeline
from telemetry.data.studies import Study
from telemetry.sim.arrival import ArrivalScenario
from telemetry.sim.replay import DEFAULT_SEED, timelines

from cloud.messages import Message, UploadSettings

# The cloud sizing run found 236 KB bodies at worst (vultures, GSM). A cap
# of 1,000 arrivals (about 100 KB) keeps each message under the 256 KiB
# limit older SQS emulators still enforce, and each batch call under it too.
MAX_ARRIVALS = 1000
MAX_BATCH = 10
MAX_BATCH_BYTES = 256 * 1024


def run_id(study: Study, scenario: ArrivalScenario) -> str:
    """The run a study and scenario are published under.

    Args:
        study: The study.
        scenario: The arrival scenario.

    Returns:
        str: ``<study>-<scenario>``.
    """
    return f"{study.slug}-{scenario.name}"


def messages_for(
    study: Study,
    deployments,
    fixes,
    scenario: ArrivalScenario,
    seed: int = DEFAULT_SEED,
    max_arrivals: int = MAX_ARRIVALS,
) -> Iterator[Message]:
    """Every message for one study under one scenario, deployment by
    deployment, each deployment's slices in order.

    Args:
        study: The study, which names the run and the boundary.
        deployments: Its deployments.
        fixes: Its fixes.
        scenario: The arrival scenario.
        seed: Arrival seed, as for the replay.
        max_arrivals: Most arrivals per message.

    Yields:
        Message: Unsent messages (``sent_at`` is None).
    """
    uploads = UploadSettings(scenario.upload_every, scenario.max_lateness)
    for timeline in timelines(deployments, fixes, scenario, seed):
        deployment = timeline.deployment
        parts = slice_timeline(
            deployment.deployment_id,
            timeline.arrivals,
            timeline.until,
            max_arrivals=max_arrivals,
        )
        for seq, part in enumerate(parts):
            yield Message(
                run_id(study, scenario),
                seq,
                deployment.taxon,
                uploads,
                study.boundary,
                part,
            )


def dedup_id(message: Message, suffix: str = "") -> str:
    """The FIFO deduplication ID, hashed if too long for SQS (128 chars).

    Args:
        message: The message.
        suffix: Appended to the ID, to send a message again as if it were
            new to the queue.

    Returns:
        str: An ID unique to the run, deployment and sequence number.
    """
    plain = message.dedup_id + suffix
    return plain if len(plain) <= 128 else hashlib.sha256(plain.encode()).hexdigest()


def publish(
    sqs, queue_url: str, messages: Iterable[Message], clock=None, suffix: str = ""
) -> int:
    """Send messages to a FIFO queue in batches, preserving order.

    Args:
        sqs: A boto3 SQS client.
        queue_url: The FIFO queue.
        messages: Messages in the order to send.
        clock: Wall-clock function returning an aware datetime, for tests.
        suffix: Appended to every deduplication ID (``dedup_id``).

    Returns:
        int: Messages sent.

    Raises:
        RuntimeError: If SQS rejects any entry; partial batches are not
            retried, since resending out of order would break the
            sequence.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    sent = 0
    batch, size = [], 0
    for message in messages:
        body = replace(message, sent_at=clock()).to_json()
        entry = {
            "Id": str(len(batch)),
            "MessageBody": body,
            "MessageGroupId": message.key,
            "MessageDeduplicationId": dedup_id(message, suffix),
        }
        if batch and (
            len(batch) == MAX_BATCH or size + len(body.encode()) > MAX_BATCH_BYTES
        ):
            sent += _send(sqs, queue_url, batch)
            batch, size = [], 0
            entry["Id"] = "0"
        batch.append(entry)
        size += len(body.encode())
    if batch:
        sent += _send(sqs, queue_url, batch)
    return sent


def _send(sqs, queue_url: str, batch: list[dict]) -> int:
    """Send one batch.

    Args:
        sqs: A boto3 SQS client.
        queue_url: The FIFO queue.
        batch: Entries for ``send_message_batch``.

    Returns:
        int: Entries sent.

    Raises:
        RuntimeError: If any entry failed.
    """
    response = sqs.send_message_batch(QueueUrl=queue_url, Entries=batch)
    if response.get("Failed"):
        raise RuntimeError(f"SQS rejected messages: {response['Failed']}")
    return len(batch)
