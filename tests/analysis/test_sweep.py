"""Tests for replay overrides and the threshold sweep on hand-built tracks."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemetry.sim.arrival import SCENARIOS
from telemetry.analysis.evaluation import build_truth
from telemetry.analysis.experiment import experiment
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset
from telemetry.core.pipeline import MERGE_SLACK, Overrides
from telemetry.sim.replay import replay
from telemetry.core.species import profile_for
from telemetry.analysis.sweep import grid, species_choice, sweep_point

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"
ELEPHANT = "Loxodonta africana"
SWEEP_JSON = Path(__file__).resolve().parents[2] / "results/sweep/vultures-tuning.json"


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
    assert merge["mortality"] == merge["potential_death"] == 96 * HOUR
    assert overrides.to_dict()["mortality_merge_hours"] == 96.0


def test_box_only_drops_the_leaving_radius():
    """The box-only override restores the detector as it was before the radius."""
    assert profile_for(JACKAL).mortality.leave_radius_m == 75.0
    mortality = (
        Overrides(mortality_box_only=True).profile(profile_for(JACKAL)).mortality
    )
    assert mortality.leave_radius_m is None


def test_grid_sweeps_each_detector_on_its_own():
    """Twenty-four mortality settings (36-120 h by 100-300 m plus the old
    24 h and 150 m points) and five gap margins."""
    points = grid()
    assert sum(1 for swept, _ in points if swept == "mortality") == 24
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


def test_species_window_changes_only_that_species():
    """A species window override leaves every other species' window alone."""
    overrides = Overrides(species_windows=((JACKAL, 60 * HOUR),))
    assert overrides.profile(profile_for(JACKAL)).mortality.window == 60 * HOUR
    turkey = profile_for("Cathartes aura")
    assert overrides.profile(turkey).mortality.window == turkey.mortality.window


def test_species_window_wins_over_uniform_window():
    """The species window is applied after the uniform one."""
    overrides = Overrides(
        mortality_window=48 * HOUR, species_windows=((JACKAL, 60 * HOUR),)
    )
    assert overrides.profile(profile_for(JACKAL)).mortality.window == 60 * HOUR
    turkey = overrides.profile(profile_for("Cathartes aura"))
    assert turkey.mortality.window == 48 * HOUR


def test_merge_follows_a_long_species_window():
    """A species window past 36 h lengthens only that stream's merge window."""
    overrides = Overrides(species_windows=((JACKAL, 60 * HOUR),))
    long = overrides.lifecycle(overrides.profile(profile_for(JACKAL)))
    assert long.config.merge_within["mortality"] == 60 * HOUR + MERGE_SLACK
    assert long.config.merge_within["potential_death"] == 60 * HOUR + MERGE_SLACK
    other = overrides.lifecycle(overrides.profile(profile_for("Cathartes aura")))
    assert other.config.merge_within["mortality"] == 48 * HOUR


def test_species_override_reaches_the_replayed_stream():
    """A 48 h jackal window misses a 40 h carcass that 24 h flags."""
    deployments, fixes = dead_jackal(40)
    plain = replay(deployments, fixes, SCENARIOS["ideal"], seed=3)
    longer = replay(
        deployments,
        fixes,
        SCENARIOS["ideal"],
        seed=3,
        overrides=Overrides(species_windows=((JACKAL, 48 * HOUR),)),
    )
    assert any(i.detector == "mortality" for i in plain.incidents)
    assert not any(i.detector == "mortality" for i in longer.incidents)
    assert longer.summary["overrides"]["species_windows_hours"] == {JACKAL: 48.0}


def test_grid_sweeps_the_black_vulture_window_alone():
    """Species points vary only the black-vulture window, 36 h first."""
    species = [o for swept, o in grid() if swept == "species"]
    assert len(species) == 9
    assert {o.species_windows[0][0] for o in species} == {"Coragyps atratus"}
    assert species[0].species_windows[0][1] == 36 * HOUR
    assert all(o.mortality_window is None for o in species)


def test_mortality_rows_are_broken_down_by_species():
    """Each species' part of a row is scored on its deployments only."""
    deployments, fixes = dead_jackal(30)
    elephant = Deployment("E", "tag", "E", ELEPHANT, START, None, None)
    lat, lon = -24.0, 31.5
    for i in range(150):
        lat, lon = offset(lat, lon, 0.0, 400.0)
        fixes.append(Fix("E", START + i * HOUR, lat, lon))
    deployments.append(elephant)
    truths = build_truth("jackals", deployments, fixes, {})
    row = sweep_point(
        deployments,
        fixes,
        truths,
        SCENARIOS["ideal"],
        "species",
        Overrides(species_windows=((JACKAL, 24 * HOUR),)),
        90.0,
    )
    jackal, walker = row["by_taxon"][JACKAL], row["by_taxon"][ELEPHANT]
    assert (jackal["deployments"], jackal["carcass_deaths"]) == (1, 1)
    assert jackal["carcass_detected"] == 1
    assert (walker["deployments"], walker["carcass_deaths"]) == (1, 0)
    assert walker["mortality_per_animal_month"] == 0.0
    assert jackal["mortality_per_animal_month"] > row["mortality_per_animal_month"]


def species_row(window, load, clear, scenario="satellite_daily"):
    """A species sweep row holding only what the decision rule reads."""
    return {
        "swept": "species",
        "scenario": scenario,
        "species_windows_hours": {"Coragyps atratus": window},
        "mortality_per_animal_month": load,
        "mortality_clear_median_hours": clear,
    }


def test_rule_takes_the_shortest_window_meeting_load_and_clear():
    """The shortest passing window wins; carcass detection is not read."""
    rows = [
        species_row(48.0, 0.30, 11.0),
        species_row(36.0, 0.59, 8.0),
        species_row(42.0, 0.40, 10.0),
        # Passes at a shorter window, but under the wrong scenario.
        species_row(39.0, 0.10, 1.0, scenario="ideal"),
    ]
    assert species_choice(rows, "satellite_daily") == 42.0


def test_rule_finds_no_window_when_none_meets_both():
    """Load met at one window and clear time at another is not a choice."""
    rows = [species_row(36.0, 0.59, 8.0), species_row(48.0, 0.30, 23.5)]
    assert species_choice(rows, "satellite_daily") is None


def test_rule_needs_a_measured_clear_time():
    """A window with no resolved false alerts cannot meet the clear target."""
    assert species_choice([species_row(36.0, 0.1, None)], "satellite_daily") is None


def test_core_runs_the_window_the_committed_sweep_chose():
    """The black-vulture window in core is the rule's choice on the committed
    sweep, or 36 h when no window meets the targets."""
    report = json.loads(SWEEP_JSON.read_text(encoding="utf-8"))
    scenario = experiment().scenario(report["study"])
    choice = species_choice(report["rows"], scenario)
    window = profile_for(experiment().species_taxon).mortality.window
    assert window == HOUR * (36.0 if choice is None else choice)
