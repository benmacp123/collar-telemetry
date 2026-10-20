"""Tests for the publisher: the cloud gets the replay's slices, numbered in
order, and the FIFO queue drops exact resends."""

from datetime import timedelta

from telemetry.core.fixes import Deployment
from telemetry.data.studies import Study
from telemetry.sim.arrival import SCENARIOS

from cloud import publisher
from cloud_helpers import JACKAL, START, messages, track


def queued(aws) -> int:
    """Messages waiting in the slice queue.

    Args:
        aws: The ``aws`` fixture.

    Returns:
        int: The approximate count, exact in moto.
    """
    return int(
        aws["sqs"].get_queue_attributes(
            QueueUrl=aws["resources"].queue_url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )["Attributes"]["ApproximateNumberOfMessages"]
    )


def test_messages_follow_the_replay_timeline():
    """Each deployment's slices are numbered from 0 and carry its taxon,
    the scenario's upload plan and the study's boundary."""
    study = Study("jackals", "t", "s", "{stem}.csv", boundary="etosha")
    deployment = Deployment("A", "tag", "animal", JACKAL, START, None, None)
    scenario = SCENARIOS["gsm"]
    out = list(publisher.messages_for(study, [deployment], track(), scenario, seed=3))
    assert [m.seq for m in out] == list(range(len(out)))
    assert {m.run_id for m in out} == {"jackals-gsm"}
    assert {m.boundary for m in out} == {"etosha"}
    assert {m.uploads.max_lateness for m in out} == {scenario.max_lateness}
    assert [m.slice for m in out] == [m.slice for m in messages("gsm")]


def test_resend_with_same_id_is_dropped_by_the_queue(aws):
    """FIFO deduplication drops a resend within the window; a new ID gets
    through (the processor's sequence check handles those)."""
    batch = messages()
    url = aws["resources"].queue_url
    assert publisher.publish(aws["sqs"], url, batch) == len(batch)
    publisher.publish(aws["sqs"], url, batch)
    assert queued(aws) == len(batch)
    publisher.publish(aws["sqs"], url, batch[:2], suffix="#again")
    assert queued(aws) == len(batch) + 2


def test_large_messages_are_split_across_batches(aws, monkeypatch):
    """Batches stay under the size limit, and nothing is lost or reordered."""
    monkeypatch.setattr(publisher, "MAX_BATCH_BYTES", 5000)
    batch = messages(max_arrivals=50)
    url = aws["resources"].queue_url
    assert publisher.publish(aws["sqs"], url, batch) == len(batch)
    got = []
    while True:
        received = (
            aws["sqs"]
            .receive_message(QueueUrl=url, MaxNumberOfMessages=10)
            .get("Messages", [])
        )
        if not received:
            break
        got += [publisher.Message.from_json(m["Body"]).seq for m in received]
        aws["sqs"].delete_message_batch(
            QueueUrl=url,
            Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                for i, m in enumerate(received)
            ],
        )
    assert got == list(range(len(batch)))


def test_long_dedup_ids_are_hashed():
    """SQS caps deduplication IDs at 128 characters."""
    message = messages()[0]
    long = publisher.Message(
        "r" * 130, 0, message.taxon, message.uploads, None, message.slice
    )
    assert len(publisher.dedup_id(long)) == 64
    assert publisher.dedup_id(message) == message.dedup_id


def test_cap_keeps_messages_small():
    """At ``MAX_ARRIVALS`` per message, a body stays well under 256 KiB."""
    batch = messages("ideal", every=timedelta(days=30))
    big = max(batch, key=lambda m: len(m.slice.arrivals))
    assert len(big.slice.arrivals) <= publisher.MAX_ARRIVALS
    per_arrival = len(big.to_json()) / max(1, len(big.slice.arrivals))
    assert per_arrival * publisher.MAX_ARRIVALS < 256 * 1024
