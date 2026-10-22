"""Tests for live mode's clock: ticks reach every deployment of the run
and give the incidents the replay's clock-only slices give, and repeated
or idle ticks change nothing."""

from dataclasses import replace
from datetime import timedelta

import pytest
from botocore.exceptions import ClientError

from telemetry.core.alerts import Incident
from telemetry.core.slices import Slice

from cloud import clock, local, processor
from cloud.messages import Message, state_key
from cloud.store import commit, load_state
from cloud_helpers import RUN, expected, messages, poller
from test_processor import apply, incidents


def state_item(aws, key: str) -> dict:
    """A raw state item.

    Args:
        aws: The ``aws`` fixture.
        key: The state key.

    Returns:
        dict: The item.
    """
    return aws["dynamodb"].get_item(
        TableName=local.TABLES.state, Key={"key": {"S": key}}
    )["Item"]


def tick(message: Message, until) -> Message:
    """A tick for a message's deployment.

    Args:
        message: Any message of the deployment.
        until: Time to run its clock to.

    Returns:
        Message: The tick.
    """
    return replace(message, seq=None, slice=Slice(message.deployment_id, (), until))


def live_part(batch: list[Message]) -> list[Message]:
    """The slices up to the last one with arrivals: what a live collar
    sends before it falls silent.

    Args:
        batch: A deployment's messages.

    Returns:
        list[Message]: The leading slices.
    """
    last = max(i for i, message in enumerate(batch) if message.slice.arrivals)
    return batch[: last + 1]


@pytest.mark.parametrize("step_hours", [1, 6])
def test_ticks_through_the_queue_give_the_replay_incidents(aws, step_hours):
    """A collar that falls silent and is then only ticked by the clock
    raises the same incidents (gap, mortality, potential_death) as the
    replay, whose clock-only slices ticks replace."""
    batch = messages()
    sent = live_part(batch)
    apply(aws, sent)
    start, end = sent[-1].slice.until, batch[-1].slice.until
    step = timedelta(hours=step_hours)
    times = [start + step * i for i in range(1, (end - start) // step + 1)]
    if times[-1] != end:
        times.append(end)
    drain = poller(aws)
    for until in times:
        assert (
            clock.send_ticks(
                aws["dynamodb"],
                aws["sqs"],
                local.TABLES,
                aws["resources"].queue_url,
                RUN,
                until,
            )
            == 1
        )
        drain.drain()
    assert incidents(aws) == expected()
    assert load_state(aws["dynamodb"], local.TABLES, sent[-1].key).seq == len(sent) - 1


def test_tick_that_changes_nothing_is_not_saved(aws):
    """An idle tick writes nothing, so live ticks cost a read, not a
    write; the next message reruns those clock steps."""
    batch = messages()
    apply(aws, batch[:2])
    before = state_item(aws, batch[1].key)
    until = batch[1].slice.until + timedelta(hours=1)
    outcome = processor.process_message(
        tick(batch[1], until), aws["dynamodb"], local.TABLES
    )
    assert outcome == processor.IDLE
    assert state_item(aws, batch[1].key) == before
    assert apply(aws, batch[2:]) == [processor.APPLIED] * (len(batch) - 2)
    assert incidents(aws) == expected()


def test_repeated_tick_is_idle(aws):
    """A tick delivered again, after its clock time has been saved, finds
    nothing to do."""
    batch = messages()
    sent = live_part(batch)
    apply(aws, sent)
    end = batch[-1].slice.until
    assert (
        processor.process_message(tick(sent[-1], end), aws["dynamodb"], local.TABLES)
        == processor.APPLIED
    )
    after = state_item(aws, sent[-1].key)
    assert (
        processor.process_message(tick(sent[-1], end), aws["dynamodb"], local.TABLES)
        == processor.IDLE
    )
    assert state_item(aws, sent[-1].key) == after


def test_tick_for_a_deployment_without_state_is_idle(aws):
    """A deployment that has sent nothing has no clock to run."""
    first = messages()[0]
    outcome = processor.process_message(
        tick(first, first.slice.until), aws["dynamodb"], local.TABLES
    )
    assert outcome == processor.IDLE


def test_saved_tick_keeps_the_sequence_and_needs_it_unchanged(aws):
    """A tick saves under the stored sequence number, so the next slice
    still follows on, and is refused if a slice was applied meanwhile."""
    batch = messages()
    apply(aws, batch[:3])
    saved = load_state(aws["dynamodb"], local.TABLES, batch[2].key)
    now = saved.state.last_arrival
    change = [Incident("A:gap:x", "A", "gap", "open", now, "m")]
    ticked = tick(batch[2], batch[2].slice.until)
    commit(aws["dynamodb"], local.TABLES, ticked, saved.state, change, now, now, 2)
    assert load_state(aws["dynamodb"], local.TABLES, batch[2].key).seq == 2
    with pytest.raises(ClientError):
        commit(aws["dynamodb"], local.TABLES, ticked, saved.state, change, now, now, 1)
    with pytest.raises(ValueError):
        commit(aws["dynamodb"], local.TABLES, ticked, saved.state, [], now, now)


def test_ticks_cover_only_the_run_with_its_settings(aws):
    """The clock ticks each deployment of the run once, with the taxon,
    uploads and boundary its slices carried, and none of another run."""
    batch = messages()
    other = [replace(m, run_id="other-run") for m in batch[:1]]
    # A second deployment of the run, with no fixes yet.
    second = [replace(batch[0], slice=Slice("B", (), batch[0].slice.until))]
    apply(aws, batch[:1] + second + other)
    until = batch[0].slice.until + timedelta(hours=1)
    found = clock.ticks(aws["dynamodb"], local.TABLES, RUN, until)
    assert [m.key for m in found] == [state_key(RUN, "A"), state_key(RUN, "B")]
    assert all(m.is_tick and m.slice.until == until for m in found)
    assert {(m.taxon, m.uploads, m.boundary) for m in found} == {
        (batch[0].taxon, batch[0].uploads, batch[0].boundary)
    }


def test_resent_ticks_are_dropped_by_the_queue(aws):
    """A retried schedule invocation sends the same deduplication IDs, so
    the FIFO queue keeps one tick per deployment."""
    batch = messages()
    apply(aws, batch[:1])
    until = batch[0].slice.until + timedelta(hours=1)
    for _ in range(2):
        clock.send_ticks(
            aws["dynamodb"],
            aws["sqs"],
            local.TABLES,
            aws["resources"].queue_url,
            RUN,
            until,
        )
    attributes = aws["sqs"].get_queue_attributes(
        QueueUrl=aws["resources"].queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )["Attributes"]
    assert attributes["ApproximateNumberOfMessages"] == "1"


def test_handler_reads_the_schedule_input(aws, monkeypatch):
    """The handler takes the run and the scheduled time from the
    schedule's input and the queue from its environment."""
    batch = messages()
    apply(aws, batch[:1])
    for name, value in {
        "STATE_TABLE": local.TABLES.state,
        "INCIDENTS_TABLE": local.TABLES.incidents,
        "QUEUE_URL": aws["resources"].queue_url,
    }.items():
        monkeypatch.setenv(name, value)
    event = {"run_id": RUN, "until": "2009-03-03T00:00:00Z"}
    assert clock.handler(event, None) == {"ticks": 1}
