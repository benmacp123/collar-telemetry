"""Tests for the fix stream: per-deployment state, ticks and JSON round trips."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.fixes import Fix
from telemetry.stream import Alert, AnimalState, FixStream, process_fix

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
    """A tick is given to every deployment, stamped with the tick time."""
    stream = FixStream([CountingDetector()])
    stream.ingest(fix("A", 0))
    stream.ingest(fix("B", 0))
    now = START + timedelta(days=1)
    alerts = stream.tick(now)
    assert {alert.deployment_id for alert in alerts} == {"A", "B"}
    assert all(alert.time == now for alert in alerts)


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
    }
