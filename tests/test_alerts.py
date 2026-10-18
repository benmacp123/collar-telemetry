"""Tests for the alert lifecycle: incidents, de-duplication and flap merging."""

import json
from datetime import datetime, timedelta, timezone

from telemetry.alerts import (
    LATE_FIX,
    OPEN,
    RESOLVED,
    Alert,
    AlertLifecycle,
    Incident,
    LifecycleConfig,
    open_incidents,
)

START = datetime(2016, 4, 19, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def opened(hours, detector="mortality"):
    """An open transition ``hours`` after START."""
    return Alert("A", detector, START + hours * HOUR, f"open at {hours}")


def resolved(hours, detector="mortality", reason="moved"):
    """A resolve transition ``hours`` after START."""
    return Alert(
        "A", detector, START + hours * HOUR, f"resolve at {hours}", RESOLVED, reason
    )


def lifecycle(**windows):
    """A lifecycle with the given merge windows, in hours, by detector."""
    return AlertLifecycle(
        LifecycleConfig({name: hours * HOUR for name, hours in windows.items()})
    )


def test_open_then_resolve_is_one_incident():
    """An episode yields one open and one resolve, sharing an ID."""
    life, state = lifecycle(), {}
    [first] = life.apply(state, [opened(0)])
    [last] = life.apply(state, [resolved(5)])
    assert (first.status, last.status) == (OPEN, RESOLVED)
    assert first.incident_id == last.incident_id
    assert last.resolved_at == START + 5 * HOUR and last.resolution == "moved"
    assert last.message == "open at 0" and last.resolve_message == "resolve at 5"
    assert not open_incidents(state)


def test_incident_id_is_stable():
    """The same opening alert always gives the same ID, so retries de-duplicate."""
    [a] = lifecycle().apply({}, [opened(3)])
    [b] = lifecycle().apply({}, [opened(3)])
    assert (
        a.incident_id
        == b.incident_id
        == f"A:mortality:{(START + 3 * HOUR).isoformat()}"
    )


def test_duplicate_open_and_orphan_resolve_are_dropped_and_counted():
    """A second open, or a resolve with nothing open, makes no incident."""
    life, state = lifecycle(), {}
    assert not life.apply(state, [resolved(0)])
    assert len(life.apply(state, [opened(1), opened(2)])) == 1
    assert state["dropped"] == {"duplicate_open": 1, "orphan_resolve": 1}


def test_detectors_have_separate_incidents():
    """Mortality and gap on the same deployment are independent incidents."""
    life, state = lifecycle(), {}
    events = life.apply(state, [opened(0, "mortality"), opened(1, "gap")])
    assert [event.detector for event in events] == ["mortality", "gap"]
    [done] = life.apply(state, [resolved(2, "gap", "fix_received")])
    assert done.detector == "gap"
    assert [i.detector for i in open_incidents(state)] == ["mortality"]


def test_reopen_within_the_window_continues_the_incident():
    """A flap inside merge_within reopens the same incident, counted as a flap."""
    life, state = lifecycle(mortality=36), {}
    [first] = life.apply(state, [opened(0)])
    [gone] = life.apply(state, [resolved(10)])
    [back] = life.apply(state, [opened(40)])
    assert gone.status == RESOLVED and back.status == OPEN
    assert back.incident_id == first.incident_id
    assert back.opened_at == START and back.flaps == 1
    assert back.resolved_at is None and back.resolution is None
    [last] = life.apply(state, [resolved(50)])
    assert last.flaps == 1 and last.resolved_at == START + 50 * HOUR


def test_reopen_after_the_window_is_a_new_incident():
    """Past merge_within, an open starts a new incident."""
    life, state = lifecycle(mortality=36), {}
    life.apply(state, [opened(0), resolved(10)])
    [new] = life.apply(state, [opened(47)])
    assert new.opened_at == START + 47 * HOUR and new.flaps == 0


def test_without_a_window_resolves_are_final():
    """A detector with no merge window never reopens an incident."""
    life, state = lifecycle(), {}
    life.apply(state, [opened(0, "gap"), resolved(1, "gap", "fix_received")])
    [new] = life.apply(state, [opened(2, "gap")])
    assert new.opened_at == START + 2 * HOUR
    assert state["recent"] == {}


def test_a_resolve_older_than_the_open_is_flagged_late():
    """A late-uploaded fix still resolves a gap, but as a latency false alarm."""
    life, state = lifecycle(), {}
    life.apply(state, [opened(10, "gap")])
    [done] = life.apply(state, [resolved(8, "gap", "fix_received")])
    assert done.resolution == LATE_FIX


def test_state_and_incidents_survive_json():
    """Lifecycle state and incidents round-trip through JSON mid-flap."""
    life, state = lifecycle(mortality=36), {}
    first, _ = life.apply(state, [opened(0), resolved(4)])
    state = json.loads(json.dumps(state))
    [back] = life.apply(state, [opened(30)])
    assert back.incident_id == first.incident_id
    assert Incident.from_dict(json.loads(json.dumps(back.to_dict()))) == back
