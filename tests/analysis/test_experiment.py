"""Tests for the experiment definition and what the reports do with it."""

import csv
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from telemetry.analysis.evaluation import ANIMAL_MONTH
from telemetry.analysis.experiment import EXPERIMENT_PATH, _target, experiment
from telemetry.analysis.intervals import wilson
from telemetry.analysis.report import _sweep_target_lines, _target_lines
from telemetry.core.pipeline import UPLOAD_MARGIN
from telemetry.core.species import profile_for

ROOT = Path(__file__).resolve().parents[2]
WATCH = "Stationary: check (watch)"
ESCALATED = "Escalated: possible death"
READ_BY_EVERY_ANALYSIS = """
import sys
from datetime import datetime, timezone
from pathlib import Path
from telemetry.analysis import experiment as module
module.EXPERIMENT_PATH = Path(sys.argv[1])
from telemetry.analysis.evaluation import CARCASS_MIN, split_for
from telemetry.analysis.intervals import BOOTSTRAP_RESAMPLES
from telemetry.analysis.report import _sweep_target_lines
from telemetry.analysis.sweep import grid
from telemetry.core.fixes import Deployment
bird = Deployment("A", "t", "A", "Cathartes aura",
                  datetime(2005, 1, 1, tzinfo=timezone.utc), None, None)
print(len(grid()), split_for("vultures", bird),
      CARCASS_MIN["Cathartes aura"].total_seconds() / 3600, BOOTSTRAP_RESAMPLES,
      module.experiment().targets[0].value)
"""


def by_tier_and_metric():
    """The targets keyed by tier and metric."""
    return {(t.tier, t.metric): t for t in experiment().targets}


def scenario_result(load, rate, lower, clear=8.0):
    """One scenario's results, holding only what the target table reads."""
    return {
        "load": {
            "mortality": {"per_animal_month": load},
            "potential_death": {"per_animal_month": load / 10},
        },
        "mortality_clear": {"median_hours": clear},
        "mortality": {"rate_at_mark": rate},
        "potential_death": {"rate_at_mark": rate},
        "precision": {
            "mortality": {"wilson": [lower, 0.9], "ceiling": 0.014},
            "potential_death": {"wilson": [lower, 0.9], "ceiling": 0.1},
            "gap": {"wilson": [lower, 0.9], "ceiling": 0.1},
        },
    }


def test_every_analysis_reads_the_same_file(tmp_path):
    """Changing the one file changes the sweep, the split, the truth rules,
    the intervals and the targets together."""
    text = EXPERIMENT_PATH.read_text(encoding="utf-8")
    for old, new in (
        ("scoring_from = 2013-01-01T00:00:00Z", "scoring_from = 2001-01-01T00:00:00Z"),
        (
            "mortality_boxes_m = [100.0, 150.0, 200.0, 300.0]",
            "mortality_boxes_m = [100.0]",
        ),
        (
            "windows_hours = [36.0, 39.0, 42.0, 45.0, 48.0, 60.0, 72.0, 96.0, 120.0]",
            "windows_hours = [36.0, 48.0]",
        ),
        ('"Cathartes aura" = 24.0', '"Cathartes aura" = 30.0'),
        ("bootstrap_resamples = 5000", "bootstrap_resamples = 7"),
        ("at_most = 3.0", "at_most = 4.0"),
    ):
        assert old in text
        text = text.replace(old, new)
    changed = tmp_path / "experiment.toml"
    changed.write_text(text, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    output = subprocess.run(
        [sys.executable, "-c", READ_BY_EVERY_ANALYSIS, str(changed)],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.split()
    assert output == ["13", "scoring", "30.0", "7", "4.0"]


def test_committed_values_are_the_settled_targets():
    """The targets are the ones decided in advance, on the sets decided."""
    targets = by_tier_and_metric()
    expected = {
        (WATCH, "load"): (3.0, "at_most", ("tuning", "fresh")),
        (WATCH, "clear_hours"): (12.0, "at_most", ("tuning", "fresh")),
        (WATCH, "rate_at_mark"): (0.8, "at_least", ("tuning", "fresh")),
        (ESCALATED, "wilson_lower"): (0.15, "above", ("fresh",)),
        (ESCALATED, "rate_at_mark"): (0.5, "at_least", ("fresh",)),
        (ESCALATED, "load"): (1.0, "at_most", ("fresh",)),
        ("Fix-rate cue", "cue_precision"): (0.1, "at_least", ("fresh",)),
    }
    got = {k: (t.value, t.bound, t.judged_on) for k, t in targets.items()}
    assert got == expected


def test_load_limits_convert_to_animal_months():
    """3 and 1 per 30 birds per week are 0.435 and 0.145 per animal-month."""
    targets = by_tier_and_metric()
    assert targets[WATCH, "load"].limit == pytest.approx(0.4348, abs=5e-4)
    assert targets[ESCALATED, "load"].limit == pytest.approx(0.145, abs=5e-4)
    assert ANIMAL_MONTH == timedelta(days=30.4375)


def test_bounds_treat_the_limit_itself_correctly():
    """ "At most" and "at least" include the limit; "above" does not, so a
    bound of exactly 15% does not pass."""
    targets = by_tier_and_metric()
    assert targets[WATCH, "clear_hours"].met(12.0)
    assert not targets[WATCH, "clear_hours"].met(12.1)
    assert targets[WATCH, "rate_at_mark"].met(0.8)
    assert not targets[WATCH, "rate_at_mark"].met(0.667)
    assert not targets[ESCALATED, "wilson_lower"].met(0.15)
    assert targets[ESCALATED, "wilson_lower"].met(0.151)


def test_verdict_judges_only_the_sets_a_target_names():
    """A value that clears the limit on a seen or tuning set is not a pass
    for a target judged on fresh sets only."""
    target = by_tier_and_metric()[ESCALATED, "wilson_lower"]
    assert target.verdict(0.4, "seen") == "not judged on seen set"
    assert target.verdict(0.4, "tuning") == "not judged on tuning set"
    assert target.verdict(0.4, "fresh") == "met"
    assert target.verdict(0.1, "fresh") == "missed"
    assert target.verdict(None, "fresh") == "not measured"


@pytest.mark.parametrize(
    "entry",
    [
        {"metric": "made_up", "at_most": 1.0},
        {"metric": "load"},
        {"metric": "load", "at_most": 1.0, "at_least": 0.5},
    ],
)
def test_malformed_target_is_refused(entry):
    """A typo in a target stops the run rather than changing what passes."""
    entry = {"tier": "T", "alert": "mortality", "judged_on": ["fresh"], **entry}
    with pytest.raises(ValueError):
        _target(entry, ANIMAL_MONTH)


def test_quoted_thresholds_match_what_the_detectors_run():
    """The file's quoted settings cannot drift from the core's own."""
    quoted = experiment().thresholds
    for taxon, hours in quoted["mortality_window_hours"].items():
        mortality = profile_for(taxon).mortality
        assert mortality.window == timedelta(hours=hours)
        assert mortality.max_extent_m == quoted["mortality_box_m"]
        assert mortality.min_fixes == quoted["mortality_min_fixes"]
        assert mortality.leave_fixes == quoted["mortality_leave_fixes"]
        assert mortality.leave_radius_m == quoted["mortality_leave_radius_m"]
    assert UPLOAD_MARGIN == timedelta(hours=quoted["upload_margin_hours"])


def test_quoted_mark_matches_the_committed_evaluation():
    """The mark the targets name is the one the evaluation measured."""
    path = ROOT / "results" / "evaluation" / "vultures-tuning.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["mark_hours"] == experiment().reference_mark_hours


def test_arithmetic_matches_the_stated_precisions():
    """25% allows 0.03 false alerts per animal-month, about 12 times fewer
    than today; 33% is the least that 5 true alerts can clear 15% with."""
    settings = experiment()
    allowed = settings.false_rate_allowed(0.25)
    assert allowed == pytest.approx(0.0306, abs=1e-4)
    assert settings.false_per_animal_month / allowed == pytest.approx(12.3, abs=0.1)
    assert settings.false_rate_allowed(0.33) == pytest.approx(0.0207, abs=1e-4)
    assert wilson(5, 15)[0] > 0.15 > wilson(5, 16)[0]


def test_stork_split_file_has_the_named_sets():
    """Every stork population in the split file falls in a set the experiment
    defines, or is excluded."""
    storks = experiment().studies["storks"]
    with (ROOT / storks["split_file"]).open(encoding="utf-8") as file:
        names = {row["split"] for row in csv.DictReader(file)}
    assert names - {"excluded"} == set(storks["sets"])


def test_no_target_on_the_spent_set_can_be_judged():
    """The held-out vultures are seen, so every target skips them, and the
    fresh studies are the only sets that judge the escalated tier."""
    settings = experiment()
    assert settings.set_kind("vultures", "scoring") == "seen"
    assert settings.set_kind("storks", "scoring") == "fresh"
    assert settings.set_kind("acopian-vultures", "all") == "fresh"
    assert settings.set_kind("jackals", "all") is None
    assert all("seen" not in t.judged_on for t in settings.targets)


def test_each_study_names_its_real_upload_scenario():
    """Targets are judged under the upload pattern fixed in advance."""
    settings = experiment()
    assert settings.scenario("vultures") == "satellite_daily"
    assert settings.scenario("storks") == "gsm"
    assert settings.scenario("acopian-vultures") is None


def section_for(study, name):
    """The target-table rows for a report whose scenarios disagree, so a
    table using the wrong scenario shows the wrong numbers."""
    other = scenario_result(load=0.2, rate=1.0, lower=0.9, clear=1.0)
    scenarios = {
        "ideal": other,
        "gsm": other,
        "satellite_2day": other,
        "satellite_daily": scenario_result(load=0.586, rate=0.667, lower=0.0626),
    }
    return {"study": study, "set": name, "scenarios": scenarios}


def table_row(lines, tier, metric):
    """The one target-table row for a tier and metric."""
    rows = [line for line in lines if line.startswith(f"| {tier} | {metric}")]
    assert len(rows) == 1
    return rows[0]


def test_target_table_judges_the_named_scenario_on_tuning():
    """Tuning figures are read from the daily scenario, with met or missed
    on watch targets and no verdict on escalated ones."""
    lines = _target_lines(section_for("vultures", "tuning"))
    load = table_row(lines, WATCH, "Load")
    assert "at most 3 per 30 birds per week (0.435 per animal-month)" in load
    assert "| 0.586 | 1.4% | missed |" in load
    assert table_row(lines, WATCH, "Median").endswith("| 8.0 h | 1.4% | met |")
    assert table_row(lines, WATCH, "Carcasses").endswith("| 66.7% | 1.4% | missed |")
    wilson_row = table_row(lines, ESCALATED, "Precision, Wilson")
    assert wilson_row.endswith("| 6.3% | 10.0% | not judged on tuning set |")
    assert "12 times fewer than today" in "\n".join(lines)


def test_target_table_never_judges_the_seen_set():
    """A held-out figure past its limit prints as seen, not as a pass."""
    report = section_for("vultures", "scoring")
    report["scenarios"]["satellite_daily"]["precision"]["potential_death"]["wilson"] = [
        0.198,
        0.64,
    ]
    lines = _target_lines(report)
    assert "not judged on seen set" in table_row(lines, ESCALATED, "Precision, Wilson")
    assert not [line for line in lines if line.endswith("| met |")]


def test_target_table_leaves_unmeasured_values_blank():
    """A held-out report from before time to clear existed shows a dash."""
    report = section_for("vultures", "scoring")
    del report["scenarios"]["satellite_daily"]["mortality_clear"]
    row = table_row(_target_lines(report), WATCH, "Median")
    assert "| – | 1.4% | not judged on seen set |" in row


def test_mammals_have_no_target_table():
    """Studies outside the experiment's sets print no targets."""
    assert not _target_lines(section_for("jackals", "all"))


def test_sweep_rows_show_each_watch_target_and_verdict():
    """Every setting prints its measures with targets, from the named scenario."""
    row = {
        "mortality_per_animal_month": 0.586,
        "mortality_clear_median_hours": 8.0,
        "carcass_rate_at_mark": 0.667,
        "mortality_ceiling": 0.014,
    }
    good = {**row, "mortality_per_animal_month": 0.3, "carcass_rate_at_mark": 0.8}
    wrong = {**row, "mortality_per_animal_month": 0.1, "carcass_rate_at_mark": 1.0}
    by_setting = {
        (36.0, 100.0): {"satellite_daily": row, "ideal": wrong},
        (48.0, 100.0): {"satellite_daily": good, "ideal": wrong},
    }
    lines = _sweep_target_lines({"study": "vultures", "set": "tuning"}, by_setting)
    assert (
        "| 36 | 100 | 0.586 (at most 0.435) | 8.0 h (at most 12 h) | "
        "66.7% (at least 80%) | 1.4% | missed: load, carcasses flagged by the mark |"
    ) in lines
    assert lines[-1].endswith("| met |")
