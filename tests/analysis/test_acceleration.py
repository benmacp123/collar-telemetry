"""Tests for the stork acceleration cue and its likelihood ratio."""

from datetime import datetime, timedelta, timezone

from telemetry.analysis.acceleration import (
    Case,
    build_cases,
    cue_value,
    fit,
    markdown,
    operating_point,
    ratio_row,
    read_grades,
)
from telemetry.analysis.evaluation import ALIVE, DEAD, Truth
from telemetry.analysis.experiment import experiment
from telemetry.core.alerts import Incident

START = datetime(2014, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def hours(values, first=0):
    """Hourly readings from START, one per value, from hour ``first``."""
    return {START + (first + i) * HOUR: v for i, v in enumerate(values)}


def truth(deployment_id, label):
    """A stork truth record whose final still period starts at hour 10."""
    return Truth(
        deployment_id=deployment_id,
        taxon="Ciconia ciconia",
        label=label,
        split="tuning",
        first_fix=START,
        last_fix=START + 200 * HOUR,
        still_start=START + 10 * HOUR,
        still_start_wide=START + 10 * HOUR,
        carcass_min=24 * HOUR,
    )


def mortality(deployment_id, opened_hours, resolved_hours=None):
    """A mortality watch incident opened ``opened_hours`` after START."""
    opened = START + opened_hours * HOUR
    return Incident(
        incident_id=f"{deployment_id}:mortality:{opened.isoformat()}",
        deployment_id=deployment_id,
        detector="mortality",
        status="resolved" if resolved_hours else "open",
        opened_at=opened,
        message="",
        resolved_at=START + resolved_hours * HOUR if resolved_hours else None,
    )


def test_cue_value_ignores_the_hour_the_alert_opened_in():
    """The cue looks only at complete hours before the alert, so a reading
    from the opening hour or later cannot leak in."""
    # A two-hour window, so one stray reading would move the median.
    readings = hours([1.0] * 24 + [99.0, 99.0])
    opened = START + 24 * HOUR + timedelta(minutes=30)
    assert cue_value(readings, opened, 2, 2) == 1.0


def test_cue_value_needs_enough_hours():
    """With fewer readings than ``min_hours`` the cue is undefined, not
    computed from a thin window."""
    readings = hours([1.0] * 11, first=13)
    assert cue_value(readings, START + 24 * HOUR, 24, 12) is None
    assert cue_value(hours([1.0] * 12, first=12), START + 24 * HOUR, 24, 12) == 1.0


def test_cue_value_is_the_median():
    """One burst of movement among still hours does not move the cue."""
    readings = hours([1.0] * 12 + [50.0])
    assert cue_value(readings, START + 13 * HOUR, 24, 12) == 1.0


def test_ratio_row_divides_the_two_shares():
    """The ratio is the true share passing over the false share passing,
    and alerts without a cue value count in neither."""
    cases = (
        [Case("a", "true", 1.0)] * 3
        + [Case("a", "true", 9.0), Case("a", "true", None)]
        + [Case("b", "false", 1.0)]
        + [Case("b", "false", 9.0)] * 3
        + [Case("c", "false", None)]
    )
    row = ratio_row(cases, 2.0)
    assert (row["true"]["passing"], row["true"]["total"]) == (3, 4)
    assert (row["false"]["passing"], row["false"]["total"]) == (1, 4)
    assert row["ratio"] == 3.0
    assert 0 < row["ratio_lower"] < row["ratio"]


def test_ratio_row_has_no_ratio_when_no_false_alert_passes():
    """With no false alert passing the ratio is undefined, but the bound
    from the false share's upper limit is still given."""
    cases = [Case("a", "true", 1.0), Case("b", "false", 9.0)]
    row = ratio_row(cases, 2.0)
    assert row["ratio"] is None
    assert row["ratio_lower"] is not None


def test_operating_point_is_the_lowest_threshold_keeping_enough():
    """The rule picks the lowest threshold that keeps the required share
    of true alerts, and nothing when no threshold does."""
    cases = [Case("a", "true", v) for v in (1.0, 3.0, 5.0, 7.0)]
    rows = [ratio_row(cases, t) for t in (2.0, 4.0, 6.0, 8.0)]
    assert operating_point(rows, 0.5)["threshold"] == 4.0
    assert operating_point(rows[:1], 0.5) is None


def test_build_cases_leaves_out_acceleration_graded_and_ambiguous_birds():
    """A bird whose death was inferred from the accelerometer, or whose
    label is not dead or alive, adds no cases."""
    settings = experiment()
    truths = [
        truth("dead", DEAD),
        truth("circular", DEAD),
        truth("alive", ALIVE),
        truth("unsure", "ambiguous"),
    ]
    readings = {t.deployment_id: hours([1.0] * 40) for t in truths}
    incidents = [mortality(t.deployment_id, 30) for t in truths]
    grades = {"circular": "acc-inferred", "dead": "found"}
    cases = build_cases(truths, incidents, readings, grades, settings)
    assert sorted((c.deployment_id, c.kind) for c in cases) == [
        ("alive", "false"),
        ("dead", "true"),
    ]


def test_build_cases_calls_an_alert_resolved_before_death_false():
    """An alert on a dead bird that cleared before the death began was a
    false alert, and is counted as one."""
    settings = experiment()
    cases = build_cases(
        [truth("dead", DEAD)],
        [mortality("dead", 5, resolved_hours=8)],
        {"dead": hours([1.0] * 40)},
        {},
        settings,
    )
    assert [c.kind for c in cases] == ["false"]


def test_read_grades_keeps_only_rows_with_a_grade(tmp_path):
    """Vulture rows, which have no grade, are left out."""
    path = tmp_path / "labels.csv"
    path.write_text(
        "deployment-id,label,basis,evidence,event-from,grade\n"
        "V1,dead,x,y,,\n"
        "S1,dead,x,y,,found\n",
        encoding="utf-8",
    )
    assert read_grades(path) == {"S1": "found"}


def test_fit_and_markdown_report_the_operating_point():
    """The fit finds the operating point and the page names it."""
    settings = experiment()
    cases = [Case("a", "true", 1.0)] * 4 + [Case("b", "false", 20.0)] * 4
    cases += [Case("c", "false", 1.0)]
    result = fit(cases, settings, animal_months=10.0)
    assert result["operating_point"]["threshold"] == 1.0
    assert result["precision"]["passing"] == 4
    assert "Operating point" in markdown(result, settings)


def test_the_stork_cue_is_defined_in_the_experiment_file():
    """The cue's definition is committed with its threshold grid sorted
    and its keep share a share."""
    cue = experiment().cues["stork_acceleration"]
    assert cue["grid"] == sorted(cue["grid"])
    assert 0 < cue["keep_share"] <= 1
    assert cue["min_hours"] <= cue["window_hours"]
