"""Tests for the mortality detector.

0.0001 degrees of latitude is about 11 m, so jitter of a few ten-thousandths
of a degree stays well inside the default 100 m extent.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.alerts import NATAL_NEST
from telemetry.core.detectors.mortality import (
    MortalityConfig,
    MortalityDetector,
    NatalConfig,
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
    assert alerts[0].message.startswith("Stationary: check. ")
    assert "could be a death or a dropped tag" in alerts[0].message
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


def scatter_after_alert():
    """A still cluster that alerts, then fixes 55 m north and twice 55 m south.

    The south pair stretches the box to about 110 m, past the 100 m
    extent, though no fix is more than 55 m from where the tag lies.
    """
    offset = 0.0005  # about 55 m of latitude
    return still(range(30), jitter=0.00005) + [
        Fix("A", at(30), LAT + offset, LON),
        Fix("A", at(31), LAT - offset, LON),
        Fix("A", at(32), LAT - offset, LON),
    ]


def test_box_alone_resolves_a_scattered_carcass():
    """Without a radius, two fixes past the grown box read as a move."""
    detector = MortalityDetector(MortalityConfig(leave_radius_m=None))
    alerts = feed(detector, {}, scatter_after_alert())
    assert [(a.status, a.time) for a in alerts] == [
        ("open", at(24)),
        ("resolved", at(32)),
    ]


def test_leave_radius_keeps_a_scattered_carcass_alerted():
    """With a 60 m radius from the alert's centre, the scatter stays put."""
    detector = MortalityDetector(MortalityConfig(leave_radius_m=60.0))
    alerts = feed(detector, {}, scatter_after_alert())
    assert [(a.status, a.time) for a in alerts] == [("open", at(24))]


def test_leave_radius_still_resolves_a_real_move():
    """A real departure resolves at the same fix as with the box test."""
    detector, state = MortalityDetector(MortalityConfig(leave_radius_m=60.0)), {}
    feed(detector, state, still(range(30)))
    trip = feed(detector, state, moving(range(30, 35)))
    assert [(a.status, a.time) for a in trip] == [("resolved", at(32))]
    assert "anchor" not in state


def test_leave_radius_centre_is_fixed_at_the_alert():
    """The centre is fixed at the alert and later fixes do not move it."""
    detector, state = MortalityDetector(MortalityConfig(leave_radius_m=60.0)), {}
    fixes = still(range(40))
    feed(detector, state, fixes[:24])
    assert "anchor" not in state
    alerts = feed(detector, state, fixes[24:25])
    assert [a.time for a in alerts] == [at(24)]
    centre = [state["cluster"]["sum_lat"] / 25, state["cluster"]["sum_lon"] / 25]
    feed(detector, state, fixes[25:])
    assert state["anchor"] == centre


def test_box_only_state_has_no_anchor():
    """Without a radius the state holds no centre, as before the radius."""
    detector, state = MortalityDetector(MortalityConfig(leave_radius_m=None)), {}
    feed(detector, state, still(range(30)))
    assert state["open"] and "anchor" not in state


def test_default_keeps_a_scattered_carcass_alerted():
    """The default 75 m radius holds the scatter that breaks the box."""
    alerts = feed(MortalityDetector(), {}, scatter_after_alert())
    assert [a.status for a in alerts] == ["open"]


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


NEST = NatalConfig(radius_m=500.0, days=30, anchor_fixes=24)


def still_north(hours, north_m):
    """Still hourly fixes about ``north_m`` metres north of the start."""
    return [
        Fix(f.deployment_id, f.timestamp, f.lat + north_m / 111_000, f.lon)
        for f in still(hours, seed=hours[0])
    ]


def natal_alerts(fixes, natal=NEST):
    """Feed ``fixes`` to a detector with the natal context; return its opens."""
    detector = MortalityDetector(MortalityConfig(natal=natal))
    return [a for a in feed(detector, {}, fixes) if a.status != "resolved"]


def test_nestling_that_never_left_is_marked_at_natal_nest():
    """A bird still where its track began alerts with the natal context and
    says so in the message."""
    [alert] = natal_alerts(still(range(30)))
    assert alert.context == NATAL_NEST
    assert alert.message.startswith("Stationary at natal nest: check.")
    assert "still since" in alert.message


def test_stillness_away_from_the_nest_has_no_context():
    """After leaving, stillness 5 km away is an ordinary watch alert."""
    fixes = still(range(30)) + moving(range(30, 36)) + still_north(range(36, 70), 5_000)
    alerts = natal_alerts(fixes)
    assert [a.context for a in alerts] == [NATAL_NEST, None]
    assert alerts[-1].message.startswith("Stationary: check.")


def test_return_to_the_nest_in_the_first_days_is_marked():
    """A young bird back within the radius of the nest is marked again."""
    fixes = (
        still(range(30))
        + still_north(range(30, 40), 3_000)
        + still_north(range(40, 80), 200)
    )
    assert [a.context for a in natal_alerts(fixes)] == [NATAL_NEST, NATAL_NEST]


def test_return_after_the_natal_days_is_not_marked():
    """Back at the nest after ``days`` (an adult breeding there) is ordinary."""
    late = 31 * 24
    fixes = (
        still(range(30))
        + still_north(range(30, 40), 3_000)
        + still_north(range(late, late + 40), 200)
    )
    assert [a.context for a in natal_alerts(fixes)] == [NATAL_NEST, None]


def test_a_stray_first_fix_does_not_count_as_leaving():
    """One stray fix 2 km off among the first fixes neither moves the anchor
    nor marks the bird as gone."""
    [first, *rest] = still(range(30))
    stray = Fix(first.deployment_id, first.timestamp, first.lat + 0.018, first.lon)
    [alert] = natal_alerts([stray] + rest)
    assert alert.context == NATAL_NEST


def test_leaving_within_the_anchor_fixes_still_counts():
    """A bird that goes beyond the radius while the anchor is being built
    has left, judged once the anchor is complete."""
    fixes = (
        still(range(10))
        + still_north(range(10, 30), 3_000)
        + still_north(range(30, 70), 3_000)
    )
    alerts = natal_alerts(fixes, NatalConfig(radius_m=500.0, anchor_fixes=12))
    assert [a.context for a in alerts] == [None]


def test_a_trip_and_return_inside_the_anchor_fixes_counts_as_leaving():
    """A bird that went beyond the radius and came back before the anchor
    was complete has still left; with no natal days, it is not marked."""
    fixes = (
        still(range(4)) + still_north(range(4, 7), 3_000) + still(range(7, 60), seed=7)
    )
    alerts = natal_alerts(fixes, NatalConfig(radius_m=500.0, days=0, anchor_fixes=12))
    assert [a.context for a in alerts] == [None]


def test_natal_context_is_off_by_default():
    """Without natal settings the detector keeps no natal state and marks
    nothing."""
    detector, state = MortalityDetector(), {}
    [alert] = feed(detector, state, still(range(30)))
    assert alert.context is None and "natal" not in state
    assert "context" not in alert.to_dict()


def test_natal_state_round_trips_through_json_in_a_stream():
    """Saving and resuming mid-anchor gives the same contexts."""
    config = MortalityConfig(natal=NEST)
    fixes = still(range(10)) + moving(range(10, 16)) + still_north(range(16, 60), 9_000)

    def run(stream, part):
        """Ingest ``part`` into ``stream``; return its incidents."""
        return [incident for fix in part for incident in stream.ingest(fix)]

    expected = run(FixStream([MortalityDetector(config)]), fixes)
    first = FixStream([MortalityDetector(config)])
    incidents = run(first, fixes[:12])
    resumed = FixStream.from_dict(
        json.loads(json.dumps(first.to_dict())), [MortalityDetector(config)]
    )
    incidents += run(resumed, fixes[12:])
    assert incidents == expected
    assert [i.context for i in expected] == [None]
