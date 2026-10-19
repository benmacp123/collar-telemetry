"""Tests for synthetic mortality injection."""

import random
import statistics
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.detectors.mortality import MortalityConfig, MortalityDetector
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m, offset
from telemetry.core.stream import FixStream
from telemetry.sim.synthetic import (
    CarcassConfig,
    choose_death_time,
    inject_mortality,
    scatter_distance,
)

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def walk(hours):
    """Hourly fixes moving steadily north-east, about 1.5 km an hour."""
    return [
        Fix("J1", START + h * HOUR, -19.0 + h * 0.01, 15.5 + h * 0.01)
        for h in range(hours)
    ]


def test_offset_moves_the_requested_distance():
    """The flat-Earth offset is accurate at GPS-scatter distances."""
    lat, lon = offset(-19.0, 15.5, 37.0, 250.0)
    assert haversine_m(-19.0, 15.5, lat, lon) == pytest.approx(250.0, rel=1e-3)


def test_scatter_matches_the_configured_quantiles():
    """Drawn distances have the configured median and 95th percentile."""
    rng, config = random.Random(1), CarcassConfig()
    draws = sorted(scatter_distance(config, rng) for _ in range(20_000))
    assert statistics.median(draws) == pytest.approx(16.0, rel=0.05)
    assert draws[int(0.95 * len(draws))] == pytest.approx(59.0, rel=0.08)


def test_track_is_real_before_death_and_stationary_after():
    """Fixes up to the death are untouched; later ones cluster at the carcass."""
    fixes = walk(24 * 20)
    death = START + 100 * HOUR
    event = inject_mortality(fixes, death, random.Random(2))
    assert event.fixes[:101] == fixes[:101]
    assert event.death_time == death
    after = event.fixes[101:]
    assert all(haversine_m(event.lat, event.lon, f.lat, f.lon) < 500 for f in after)


def test_collar_keeps_its_schedule_misses_fixes_and_stops():
    """Synthetic fixes reuse real timestamps, drop some, and end after duration."""
    fixes = walk(24 * 20)
    config = CarcassConfig(fix_success=0.5, duration=timedelta(days=3))
    event = inject_mortality(fixes, START + 100 * HOUR, random.Random(3), config)
    after = event.fixes[101:]
    real_times = {f.timestamp for f in fixes}
    assert all(f.timestamp in real_times for f in after)
    assert 0.3 * 72 < len(after) < 0.7 * 72
    assert after[-1].timestamp <= event.death_time + config.duration


def test_same_seed_same_event():
    """Injection is reproducible from its seed."""
    fixes = walk(24 * 20)
    a = inject_mortality(fixes, START + 50 * HOUR, random.Random(9))
    b = inject_mortality(fixes, START + 50 * HOUR, random.Random(9))
    assert a == b


def test_death_time_respects_both_margins():
    """The chosen death leaves room for a baseline and the carcass period."""
    fixes = walk(24 * 20)
    rng = random.Random(4)
    for _ in range(50):
        death = choose_death_time(fixes, rng, timedelta(days=7), timedelta(days=7))
        assert (
            START + timedelta(days=7)
            <= death
            <= fixes[-1].timestamp - timedelta(days=7)
        )


def test_short_track_is_rejected():
    """A track too short for both margins is an error, not a bad event."""
    with pytest.raises(ValueError, match="too short"):
        choose_death_time(walk(48), random.Random(0), timedelta(days=7), HOUR)


def test_death_before_the_track_is_rejected():
    """A death before the first fix has no carcass position."""
    with pytest.raises(ValueError, match="before the track"):
        inject_mortality(walk(10), START - HOUR, random.Random(0))


def test_an_injected_death_is_one_incident():
    """End to end: a synthetic carcass gives one incident, alerted after the window.

    Uses a 200 m box: with observed carcass scatter the provisional 100 m box
    splits 15-42% of deaths into several incidents (see PLAN.md, Phase 2),
    which is a tuning question, not what this test protects.
    """
    fixes = walk(24 * 20)
    event = inject_mortality(fixes, START + 100 * HOUR, random.Random(5))
    stream = FixStream([MortalityDetector(MortalityConfig(max_extent_m=200.0))])
    incidents = [i for f in event.fixes for i in stream.ingest(f)]
    assert len({i.incident_id for i in incidents}) == 1
    delay = incidents[0].opened_at - event.death_time
    assert timedelta(hours=24) <= delay < timedelta(hours=36)
