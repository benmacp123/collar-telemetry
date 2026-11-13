"""Tests for the fix-rate cue, its selection rule and its pinned bird."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telemetry.analysis.experiment import experiment
from telemetry.analysis.fixrate import (
    Case,
    Track,
    Variant,
    balanced_row,
    cue_value,
    fit,
    frozen,
    markdown,
    still_start,
    variants,
)
from telemetry.core.fixes import Fix

START = datetime(2007, 1, 10, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
PLAIN = Variant(7, "count", False)
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def track(times, coords=None):
    """A track with one fix at each time; positions differ unless given."""
    return Track(
        [
            Fix("d", t, *(coords[i] if coords else (i * 0.01, 0.0)))
            for i, t in enumerate(times)
        ]
    )


def steady(days, per_hour=1):
    """Fixes every hour for ``days`` days before START, then none."""
    return [START - HOUR * h for h in range(days * 24, 0, -1) for _ in range(per_hour)]


def test_still_start_reads_the_alert_text():
    """The run's start comes from the text the mortality detector writes."""
    text = "No movement for 39 h; still since 2006-11-21 19:00 UTC. Often rest"
    assert still_start(text) == datetime(2006, 11, 21, 19, tzinfo=timezone.utc)
    assert still_start("no start here") is None


def test_still_start_matches_the_detector_wording():
    """The pattern still matches the message core's detector writes."""
    source = (
        Path(__file__).resolve().parents[2]
        / "src/telemetry/core/detectors/mortality.py"
    ).read_text(encoding="utf-8")
    assert "still since {start:%Y-%m-%d %H:%M} UTC" in source


def test_ratio_is_per_elapsed_hour_not_per_fix_span():
    """Two fixes close together in a 36 h run do not look like a high rate."""
    fixes = steady(7) + [START + HOUR, START + 2 * HOUR]
    value = cue_value(track(fixes), START, START + 36 * HOUR, PLAIN, 48)
    assert value == pytest.approx((2 / 36) / (168 / 168))


def test_ratio_does_not_read_fixes_after_the_alert():
    """A fix after the evidence time leaves the value unchanged."""
    fixes = steady(7) + [START + HOUR]
    late = fixes + [START + 40 * HOUR]
    args = (START, START + 36 * HOUR, PLAIN, 48)
    assert cue_value(track(fixes), *args) == cue_value(track(late), *args)


def test_repeat_positions_can_be_dropped():
    """Fixes that resend the previous coordinates leave both rates."""
    times = steady(7) + [START + HOUR, START + 2 * HOUR]
    same = [(0.0, 0.0)] * len(times)
    drop = Variant(7, "drop", False)
    assert cue_value(
        track(times, same), START, START + 36 * HOUR, drop, 48
    ) == pytest.approx(0.0)
    assert cue_value(track(times, same), START, START + 36 * HOUR, PLAIN, 48) > 0


def test_hour_matching_ignores_hours_the_collar_never_fixes():
    """A collar silent at night is not read as having dropped its rate."""
    day = [START - timedelta(days=d) + HOUR * h for d in range(1, 8) for h in range(12)]
    run = [START + timedelta(hours=h) for h in range(36) if h % 24 < 12]
    fixes = day + run
    matched = Variant(7, "count", True)
    assert cue_value(
        track(fixes), START, START + 36 * HOUR, matched, 48
    ) == pytest.approx(1.0)
    assert cue_value(
        track(fixes), START, START + 36 * HOUR, PLAIN, 48
    ) == pytest.approx((24 / 36) / (84 / 168))


def test_short_or_empty_baseline_is_undefined():
    """With under the minimum baseline, or no fixes in it, there is no value."""
    young = track([START - 10 * HOUR, START + HOUR])
    assert cue_value(young, START, START + 36 * HOUR, PLAIN, 48) is None
    empty = track([START - 200 * HOUR, START - 100 * HOUR + 1 * HOUR])
    assert cue_value(empty, START - 3 * HOUR, START + HOUR, PLAIN, 48) is not None


def test_variants_list_simplest_first():
    """The first variant has every option off, which breaks ties."""
    listed = variants(experiment())
    assert len(listed) == 8
    assert listed[0] == Variant(7, "count", False)


def case(group, kind, value):
    """A case whose every variant has the same ratio."""
    return Case(group, "d", kind, {v: value for v in variants(experiment())})


def test_balanced_row_weights_groups_equally():
    """A small group counts as much as a large one."""
    cases = [case("a", "true", 0.1)] * 2 + [case("b", "true", 0.9)] * 98
    row = balanced_row(cases, ["a", "b"], variants(experiment())[0], 0.5)
    assert row["true"] == pytest.approx(0.5)


def test_fit_picks_the_best_ratio_among_variants_that_keep_enough():
    """The rule keeps half the true alerts, then takes the best ratio."""
    cases = [case("a", "true", 0.1)] * 4 + [case("a", "false", 0.1)] * 1
    cases += [case("a", "false", 0.9)] * 9
    result = fit(cases, ["a"], experiment())
    assert result["meets_keep_share"]
    assert result["chosen"]["point"]["cut"] == 0.1
    assert result["chosen"]["variant"] == variants(experiment())[0]
    assert "Frozen definition" in markdown(result, experiment())


def test_fit_reports_failure_when_no_variant_keeps_enough():
    """With true ratios above every cut, the cue is reported as failing."""
    cases = [case("a", "true", 5.0)] * 4 + [case("a", "false", 0.1)] * 4
    result = fit(cases, ["a"], experiment())
    assert not result["meets_keep_share"]
    assert result["chosen"]["point"]["cut"] == 0.5


def test_frozen_definition_is_one_of_the_tried_variants():
    """The frozen variant was among those the rule chose between."""
    variant, cut = frozen(experiment())
    assert variant in variants(experiment())
    assert cut in experiment().cues["fix_rate"]["cuts"]


def test_mem_blvu_68361_value_is_pinned():
    """The bird the two earlier checks disagreed on scores about 0.12.

    It is measured at its carcass period's start plus the 36 h watch
    window, since the daily-upload replay raised no alert on it then. The
    earlier 1.96 came from dividing by the span of two fixes.
    """
    from telemetry.data.studies import STUDIES

    study = next(s for s in STUDIES if s.slug == "vultures")
    _, fixes, _ = study.load(RAW)
    bird = Track([f for f in fixes if f.deployment_id == "MEM_BLVU_68361"])
    start = datetime(2007, 12, 1, 17, tzinfo=timezone.utc)
    variant, _ = frozen(experiment())
    value = cue_value(bird, start, start + 36 * HOUR, variant, 48)
    assert value == pytest.approx(0.1236, abs=0.0005)
