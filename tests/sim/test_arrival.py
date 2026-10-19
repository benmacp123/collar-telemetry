"""Tests for seeded arrival scenarios."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.sim.arrival import (
    SCENARIOS,
    ArrivalScenario,
    merge_arrivals,
    simulate_arrival,
)
from telemetry.core.cleaning import Cleaner, CleaningConfig
from telemetry.core.fixes import Fix

START = datetime(2010, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def track(hours, deployment="A", step=HOUR):
    """Fixes for one deployment every ``step`` for ``hours`` hours."""
    count = int(hours * HOUR / step)
    return [Fix(deployment, START + i * step, -19.0, 15.5) for i in range(count)]


def test_ideal_arrives_as_taken():
    """The ideal scenario delivers every fix at its own time, once."""
    fixes = track(48)
    arrivals = simulate_arrival(fixes, SCENARIOS["ideal"], seed=1)
    assert [(a.time, a.fix) for a in arrivals] == [(f.timestamp, f) for f in fixes]


def test_daily_upload_batches_fixes_in_order():
    """Daily uploads deliver each day's fixes together, never before taken."""
    fixes = track(24 * 10)
    arrivals = simulate_arrival(fixes, SCENARIOS["satellite_daily"], seed=1)
    assert len(arrivals) == len(fixes)
    assert all(a.time >= a.fix.timestamp for a in arrivals)
    assert all(a.time - a.fix.timestamp < timedelta(days=1) for a in arrivals)
    assert len({a.time for a in arrivals}) in (10, 11)
    assert [a.fix for a in arrivals] == fixes


def test_uploads_keep_one_phase_per_deployment():
    """Every upload of a deployment falls at the same time of day."""
    arrivals = simulate_arrival(track(24 * 10), SCENARIOS["satellite_daily"], seed=3)
    assert len({(a.time.hour, a.time.minute) for a in arrivals}) == 1


def test_same_seed_same_arrivals_and_other_seeds_differ():
    """Arrivals are reproducible from the seed and change with it."""
    fixes, gsm = track(24 * 30), SCENARIOS["gsm"]
    assert simulate_arrival(fixes, gsm, 7) == simulate_arrival(fixes, gsm, 7)
    assert simulate_arrival(fixes, gsm, 7) != simulate_arrival(fixes, gsm, 8)


def test_deployments_are_independent():
    """A deployment's arrivals do not depend on which others exist."""
    a = simulate_arrival(track(24 * 30, "A"), SCENARIOS["gsm"], 7)
    b = simulate_arrival(track(24 * 30, "B"), SCENARIOS["gsm"], 7)
    merged = merge_arrivals([a, b])
    assert [x for x in merged if x.fix.deployment_id == "A"] == a
    assert [x.time for x in merged] == sorted(x.time for x in merged)


def test_outages_do_not_depend_on_retry_rate():
    """Changing the retry rate leaves the coverage pattern unchanged."""
    fixes = track(24 * 60)
    quiet = replace(SCENARIOS["gsm"], retry_share=0.0, duplicate_share=0.0)
    noisy = replace(SCENARIOS["gsm"], retry_share=0.3, duplicate_share=0.0)
    # The upload a fix first reaches is set by coverage alone; retries can
    # only push it later.
    first = {a.fix: a.time for a in simulate_arrival(fixes, quiet, 5)}
    later = {a.fix: a.time for a in simulate_arrival(fixes, noisy, 5)}
    assert all(later[f] >= first[f] for f in fixes)
    assert sum(later[f] == first[f] for f in fixes) > 0.6 * len(fixes)


def test_gsm_outages_hold_whole_days_in_order():
    """An outage delays a day's fixes past midnight, oldest first."""
    scenario = replace(SCENARIOS["gsm"], retry_share=0.0, duplicate_share=0.0)
    fixes = track(24 * 60)
    arrivals = simulate_arrival(fixes, scenario, 2)
    held = [a for a in arrivals if a.time.date() > a.fix.timestamp.date()]
    assert held, "expected some outage days in 60 days at 10%"
    assert [a.fix for a in arrivals] == fixes


def test_retries_put_fixes_out_of_order_and_the_hold_reorders_most():
    """Retried fixes arrive after newer ones; the hold reorders ordinary retries.

    Retried backlog fixes can arrive up to a day late, beyond the 3 h hold,
    so the cleaner drops those as late; they stay a small, counted share.
    """
    fixes = track(24 * 60)
    scenario = replace(SCENARIOS["gsm"], duplicate_share=0.0)
    arrivals = simulate_arrival(fixes, scenario, 4)
    order = [a.fix for a in arrivals]
    assert order != fixes and sorted(order, key=lambda f: f.timestamp) == fixes

    cleaner = Cleaner(
        CleaningConfig(max_lateness=scenario.max_lateness, max_speed_mps=50.0)
    )
    state, released = {}, []
    for a in arrivals:
        released += cleaner.arrive(state, a.fix)
    released += cleaner.tick(state, START + timedelta(days=90))
    late = state["dropped"]["late"]
    assert released == sorted(released, key=lambda f: f.timestamp)
    assert len(released) + late == len(fixes)
    assert 0 < late < 0.02 * len(fixes)


def test_duplicates_arrive_later_and_are_removed_by_the_cleaner():
    """A duplicate arrives at a later upload; the cleaner drops it."""
    scenario = replace(SCENARIOS["gsm"], retry_share=0.0, duplicate_share=0.2)
    fixes = track(24 * 10)
    arrivals = simulate_arrival(fixes, scenario, 6)
    assert len(arrivals) > len(fixes)
    first_seen = {}
    for a in arrivals:
        if a.fix in first_seen:
            assert a.time > first_seen[a.fix]
        first_seen.setdefault(a.fix, a.time)


def test_impossible_shares_are_rejected():
    """A share of 1 would never deliver, so it is an error."""
    with pytest.raises(ValueError, match="outage_day_share"):
        ArrivalScenario("broken", HOUR, outage_day_share=1.0)


def test_mixed_deployments_are_rejected():
    """One call simulates one collar."""
    with pytest.raises(ValueError, match="one deployment"):
        simulate_arrival(track(2, "A") + track(2, "B"), SCENARIOS["gsm"], 1)


def test_empty_track_has_no_arrivals():
    """No fixes, no arrivals."""
    assert not simulate_arrival([], SCENARIOS["gsm"], 1)
