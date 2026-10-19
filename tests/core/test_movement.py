"""Tests for the unusual-movement detector.

The normal track wanders back and forth about 500 m an hour, so its 3 h
net displacement stays around 1-1.5 km.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.detectors.movement import (
    N_BINS,
    MovementConfig,
    MovementDetector,
    bin_index,
    bin_upper,
    histogram_quantile,
)
from telemetry.core.fixes import Fix
from telemetry.core.stream import FixStream

START = datetime(2008, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
LAT, LON = -24.5, 31.7
# 0.0045 degrees of latitude is about 500 m.
STEP = 0.0045


def at(hours):
    """The time ``hours`` after START."""
    return START + hours * HOUR


def wander(hours, lat=LAT):
    """Hourly fixes going north and back over a 3 km beat, 500 m an hour."""
    fixes = []
    for h in hours:
        phase = h % 12
        offset = phase if phase < 6 else 12 - phase
        fixes.append(Fix("A", at(h), lat + offset * STEP, LON))
    return fixes


def dash(hours, km_per_hour=10.0):
    """Hourly fixes heading north at ``km_per_hour`` from LAT."""
    start = hours[0]
    return [
        Fix("A", at(h), LAT + (h - start) * km_per_hour / 111.2, LON) for h in hours
    ]


def feed(detector, state, fixes):
    """Give each fix to the detector; return any alerts."""
    alerts = []
    for fix in fixes:
        alerts += detector.on_fix(state, "A", fix)
    return alerts


def test_bins_cover_metres_to_megametres():
    """Bins start at 1 m, are about 26% wide and clamp at 1,000 km."""
    assert bin_index(0.5) == 0
    assert bin_index(10) == 10
    assert bin_index(1e9) == N_BINS - 1
    assert bin_upper(9) == pytest.approx(10.0)


def test_histogram_quantile():
    """The quantile is the upper edge of the bin where the weight crosses it."""
    weights = [0.0] * N_BINS
    weights[bin_index(100)] = 99.0
    weights[bin_index(10_000)] = 1.0
    assert histogram_quantile(weights, 0.5) == bin_upper(bin_index(100))
    assert histogram_quantile(weights, 1.0) == bin_upper(bin_index(10_000))
    assert histogram_quantile([0.0] * N_BINS, 0.99) == 0.0


def test_normal_movement_never_alerts():
    """Three weeks of the animal's usual beat raise nothing."""
    detector, state = MovementDetector(), {}
    assert not feed(detector, state, wander(range(21 * 24)))


def test_sustained_dash_alerts_once():
    """After a normal fortnight, a 10 km/h run alerts once, not every hour."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(14 * 24)))
    alerts = feed(detector, state, dash(range(14 * 24, 14 * 24 + 8)))
    assert len(alerts) == 1
    assert "Unusual movement" in alerts[0].message
    # 3 h at 10 km/h is 30 km, far beyond the 2 km floor and 2x normal.
    assert alerts[0].time <= at(14 * 24 + 3)


def test_rearms_after_returning_to_normal():
    """Settling down resolves the alert, and a second run alerts again."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(14 * 24)))
    first = feed(detector, state, dash(range(14 * 24, 14 * 24 + 6)))
    calm = feed(detector, state, wander(range(14 * 24 + 6, 16 * 24), lat=LAT + 0.5))
    second = feed(detector, state, dash(range(16 * 24, 16 * 24 + 6)))
    assert len(first) == 1 and len(second) == 1
    assert [(a.status, a.reason) for a in calm] == [("resolved", "normal")]
    assert second[0].status == "open"


def test_no_alert_during_warmup():
    """A run in the first week cannot be judged against a baseline yet."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(3 * 24)))
    assert not feed(detector, state, dash(range(3 * 24, 3 * 24 + 6)))


def test_floor_stops_a_sedentary_animal_alerting_on_a_short_walk():
    """An animal that barely moves does not alert on a 1 km walk."""
    detector, state = MovementDetector(), {}
    sedentary = [Fix("A", at(h), LAT + (h % 2) * 0.0001, LON) for h in range(14 * 24)]
    feed(detector, state, sedentary)
    walk = dash(range(14 * 24, 14 * 24 + 6), km_per_hour=0.3)
    assert not feed(detector, state, walk)


def test_distance_across_a_gap_is_not_movement():
    """After a 2-day silence, the jump to a new place is not judged as speed."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(14 * 24)))
    later = Fix("A", at(14 * 24 + 48), LAT + 0.5, LON)  # 55 km away
    assert not feed(detector, state, [later])
    assert len(state["window"]) == 1


def test_fast_tags_are_measured_over_the_same_span():
    """With 1-minute fixes the window spans 3 h, not 3 fixes."""
    detector, state = MovementDetector(), {}
    minutes = [
        Fix("A", START + timedelta(minutes=m), LAT, LON) for m in range(0, 4 * 60)
    ]
    feed(detector, state, minutes)
    assert len(state["window"]) == 3 * 60 + 1


def test_ticks_never_alert():
    """Movement is only seen in fixes."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(24)))
    assert not detector.on_tick(state, "A", at(1000))


@pytest.mark.parametrize("split", [100, 336, 340])
def test_state_round_trips_through_json_in_a_stream(split):
    """Saving and resuming at any point gives the same alerts."""
    fixes = wander(range(14 * 24)) + dash(range(14 * 24, 14 * 24 + 8))

    def run(stream, part):
        """Ingest ``part`` into ``stream``; return any alerts."""
        return [alert for fix in part for alert in stream.ingest(fix)]

    expected = run(FixStream([MovementDetector()]), fixes)
    first = FixStream([MovementDetector()])
    alerts = run(first, fixes[:split])
    resumed = FixStream.from_dict(
        json.loads(json.dumps(first.to_dict())),
        [MovementDetector(MovementConfig())],
    )
    alerts += run(resumed, fixes[split:])
    assert alerts == expected
    assert len(expected) == 1


def test_an_episode_does_not_raise_the_bar_for_the_next():
    """Measurements during an alert are not learned into the baseline."""
    detector, state = MovementDetector(), {}
    feed(detector, state, wander(range(14 * 24)))
    before = list(state["weights"])
    feed(detector, state, dash(range(14 * 24, 14 * 24 + 4)))
    assert state["weights"][-20:] == pytest.approx([w for w in before[-20:]], rel=0.1)
    assert state["open"]


def test_a_long_episode_closes_and_learning_resumes():
    """A move that lasts past max_episode re-arms, so the baseline adapts."""
    config = MovementConfig(max_episode=timedelta(hours=6))
    detector, state = MovementDetector(config), {}
    feed(detector, state, wander(range(14 * 24)))
    # The episode opens an hour into the run and closes 6 h later.
    alerts = feed(detector, state, dash(range(14 * 24, 14 * 24 + 8)))
    assert not state["open"]
    assert [(a.status, a.reason) for a in alerts] == [
        ("open", None),
        ("resolved", "expired"),
    ]


def test_quantile_past_the_last_bin_returns_the_top_edge():
    """Rounding can leave the running total short; the top bin is the answer."""
    weights = [0.0] * N_BINS
    weights[0] = 1.0
    assert histogram_quantile(weights, 1.5) == bin_upper(N_BINS - 1)


def test_no_alert_without_enough_measurements():
    """Past the warm-up but with too few measurements, nothing alerts."""
    detector, state = MovementDetector(MovementConfig(min_samples=1000)), {}
    feed(detector, state, wander(range(14 * 24)))
    assert not feed(detector, state, dash(range(14 * 24, 14 * 24 + 6)))
