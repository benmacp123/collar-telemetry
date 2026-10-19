"""Tests for the fix stream: per-deployment state, ticks and JSON round trips."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.fixes import Arrival, Fix
from telemetry.core.stream import Alert, AnimalState, FixStream, advance, process_fix

START = datetime(2016, 4, 19, tzinfo=timezone.utc)


def fix(deployment_id, hours, lat=30.5, lon=-86.5):
    """A fix for ``deployment_id`` ``hours`` after START."""
    return Fix(deployment_id, START + timedelta(hours=hours), lat, lon)


class CountingDetector:
    """Counts fixes and alerts on every ``every``-th one, and on ticks."""

    def __init__(self, name="count", every=3):
        """Name the detector and set how often it alerts."""
        self.name = name
        self.every = every

    def on_fix(self, state, deployment_id, fix):
        """Count the fix and alert on every ``every``-th one."""
        state["n"] = state.get("n", 0) + 1
        if state["n"] % self.every:
            return []
        return [Alert(deployment_id, self.name, fix.timestamp, f"fix {state['n']}")]

    def on_tick(self, state, deployment_id, now):
        """Alert on every tick, reporting the count so far."""
        return [Alert(deployment_id, self.name, now, f"tick after {state.get('n', 0)}")]


def test_each_deployment_has_its_own_state():
    """Interleaved fixes for two deployments are counted separately."""
    stream = FixStream([CountingDetector(every=2)])
    alerts = [
        alert
        for hours, deployment in enumerate(["A", "B", "A", "B", "A"])
        for alert in stream.ingest(fix(deployment, hours))
    ]
    assert [alert.deployment_id for alert in alerts] == ["A", "B"]
    assert stream.states["A"].fixes_seen == 3
    assert stream.states["B"].detectors == {"count": {"n": 2}}


def test_detectors_get_separate_state():
    """Each detector's state lives under its own name."""
    stream = FixStream([CountingDetector("one"), CountingDetector("two")])
    stream.ingest(fix("A", 0))
    assert stream.states["A"].detectors == {"one": {"n": 1}, "two": {"n": 1}}


def test_duplicate_detector_names_rejected():
    """Two detectors with one name would share state, so it is an error."""
    with pytest.raises(ValueError, match="unique"):
        FixStream([CountingDetector(), CountingDetector()])


def test_latest_fix_is_by_timestamp_not_arrival():
    """A late arrival does not replace a newer fix as the latest."""
    stream = FixStream([])
    stream.ingest(fix("A", 5))
    stream.ingest(fix("A", 2))  # late arrival
    assert stream.states["A"].latest_fix.timestamp == START + timedelta(hours=5)
    assert stream.states["A"].fixes_seen == 2


def test_fix_for_another_deployment_rejected():
    """A fix sent to the wrong deployment's state is an error, not corruption."""
    with pytest.raises(ValueError, match="sent to state"):
        process_fix(AnimalState("A"), fix("B", 0), [])


def test_tick_reaches_every_deployment():
    """A tick reaches every deployment; repeats of an open alert are dropped."""
    stream = FixStream([CountingDetector()])
    stream.ingest(fix("A", 0))
    stream.ingest(fix("B", 0))
    now = START + timedelta(days=1)
    incidents = stream.tick(now)
    assert {incident.deployment_id for incident in incidents} == {"A", "B"}
    assert all(incident.opened_at == now for incident in incidents)
    # CountingDetector re-raises on every tick, but each incident is open.
    assert not stream.tick(now + timedelta(hours=1))
    assert stream.states["A"].alerts["dropped"]["duplicate_open"] == 1
    assert len(stream.open_incidents()) == 2


def test_state_survives_a_json_round_trip():
    """Splitting a stream across saves must not change its alerts."""
    fixes = [fix("A", hours, lat=30.5 + hours / 100) for hours in range(7)]

    whole = FixStream([CountingDetector()])
    expected = [alert for f in fixes for alert in whole.ingest(f)]

    first = FixStream([CountingDetector()])
    alerts = [alert for f in fixes[:4] for alert in first.ingest(f)]
    saved = json.dumps(first.to_dict())
    resumed = FixStream.from_dict(json.loads(saved), [CountingDetector()])
    alerts += [alert for f in fixes[4:] for alert in resumed.ingest(f)]

    assert alerts == expected
    assert resumed.to_dict() == whole.to_dict()


def test_empty_state_round_trips():
    """A fresh state survives JSON unchanged."""
    state = AnimalState("A")
    assert AnimalState.from_dict(json.loads(json.dumps(state.to_dict()))) == state


def test_alert_to_dict():
    """Alerts serialise to plain JSON with an ISO 8601 time."""
    alert = Alert("A", "count", START, "fix 3")
    assert json.loads(json.dumps(alert.to_dict())) == {
        "deployment_id": "A",
        "detector": "count",
        "time": "2016-04-19T00:00:00+00:00",
        "message": "fix 3",
        "status": "open",
        "reason": None,
    }


def test_ticks_and_arrivals_stamp_raised_time():
    """Incidents record the arrival or tick time, not the evidence time."""
    stream = FixStream([CountingDetector(every=1)])
    arrived = START + timedelta(days=2)
    [incident] = stream.ingest(fix("A", 0), now=arrived)
    assert incident.opened_at == START and incident.raised_at == arrived


class RecordingDetector:
    """Records the order of fixes and ticks it sees; never alerts."""

    name = "record"

    def on_fix(self, state, deployment_id, fix):
        """Record the fix's hour offset from START."""
        state.setdefault("log", []).append(["fix", hours_after(fix.timestamp)])
        return []

    def on_tick(self, state, deployment_id, now):
        """Record the tick's hour offset from START."""
        state.setdefault("log", []).append(["tick", hours_after(now)])
        return []


def hours_after(time):
    """Hours from START to ``time``."""
    return (time - START) / timedelta(hours=1)


def arrive(hours, taken=None):
    """An arrival for deployment A ``hours`` after START."""
    return Arrival(
        START + timedelta(hours=hours), fix("A", hours if taken is None else taken)
    )


def test_advance_interleaves_ticks_and_arrivals():
    """Ticks start after the first arrival; a tick at an arrival's instant
    runs after it; ``until`` runs ticks up to and including it."""
    state = AnimalState("A")
    detectors = [RecordingDetector()]
    advance(
        state,
        [arrive(0.5), arrive(2), arrive(2.5)],
        START + timedelta(hours=4),
        detectors,
    )
    assert state.detectors["record"]["log"] == [
        ["fix", 0.5],
        ["tick", 1],
        ["fix", 2],
        ["tick", 2],
        ["fix", 2.5],
        ["tick", 3],
        ["tick", 4],
    ]
    assert state.next_tick == START + timedelta(hours=5)


def test_advance_without_arrivals_does_not_start_the_clock():
    """A clock-only call before the first arrival runs no ticks."""
    state = AnimalState("A")
    assert not advance(state, [], START + timedelta(days=1), [RecordingDetector()])
    assert state.next_tick is None and not state.detectors


def test_advance_rejects_an_arrival_before_a_tick_already_run():
    """An arrival the clock has already passed would change results by
    split, so it is an error."""
    state = AnimalState("A")
    advance(state, [arrive(0.5)], START + timedelta(hours=2), [RecordingDetector()])
    with pytest.raises(ValueError, match="not after the tick"):
        advance(state, [arrive(2)], None, [RecordingDetector()])
    advance(state, [arrive(2.1)], None, [RecordingDetector()])


def test_advance_rejects_an_arrival_before_the_last_one():
    """Arrivals must come in arrival order."""
    state = AnimalState("A")
    advance(state, [arrive(5)], None, [RecordingDetector()])
    with pytest.raises(ValueError, match="before the last arrival"):
        advance(state, [arrive(4.5)], None, [RecordingDetector()])


def test_clock_cursor_survives_a_json_round_trip():
    """The tick cursor and last arrival are saved with the state."""
    state = AnimalState("A")
    advance(state, [arrive(0.5)], START + timedelta(hours=3), [RecordingDetector()])
    again = AnimalState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert again == state
    assert again.next_tick == START + timedelta(hours=4)


def test_arrivals_at_the_instant_of_an_on_grid_first_arrival_are_accepted():
    """No tick runs at the first arrival's instant, so a batch arriving
    exactly on the hour is not mistaken for a late arrival."""
    state = AnimalState("A")
    batch = [arrive(3, taken=1), arrive(3, taken=2)]
    advance(state, batch[:1], None, [RecordingDetector()])
    advance(state, batch[1:], START + timedelta(hours=4), [RecordingDetector()])
    assert state.detectors["record"]["log"] == [["fix", 1], ["fix", 2], ["tick", 4]]
    assert state.last_tick == START + timedelta(hours=4)
