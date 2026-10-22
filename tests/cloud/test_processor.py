"""Tests for the processor handler and its store: messages applied once,
in order, with state and incidents saved together."""

import json
import zlib
from dataclasses import replace

import pytest
from botocore.exceptions import ClientError

from telemetry.core.alerts import Incident

from cloud import local, processor
from cloud.messages import state_key
from cloud.store import (
    MAX_INCIDENTS,
    commit,
    item_size,
    load_state,
    pack_state,
    run_incidents,
    unpack_state,
    write_units,
)
from cloud_helpers import RUN, expected, messages, sqs_records


def stored(aws) -> dict:
    """Stored incident items for the test run, by incident ID.

    Args:
        aws: The ``aws`` fixture.

    Returns:
        dict: Raw items by incident ID.
    """
    return {
        item["incident_id"]["S"]: item
        for item in run_incidents(aws["dynamodb"], local.TABLES, RUN)
    }


def incidents(aws) -> dict:
    """Stored incidents for the test run, as dicts, by incident ID.

    Args:
        aws: The ``aws`` fixture.

    Returns:
        dict: Incident dicts by incident ID.
    """
    return {key: json.loads(item["incident"]["S"]) for key, item in stored(aws).items()}


def apply(aws, batch) -> list[str]:
    """Process messages one at a time, as the handler would.

    Args:
        aws: The ``aws`` fixture.
        batch: Messages.

    Returns:
        list[str]: Each message's outcome.
    """
    return [
        processor.process_message(message, aws["dynamodb"], local.TABLES)
        for message in batch
    ]


@pytest.mark.parametrize("scenario", ["satellite_daily", "gsm"])
def test_sliced_messages_store_the_replay_incidents(aws, scenario):
    """Applying every slice gives exactly the incidents of one pass."""
    batch = messages(scenario)
    assert set(apply(aws, batch)) == {processor.APPLIED}
    assert incidents(aws) == expected(scenario)
    saved = load_state(aws["dynamodb"], local.TABLES, state_key(RUN, "A"))
    assert saved.seq == len(batch) - 1


def test_split_slices_store_the_same_incidents(aws):
    """Slices split by ``max_arrivals`` still give the one-pass incidents."""
    batch = messages(max_arrivals=5)
    assert len(batch) > len(messages())
    apply(aws, batch)
    assert incidents(aws) == expected()


def test_redelivered_message_is_skipped_and_changes_nothing(aws):
    """A message seen again (SQS redelivery after a crash between the write
    and the delete) is a no-op."""
    batch = messages()
    apply(aws, batch[:6])
    before_state = aws["dynamodb"].get_item(
        TableName=local.TABLES.state, Key={"key": {"S": state_key(RUN, "A")}}
    )["Item"]
    before = stored(aws)
    assert apply(aws, [batch[5], batch[2]]) == [processor.DUPLICATE] * 2
    after_state = aws["dynamodb"].get_item(
        TableName=local.TABLES.state, Key={"key": {"S": state_key(RUN, "A")}}
    )["Item"]
    assert after_state == before_state
    assert stored(aws) == before


def test_retried_batch_after_crash_gives_the_same_result(aws):
    """Running a whole batch twice, as after a handler timeout, stores the
    same incidents as running it once."""
    batch = messages()
    records = sqs_records(batch)
    for _ in range(2):
        response = processor.process_records(records, aws["dynamodb"], local.TABLES)
        assert response == {"batchItemFailures": []}
    assert incidents(aws) == expected()


def test_message_ahead_of_its_predecessor_fails(aws):
    """A gap in the sequence stops the deployment instead of skipping."""
    batch = messages()
    apply(aws, batch[:2])
    with pytest.raises(processor.OutOfOrder):
        processor.process_message(batch[3], aws["dynamodb"], local.TABLES)
    assert apply(aws, batch[2:4]) == [processor.APPLIED] * 2


def test_first_message_must_be_number_zero(aws):
    """A deployment with no state accepts only its first slice."""
    with pytest.raises(processor.OutOfOrder):
        processor.process_message(messages()[1], aws["dynamodb"], local.TABLES)


def test_batch_reports_the_failure_and_everything_after_it(aws):
    """Later records are not applied past a failed one, so none overtakes
    it, and they succeed once retried in order."""
    batch = messages()
    records = sqs_records([batch[0], batch[2], batch[1], batch[3]])
    response = processor.process_records(records, aws["dynamodb"], local.TABLES)
    assert response["batchItemFailures"] == [
        {"itemIdentifier": "m2"},
        {"itemIdentifier": "m1"},
        {"itemIdentifier": "m3"},
    ]
    saved = load_state(aws["dynamodb"], local.TABLES, state_key(RUN, "A"))
    assert saved.seq == 0
    retry = sqs_records(batch[1:])
    assert processor.process_records(retry, aws["dynamodb"], local.TABLES) == {
        "batchItemFailures": []
    }
    assert incidents(aws) == expected()


@pytest.mark.parametrize(
    "changed, code",
    [
        (False, "ConditionalCheckFailedException"),
        (True, "TransactionCanceledException"),
    ],
)
def test_concurrent_write_is_rejected(aws, changed, code):
    """The conditional put refuses a second writer for the same sequence
    number, with or without incidents, so two invocations cannot both apply
    a message."""
    first = messages()[0]
    apply(aws, [first])
    saved = load_state(aws["dynamodb"], local.TABLES, first.key)
    now = saved.state.last_arrival
    changes = [Incident("A:gap:x", "A", "gap", "open", now, "m")] if changed else []
    with pytest.raises(ClientError) as error:
        commit(aws["dynamodb"], local.TABLES, first, saved.state, changes, now, now)
    assert error.value.response["Error"]["Code"] == code


class Recorder:
    """A DynamoDB client that records which write call each save used."""

    def __init__(self, client):
        """Wrap a client.

        Args:
            client: A boto3 DynamoDB client.
        """
        self.client = client
        self.calls = []

    def __getattr__(self, name):
        """The wrapped client's attribute, recording write calls.

        Args:
            name: The attribute.

        Returns:
            The attribute, wrapped if it is a write call.
        """
        attribute = getattr(self.client, name)
        if name not in ("put_item", "transact_write_items"):
            return attribute

        def record(**kwargs):
            """Record the call and pass it on."""
            self.calls.append(name)
            return attribute(**kwargs)

        return record


def test_transaction_only_when_incidents_change(aws):
    """Messages that change no incident are saved with a plain put, so
    they are not billed twice; the rest use a transaction."""
    recorder = Recorder(aws["dynamodb"])
    used = []
    for message in messages():
        before = stored(aws)
        processor.process_message(message, recorder, local.TABLES)
        used.append((recorder.calls[-1], stored(aws) != before))
    assert {call for call, changed in used if changed} == {"transact_write_items"}
    assert {call for call, changed in used if not changed} == {"put_item"}
    assert incidents(aws) == expected()


def test_state_is_stored_compressed(aws):
    """The state attribute is zlib-compressed JSON of the state, smaller
    than the JSON, and reads back unchanged."""
    batch = messages()
    apply(aws, batch)
    item = aws["dynamodb"].get_item(
        TableName=local.TABLES.state, Key={"key": {"S": batch[-1].key}}
    )["Item"]
    saved = load_state(aws["dynamodb"], local.TABLES, batch[-1].key)
    text = json.dumps(saved.state.to_dict(), separators=(",", ":"))
    assert json.loads(zlib.decompress(item["state"]["B"])) == json.loads(text)
    assert len(item["state"]["B"]) < len(text)
    assert unpack_state(pack_state(saved.state)) == saved.state


def test_item_size_follows_dynamodb_rules():
    """Names and values count as DynamoDB bills them: UTF-8 bytes for
    strings, length for binary, two digits a byte plus one for numbers."""
    assert item_size({"ab": {"S": "é"}}) == 2 + 2
    assert item_size({"b": {"B": b"\x00" * 10}}) == 1 + 10
    assert item_size({"n": {"N": "12345"}}) == 1 + 3 + 1
    assert item_size({"n": {"N": "100"}}) == 1 + 1 + 1
    with pytest.raises(ValueError):
        item_size({"m": {"M": {}}})


def test_write_units_round_up_per_kilobyte_and_double_in_transactions():
    """A write bills one unit per started kilobyte, at least one, and a
    transaction bills twice."""
    assert write_units(0, transaction=False) == 1
    assert write_units(1024, transaction=False) == 1
    assert write_units(1025, transaction=False) == 2
    assert write_units(1025, transaction=True) == 4


def test_too_many_incidents_for_one_transaction_fail(aws):
    """A message whose incidents cannot be saved atomically is refused,
    not split."""
    first = messages()[0]
    many = [
        Incident(f"A:gap:{i}", "A", "gap", "open", first.slice.until, "m")
        for i in range(MAX_INCIDENTS + 1)
    ]
    with pytest.raises(ValueError):
        commit(
            aws["dynamodb"],
            local.TABLES,
            first,
            None,
            many,
            first.slice.until,
            first.slice.until,
        )


def test_incident_update_keeps_notified_mark_and_first_times(aws):
    """Rewriting an incident keeps ``notified_at`` and the first write's
    wall-clock times."""
    batch = messages()
    apply(aws, batch)
    key, item = next(iter(stored(aws).items()))
    aws["dynamodb"].update_item(
        TableName=local.TABLES.incidents,
        Key={"run_id": {"S": RUN}, "incident_id": {"S": key}},
        UpdateExpression="SET notified_at = :t",
        ExpressionAttributeValues={":t": {"S": "2026-10-20T00:00:00+00:00"}},
    )
    incident = Incident.from_dict(json.loads(item["incident"]["S"]))
    saved = load_state(aws["dynamodb"], local.TABLES, batch[-1].key)
    later = replace(batch[-1], seq=len(batch))
    now = saved.state.last_arrival
    commit(aws["dynamodb"], local.TABLES, later, saved.state, [incident], now, now)
    after = stored(aws)[key]
    assert after["notified_at"] == {"S": "2026-10-20T00:00:00+00:00"}
    assert after["first_seq"] == item["first_seq"]
    assert after["first_stored_at"] == item["first_stored_at"]
    assert after["seq"] == {"N": str(len(batch))}
