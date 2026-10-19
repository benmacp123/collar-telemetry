"""Tests for the mortality detector.

0.0001 degrees of latitude is about 11 m, so jitter of a few ten-thousandths
of a degree stays well inside the default 100 m extent.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.detectors.mortality import (
    MortalityConfig,
    MortalityDetector,
    extent,
    extent_with,
    new_cluster,
)
from telemetry.core.fixes import Fix
from telemetry.core.stream import FixStream

START = datetime(2007, 4, 5, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
LAT, LON = 30.5, -86.5


def at(hours):
    """The time ``hours`` after START."""
    return START + hours * HOUR


def still(hours, seed=0, jitter=0.0002):
    """Hourly fixes at one place with GPS-like jitter, at each of ``hours``."""
    rng = random.Random(seed)
    return [
        Fix(
            "A",
            at(h),
            LAT + rng.uniform(-jitter, jitter),
            LON + rng.uniform(-jitter, jitter),
        )
        for h in hours
    ]


def moving(hours, step=0.01):
    """Hourly fixes travelling north about 1.1 km an hour."""
    return [Fix("A", at(h), LAT + (h - hours[0]) * step, LON) for h in hours]


def feed(detector, state, fixes):
    """Give each fix to the detector; return any alerts."""
    alerts = []
    for fix in fixes:
        alerts += detector.on_fix(state, "A", fix)
    return alerts


def test_extent_of_one_point_is_zero():
    """A cluster of one fix has no size."""
    assert extent(new_cluster([Fix("A", START, LAT, LON)])) == 0.0


def test_extent_with_measures_the_stretched_box():
    """Stretching the box to a fix 0.001 degrees north adds about 111 m."""
    cluster = new_cluster([Fix("A", START, LAT, LON)])
    assert extent_with(cluster, Fix("A", START, LAT + 0.001, LON)) == pytest.approx(
        111.2, abs=0.5
    )


def test_stationary_tag_alerts_once_after_the_window():
    """A tag still for two days alerts once, when 24 h have passed."""
    detector, state = MortalityDetector(), {}
    alerts = feed(detector, state, still(range(48)))
    assert len(alerts) == 1
    assert alerts[0].time == at(24)
    assert "Possible mortality or dropped tag" in alerts[0].message
    assert "near 30.5" in alerts[0].message


def test_overnight_roost_is_not_a_death():
    """A 14 h roost between flights stays under the 24 h window."""
    detector, state = MortalityDetector(), {}
    fixes = moving(range(0, 6)) + still(range(6, 20)) + moving(range(20, 30))
    assert not feed(detector, state, fixes)


def test_slow_steady_drift_breaks_the_cluster():
    """Moving 20 m an hour leaves a 100 m box within a day, so no alert."""
    detector, state = MortalityDetector(), {}
    assert not feed(detector, state, moving(range(72), step=0.00018))


def test_one_gps_outlier_does_not_reset_the_cluster():
    """A single stray fix is forgiven when the next fix is back in place."""
    detector, state = MortalityDetector(), {}
    fixes = (
        still(range(12))
        + [Fix("A", at(12), LAT + 0.01, LON)]
        + still(range(13, 30), seed=1)
    )
    alerts = feed(detector, state, fixes)
    assert [alert.time for alert in alerts] == [at(24)]


def test_leaving_resets_the_cluster_and_rearms():
    """Moving away resolves and re-arms; stopping elsewhere alerts again."""
    detector, state = MortalityDetector(), {}
    first = feed(detector, state, still(range(30)))
    trip = feed(detector, state, moving(range(30, 35)))
    elsewhere = [
        Fix("A", f.timestamp, f.lat + 0.1, f.lon) for f in still(range(35, 70))
    ]
    second = feed(detector, state, elsewhere)
    assert len(first) == 1 and len(second) == 1
    assert second[0].time == at(35 + 24)
    # The trip starts on the cluster, so hours 31 and 32 are the two fixes
    # outside it, and the second confirms the move.
    assert [(a.status, a.reason, a.time) for a in trip] == [
        ("resolved", "moved", at(32))
    ]


def test_leaving_an_unalerted_cluster_resolves_nothing():
    """A short rest that never alerted has nothing to resolve."""
    detector, state = MortalityDetector(), {}
    feed(detector, state, still(range(10)))
    assert not feed(detector, state, moving(range(10, 15)))


def test_two_fixes_a_day_apart_are_not_enough():
    """Sparse fixes cannot show a tag is still, whatever the time span."""
    detector, state = MortalityDetector(MortalityConfig(min_fixes=6)), {}
    assert not feed(detector, state, still([0, 30, 60]))


def test_new_cluster_starts_from_the_fixes_that_left():
    """After leaving, the clock restarts from the first fix of the new place."""
    detector, state = MortalityDetector(MortalityConfig(leave_fixes=2)), {}
    feed(detector, state, still(range(10)))
    away = [Fix("A", f.timestamp, f.lat + 0.1, f.lon) for f in still(range(10, 12))]
    feed(detector, state, away)
    assert state["cluster"]["start"] == at(10).isoformat()
    assert state["cluster"]["n"] == 2


def test_spread_out_departure_starts_from_the_last_fix():
    """If the departing fixes are far apart, only the last one is kept."""
    detector, state = MortalityDetector(), {}
    feed(detector, state, still(range(10)))
    away = [Fix("A", at(10), LAT + 0.01, LON), Fix("A", at(11), LAT + 0.02, LON)]
    feed(detector, state, away)
    assert state["cluster"]["start"] == at(11).isoformat()
    assert state["cluster"]["n"] == 1


def test_ticks_never_alert():
    """Only fixes show whether a tag moves; silence is the gap detector's job."""
    detector, state = MortalityDetector(), {}
    feed(detector, state, still(range(10)))
    assert not detector.on_tick(state, "A", at(1000))


@pytest.mark.parametrize("split", [5, 20, 40])
def test_state_round_trips_through_json_in_a_stream(split):
    """Saving and resuming at any point gives the same alerts."""
    fixes = still(range(20)) + moving(range(20, 25)) + still(range(25, 60), seed=2)

    def run(stream, part):
        """Ingest ``part`` into ``stream``; return any alerts."""
        return [alert for fix in part for alert in stream.ingest(fix)]

    expected = run(FixStream([MortalityDetector()]), fixes)
    first = FixStream([MortalityDetector()])
    alerts = run(first, fixes[:split])
    resumed = FixStream.from_dict(
        json.loads(json.dumps(first.to_dict())), [MortalityDetector()]
    )
    alerts += run(resumed, fixes[split:])
    assert alerts == expected
    assert len(expected) == 1


def test_a_short_drag_stays_one_incident():
    """End to end: a carcass dragged 200 m and still again is one incident."""
    stream = FixStream([MortalityDetector()])
    dragged = [
        Fix("A", f.timestamp, f.lat + 0.002, f.lon) for f in still(range(30, 70))
    ]
    events = [e for f in still(range(30)) + dragged for e in stream.ingest(f)]
    assert [(e.status, e.flaps) for e in events] == [
        ("open", 0),
        ("resolved", 0),
        ("open", 1),
    ]
    assert len({e.incident_id for e in events}) == 1
    assert events[-1].opened_at == at(24)
