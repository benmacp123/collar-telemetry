"""Tests for replay overrides and the threshold sweep on hand-built tracks."""

from datetime import datetime, timedelta, timezone

from telemetry.sim.arrival import SCENARIOS
from telemetry.analysis.evaluation import build_truth
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset
from telemetry.core.pipeline import MERGE_SLACK, Overrides
from telemetry.sim.replay import replay
from telemetry.core.species import profile_for
from telemetry.analysis.sweep import grid, sweep_point

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"


def dead_jackal(still_hours):
    """A jackal that walks for 5 days, then lies dead for ``still_hours``."""
    deployment = Deployment("A", "tag", "A", JACKAL, START, None, "dead")
    lat, lon = -19.0, 15.5
    fixes = []
    for i in range(120):
        lat, lon = offset(lat, lon, 0.0, 300.0)
        fixes.append(Fix("A", START + i * HOUR, lat, lon))
    for i in range(still_hours):
        point = offset(lat, lon, 90.0 if i % 2 else 270.0, 10.0)
        fixes.append(Fix("A", START + (120 + i) * HOUR, *point))
    return [deployment], fixes


def test_default_overrides_reproduce_plain_replay():
    """A replay with default overrides matches one without any."""
    deployments, fixes = dead_jackal(40)
    plain = replay(deployments, fixes, SCENARIOS["gsm"], seed=3)
    same = replay(deployments, fixes, SCENARIOS["gsm"], seed=3, overrides=Overrides())
    assert plain == same
    assert "overrides" not in plain.summary


def test_overrides_replace_window_box_and_merge():
    """Window and box replace the species' values; merge follows window."""
    overrides = Overrides(mortality_window=48 * HOUR, mortality_box_m=150.0)
    mortality = overrides.profile(profile_for(JACKAL)).mortality
    assert (mortality.window, mortality.max_extent_m) == (48 * HOUR, 150.0)
    merge = overrides.lifecycle().config.merge_within["mortality"]
    assert merge == 48 * HOUR + MERGE_SLACK


def test_overrides_replace_leave_settings_and_merge():
    """Leave fixes, leave radius and merge window are set independently."""
    overrides = Overrides(
        mortality_leave_fixes=3,
        mortality_leave_radius_m=75.0,
        mortality_merge=96 * HOUR,
    )
    mortality = overrides.profile(profile_for(JACKAL)).mortality
    assert (mortality.leave_fixes, mortality.leave_radius_m) == (3, 75.0)
    merge = overrides.lifecycle().config.merge_within
    assert merge["mortality"] == merge["likely_death"] == 96 * HOUR
    assert overrides.to_dict()["mortality_merge_hours"] == 96.0


def test_box_only_drops_the_leaving_radius():
    """The box-only override restores the detector as it was before the radius."""
    assert profile_for(JACKAL).mortality.leave_radius_m == 75.0
    mortality = (
        Overrides(mortality_box_only=True).profile(profile_for(JACKAL)).mortality
    )
    assert mortality.leave_radius_m is None


def test_grid_sweeps_each_detector_on_its_own():
    """Twelve mortality settings and five gap margins."""
    points = grid()
    assert sum(1 for swept, _ in points if swept == "mortality") == 12
    gap = [o for swept, o in points if swept == "gap"]
    assert len(gap) == 5
    assert all(o.mortality_window is None for o in gap)


def test_longer_window_misses_a_short_carcass_period():
    """A 30 h carcass is flagged with a 24 h window but not a 48 h one."""
    deployments, fixes = dead_jackal(30)
    truths = build_truth("jackals", deployments, fixes, {})
    rows = [
        sweep_point(
            deployments,
            fixes,
            truths,
            SCENARIOS["ideal"],
            "mortality",
            Overrides(mortality_window=w * HOUR),
            90.0,
        )
        for w in (24, 48)
    ]
    assert [r["carcass_detected"] for r in rows] == [1, 0]
    assert rows[0]["mortality_window_hours"] == 24.0
