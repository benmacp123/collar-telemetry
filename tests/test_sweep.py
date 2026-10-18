"""Tests for replay overrides and the threshold sweep on hand-built tracks."""

from datetime import datetime, timedelta, timezone

from telemetry.arrival import SCENARIOS
from telemetry.evaluation import build_truth
from telemetry.fixes import Deployment, Fix
from telemetry.geo import offset
from telemetry.replay import MERGE_SLACK, Overrides, gap_config, replay
from telemetry.species import profile_for
from telemetry.sweep import grid, sweep_point

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


def test_gap_margin_adds_to_upload_interval():
    """The gap margin sits on top of the upload interval."""
    assert gap_config(SCENARIOS["ideal"], 12 * HOUR).min_silence == 12 * HOUR
    assert gap_config(SCENARIOS["satellite_daily"], 12 * HOUR).min_silence == (
        36 * HOUR
    )


def test_grid_sweeps_each_detector_on_its_own():
    """Twelve mortality settings and four gap margins."""
    points = grid()
    assert sum(1 for swept, _ in points if swept == "mortality") == 12
    gap = [o for swept, o in points if swept == "gap"]
    assert len(gap) == 4
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
