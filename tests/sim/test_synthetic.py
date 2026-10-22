"""Tests for synthetic mortality injection."""

import json
import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telemetry.core.detectors.mortality import MortalityConfig, MortalityDetector
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m, offset
from telemetry.core.stream import FixStream
from telemetry.core.fixes import Deployment
from telemetry.sim.synthetic import (
    REPORTING,
    SPARSE,
    CarcassConfig,
    choose_death_time,
    inject_mortality,
    scatter_distance,
    synthetic_id,
    synthetic_study,
)

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
CARCASS = Path(__file__).resolve().parents[2] / "results" / "carcass" / "carcass.json"


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
    assert statistics.median(draws) == pytest.approx(15.9, rel=0.05)
    assert draws[int(0.95 * len(draws))] == pytest.approx(36.5, rel=0.08)


def test_defaults_match_the_committed_carcass_profile():
    """The carcass defaults are the values ``make carcass`` measured."""
    measured = json.loads(CARCASS.read_text(encoding="utf-8"))["vulture_carcasses"]
    config = CarcassConfig()
    assert config.reporting_success == measured["reporting_ratio"]
    assert config.sparse_success == measured["sparse_ratio"]
    assert config.sparse_share == measured["sparse_share"]
    assert config.scatter_median_m == measured["scatter_median_m"]
    assert config.scatter_p95_m == measured["scatter_p95_m"]
    sparse_hours = sorted(tail["hours"] for tail in measured["tails"] if tail["sparse"])
    assert [life / HOUR for life in config.sparse_lives] == sparse_hours


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
    config = CarcassConfig(reporting_success=0.5, duration=timedelta(days=3))
    event = inject_mortality(
        fixes, START + 100 * HOUR, random.Random(3), config, sparse=False
    )
    after = event.fixes[101:]
    real_times = {f.timestamp for f in fixes}
    assert all(f.timestamp in real_times for f in after)
    assert 0.3 * 72 < len(after) < 0.7 * 72
    assert after[-1].timestamp <= event.death_time + config.duration


def test_sparse_carcasses_send_far_fewer_fixes():
    """A sparse carcass keeps its regime's share of the schedule, not the other's."""
    fixes = walk(24 * 40)
    death = START + 100 * HOUR
    config = CarcassConfig(sparse_lives=())
    reporting = inject_mortality(fixes, death, random.Random(6), config, sparse=False)
    sparse = inject_mortality(fixes, death, random.Random(6), config, sparse=True)
    slots = 24 * 30
    assert not reporting.sparse and sparse.sparse
    assert len(reporting.fixes) - 101 == pytest.approx(
        config.reporting_success * slots, rel=0.15
    )
    assert len(sparse.fixes) - 101 == pytest.approx(
        config.sparse_success * slots, rel=0.3
    )


def test_sparse_collar_stops_after_an_observed_life():
    """A sparse carcass's collar stops after one of the observed sparse lives;
    a reporting one keeps the full duration."""
    fixes = walk(24 * 40)
    death = START + 100 * HOUR
    config = CarcassConfig()
    lives = set()
    for seed in range(30):
        sparse = inject_mortality(fixes, death, random.Random(seed), sparse=True)
        assert sparse.life in config.sparse_lives
        assert sparse.fixes[-1].timestamp <= death + sparse.life
        lives.add(sparse.life)
    assert lives == set(config.sparse_lives)
    reporting = inject_mortality(fixes, death, random.Random(0), sparse=False)
    assert reporting.life == config.duration


def test_regime_is_drawn_at_the_configured_share():
    """Unforced, about ``sparse_share`` of carcasses come out sparse."""
    fixes = walk(24 * 10)
    rng = random.Random(7)
    drawn = [
        inject_mortality(fixes, START + 50 * HOUR, rng).sparse for _ in range(2000)
    ]
    assert sum(drawn) / len(drawn) == pytest.approx(
        CarcassConfig().sparse_share, abs=0.04
    )


def test_collar_stops_with_the_real_track():
    """A carcass period longer than the rest of the track ends with the track."""
    fixes = walk(24 * 10)
    event = inject_mortality(fixes, START + 100 * HOUR, random.Random(8), sparse=False)
    assert event.fixes[-1].timestamp <= fixes[-1].timestamp


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


def test_death_is_never_placed_before_a_long_outage():
    """No death falls where the real collar was silent through the carcass period."""
    fixes = walk(24 * 30)
    # Collar off for days 12-15: a death on days 5-12 would lose fixes.
    gappy = [
        f
        for f in fixes
        if not START + timedelta(days=12) < f.timestamp < START + timedelta(days=15)
    ]
    rng = random.Random(10)
    deaths = {
        choose_death_time(gappy, rng, timedelta(days=1), timedelta(days=7))
        for _ in range(300)
    }
    off, on = START + timedelta(days=12), START + timedelta(days=15)
    # Allowed: after the outage, or early enough that the carcass period
    # runs at most 24 h into it.
    assert all(d >= on or d + timedelta(days=7) <= off + 24 * HOUR for d in deaths)
    assert any(d >= on for d in deaths) and any(d < off for d in deaths)


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
    event = inject_mortality(fixes, START + 100 * HOUR, random.Random(5), sparse=False)
    stream = FixStream([MortalityDetector(MortalityConfig(max_extent_m=200.0))])
    incidents = [i for f in event.fixes for i in stream.ingest(f)]
    assert len({i.incident_id for i in incidents}) == 1
    delay = incidents[0].opened_at - event.death_time
    assert timedelta(hours=24) <= delay < timedelta(hours=36)


def deployment(deployment_id):
    """A jackal deployment from START with no recorded end."""
    return Deployment(
        deployment_id, "tag", "animal", "Canis mesomelas", START, None, None
    )


def walk_as(deployment_id, hours):
    """``walk`` for another deployment ID."""
    return [Fix(deployment_id, f.timestamp, f.lat, f.lon) for f in walk(hours)]


def test_synthetic_study_kills_each_deployment_once_per_regime():
    """Each usable deployment gives a reporting and a sparse copy dying together."""
    fixes = walk_as("J1", 24 * 30) + walk_as("J2", 24 * 30)
    variant = synthetic_study([deployment("J2"), deployment("J1")], fixes, 2026)
    ids = [d.deployment_id for d in variant.deployments]
    assert ids == [
        synthetic_id("J1", REPORTING),
        synthetic_id("J1", SPARSE),
        synthetic_id("J2", REPORTING),
        synthetic_id("J2", SPARSE),
    ]
    assert [d.regime for d in variant.deaths] == [REPORTING, SPARSE] * 2
    for first, second in zip(variant.deaths[::2], variant.deaths[1::2]):
        assert first.death_time == second.death_time
        assert first.source_id == second.source_id
    # Sparse carcasses keep fewer of the same scheduled fixes.
    assert variant.deaths[1].carcass_fixes < variant.deaths[0].carcass_fixes
    assert not variant.skipped


def test_synthetic_deployments_end_dead_at_their_last_fix():
    """The evaluation labels synthetic deployments dead with no override."""
    variant = synthetic_study([deployment("J1")], walk_as("J1", 24 * 30), 2026)
    for synthetic in variant.deployments:
        own = [f for f in variant.fixes if f.deployment_id == synthetic.deployment_id]
        assert synthetic.end_type == "dead"
        assert synthetic.deploy_off == own[-1].timestamp
        assert synthetic.taxon == "Canis mesomelas"
    assert {f.deployment_id for f in variant.fixes} == {
        d.deployment_id for d in variant.deployments
    }


def test_synthetic_study_skips_short_tracks_with_a_reason():
    """A track too short for a death is listed, not silently dropped."""
    fixes = walk_as("J1", 24 * 30) + walk_as("J2", 48)
    variant = synthetic_study([deployment("J1"), deployment("J2")], fixes, 2026)
    assert set(variant.skipped) == {"J2"}
    assert "too short" in variant.skipped["J2"]
    assert {d.source_id for d in variant.deaths} == {"J1"}


def test_synthetic_study_death_ignores_other_deployments():
    """A deployment's death does not change when another is added."""
    alone = synthetic_study([deployment("J1")], walk_as("J1", 24 * 30), 2026)
    both = synthetic_study(
        [deployment("J1"), deployment("J2")],
        walk_as("J1", 24 * 30) + walk_as("J2", 24 * 30),
        2026,
    )
    assert alone.deaths == both.deaths[:2]
    assert alone.fixes == [f for f in both.fixes if f.deployment_id.startswith("J1")]
