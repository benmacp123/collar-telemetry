"""How much a stork's acceleration says about a stationary alert.

A stationary watch alert says a bird has not moved. Most such alerts are on
living birds at rest, and a collar on a carcass records a still body. The
cue asks whether the bird's own acceleration, in the hours before the alert
opened, was as still as a carcass would give.

The cue is defined in ``config/experiment.toml`` under
``[cues.stork_acceleration]`` before it is fitted: the signal (the hourly
median burst spread), the statistic and window, the grid of thresholds and
the rule that picks one. This module only carries that definition out, on
the stork tuning populations.

The answer is a likelihood ratio: the share of true alerts that pass the
cue over the share of false alerts that pass it. A ratio of 1 means the cue
tells nothing; the larger it is, the more it separates carcasses from
sleeping birds.
"""

import csv
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from telemetry.analysis.evaluation import ALIVE, DEAD, Truth, classify
from telemetry.analysis.experiment import Experiment
from telemetry.analysis.intervals import wilson
from telemetry.core.alerts import Incident

HOUR = timedelta(hours=1)
TRUE = "true"
FALSE = "false"


@dataclass(frozen=True)
class Case:
    """One watch alert with the cue's value at the time it opened.

    Attributes:
        deployment_id: The bird.
        kind: ``true`` or ``false``, as ``classify`` calls it.
        value: The cue value; None if too few hours of acceleration
            were held before the alert.
    """

    deployment_id: str
    kind: str
    value: float | None


def read_grades(path: Path) -> dict[str, str]:
    """Read how each death label was established.

    Args:
        path: ``data/labels.csv``, whose ``grade`` column is filled for
            the stork rows.

    Returns:
        dict[str, str]: Grade by deployment ID, for rows that have one.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            row["deployment-id"].strip(): row["grade"].strip()
            for row in csv.DictReader(handle)
            if (row.get("grade") or "").strip()
        }


def cue_value(
    readings: dict[datetime, float],
    opened_at: datetime,
    window_hours: int,
    min_hours: int,
) -> float | None:
    """The cue's value for one alert.

    Only complete hours that ended by ``opened_at`` are used, so the cue
    never sees acceleration from after the alert was raised.

    Args:
        readings: Hourly values by hour start, for one bird.
        opened_at: When the alert's evidence ended.
        window_hours: Hours to look back over.
        min_hours: Fewest hours with a reading for the cue to be defined.

    Returns:
        float | None: The median of the readings in the window, or None
        if fewer than ``min_hours`` of the hours have one.
    """
    end = opened_at.replace(minute=0, second=0, microsecond=0)
    values = [
        readings[hour]
        for hour in (end - HOUR * step for step in range(1, window_hours + 1))
        if hour in readings
    ]
    return statistics.median(values) if len(values) >= min_hours else None


def build_cases(
    truths: list[Truth],
    incidents: list[Incident],
    readings: dict[str, dict[datetime, float]],
    grades: dict[str, str],
    settings: Experiment,
) -> list[Case]:
    """The watch alerts that can score the cue.

    A bird is left out whole unless it is labelled dead or alive, and also
    if its death was graded as inferred from the accelerometer, because the
    cue would then be scored against itself. Ambiguous birds, tag events
    and deaths after the track are left out because the alert cannot be
    called right or wrong for them.

    Args:
        truths: What is known about each of one population's birds.
        incidents: That population's incidents.
        readings: Hourly acceleration by deployment ID.
        grades: Death-label grades from ``read_grades``.
        settings: The experiment file.

    Returns:
        list[Case]: One per mortality watch alert on a bird that can score
        the cue.
    """
    cue = settings.cues["stork_acceleration"]
    by_id = {truth.deployment_id: truth for truth in truths}
    cases = []
    for incident in incidents:
        if incident.detector != "mortality":
            continue
        truth = by_id.get(incident.deployment_id)
        if truth is None:
            continue
        if (
            truth.label not in (DEAD, ALIVE)
            or grades.get(truth.deployment_id) in cue["excluded_grades"]
        ):
            continue
        cases.append(
            Case(
                truth.deployment_id,
                classify(truth, incident),
                cue_value(
                    readings.get(truth.deployment_id, {}),
                    incident.opened_at,
                    cue["window_hours"],
                    cue["min_hours"],
                ),
            )
        )
    return cases


def _share(passing: int, total: int) -> dict:
    """A count out of a total, with its Wilson interval.

    Args:
        passing: Cases passing the cue.
        total: Cases with a cue value.

    Returns:
        dict: ``passing``, ``total``, ``share`` and ``wilson``.
    """
    return {
        "passing": passing,
        "total": total,
        "share": round(passing / total, 6) if total else None,
        "wilson": wilson(passing, total),
    }


def ratio_row(cases: list[Case], threshold: float) -> dict:
    """The cue's likelihood ratio at one threshold.

    Cases with no cue value are left out of both shares, so a gap in the
    acceleration record cannot flatter or hurt the cue; their number is
    reported beside the table.

    Args:
        cases: Watch alerts, true and false.
        threshold: The cue passes when its value is at or below this.

    Returns:
        dict: ``threshold``, the ``true`` and ``false`` shares passing, the
        ratio, and a conservative lower bound (the true share's Wilson
        lower bound over the false share's upper bound; None if the
        false share's bound is zero).
    """
    valued = [case for case in cases if case.value is not None]
    true = [case for case in valued if case.kind == TRUE]
    false = [case for case in valued if case.kind == FALSE]
    true_pass = _share(sum(case.value <= threshold for case in true), len(true))
    false_pass = _share(sum(case.value <= threshold for case in false), len(false))
    ratio = lower = None
    if true_pass["share"] is not None and false_pass["share"]:
        ratio = round(true_pass["share"] / false_pass["share"], 3)
    if true_pass["wilson"] and false_pass["wilson"] and false_pass["wilson"][1] > 0:
        lower = round(true_pass["wilson"][0] / false_pass["wilson"][1], 3)
    return {
        "threshold": threshold,
        "true": true_pass,
        "false": false_pass,
        "ratio": ratio,
        "ratio_lower": lower,
    }


def operating_point(rows: list[dict], keep_share: float) -> dict | None:
    """The row the frozen rule picks.

    Args:
        rows: Rows from ``ratio_row``, by rising threshold.
        keep_share: Smallest share of true alerts that must pass.

    Returns:
        dict | None: The lowest-threshold row keeping at least that share
        of true alerts, or None if none does.
    """
    for row in rows:
        if row["true"]["share"] is not None and row["true"]["share"] >= keep_share:
            return row
    return None


def fit(cases: list[Case], settings: Experiment, animal_months: float) -> dict:
    """Run the frozen cue over a set of cases.

    Args:
        cases: Watch alerts from the tuning populations, pooled.
        settings: The experiment file.
        animal_months: Tracked time the cases come from, for rates.

    Returns:
        dict: The ratio at every grid threshold, the operating point the
        rule picks, the precision there with its Wilson interval, and
        how many alerts had no cue value.
    """
    cue = settings.cues["stork_acceleration"]
    rows = [ratio_row(cases, threshold) for threshold in sorted(cue["grid"])]
    point = operating_point(rows, cue["keep_share"])
    precision = None
    if point is not None:
        passing = point["true"]["passing"] + point["false"]["passing"]
        precision = _share(point["true"]["passing"], passing)
    return {
        "rows": rows,
        "operating_point": point,
        "precision": precision,
        "animal_months": round(animal_months, 1),
        "alerts": {
            "true": sum(case.kind == TRUE for case in cases),
            "false": sum(case.kind == FALSE for case in cases),
            "true_without_value": sum(
                case.kind == TRUE and case.value is None for case in cases
            ),
            "false_without_value": sum(
                case.kind == FALSE and case.value is None for case in cases
            ),
            "false_birds": len(
                {case.deployment_id for case in cases if case.kind == FALSE}
            ),
        },
    }


def _pct(share: float | None) -> str:
    """A share as a percentage for the table.

    Args:
        share: A share from 0 to 1, or None.

    Returns:
        str: For example ``52.0%``, or ``-`` for None.
    """
    return "-" if share is None else f"{share * 100:.1f}%"


def markdown(result: dict, settings: Experiment) -> str:
    """The likelihood-ratio table as Markdown.

    Args:
        result: The output of ``fit``.
        settings: The experiment file.

    Returns:
        str: The page.
    """
    cue = settings.cues["stork_acceleration"]
    alerts = result["alerts"]
    point = result["operating_point"]
    lines = [
        "# Stork acceleration cue: likelihood ratio at the watch alert",
        "",
        "Written by `make acceleration` from the stork tuning populations only.",
        f"The cue is the median of the hourly `{cue['signal']}` over the "
        f"{cue['window_hours']} hours before a watch alert opened (at least "
        f"{cue['min_hours']} of them held), and passes when it is at or "
        "below the threshold. The definition is in `config/experiment.toml`.",
        "",
        f"Watch alerts: {alerts['true']} true and {alerts['false']} false "
        f"(on {alerts['false_birds']} birds). Without a cue value: "
        f"{alerts['true_without_value']} true, "
        f"{alerts['false_without_value']} false; they are left out of the "
        "shares below.",
        "",
        "| Threshold | True alerts passing | False alerts passing | "
        "Likelihood ratio | Conservative lower bound |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in result["rows"]:
        lines.append(
            f"| {row['threshold']:g} "
            f"| {row['true']['passing']}/{row['true']['total']} "
            f"({_pct(row['true']['share'])}) "
            f"| {row['false']['passing']}/{row['false']['total']} "
            f"({_pct(row['false']['share'])}) "
            f"| {row['ratio'] if row['ratio'] is not None else '-'} "
            f"| {row['ratio_lower'] if row['ratio_lower'] is not None else '-'} |"
        )
    lines += ["", "## Operating point", ""]
    if point is None:
        lines.append(
            f"No threshold in the grid keeps {_pct(cue['keep_share'])} of true alerts."
        )
        return "\n".join(lines) + "\n"
    lines += [
        f"The frozen rule takes the lowest threshold keeping at least "
        f"{_pct(cue['keep_share'])} of the true alerts: **{point['threshold']:g}**.",
        f"There {_pct(point['true']['share'])} of true and "
        f"{_pct(point['false']['share'])} of false alerts pass, a ratio of "
        f"**{point['ratio']}** (conservative lower bound "
        f"{point['ratio_lower']}).",
        "",
        "The conservative bound divides the true share's Wilson lower bound "
        "by the false share's Wilson upper bound. Both treat alerts as "
        "independent, but false alerts cluster on few birds, so the real "
        "uncertainty is wider.",
        "",
        "## What it would mean for precision",
        "",
        f"Tuning population: {result['animal_months']:.0f} animal-months, "
        f"{alerts['false']} false watch alerts "
        f"({alerts['false'] / result['animal_months']:.3f} per animal-month).",
        f"After the cue: {point['false']['passing']} false alerts remain "
        f"({point['false']['passing'] / result['animal_months']:.3f} per "
        "animal-month). Precision among alerts with a cue value is "
        f"{_pct(result['precision']['share'])}, Wilson 95% interval "
        f"{result['precision']['wilson']}; the escalated target needs a "
        "lower bound above 15%.",
    ]
    return "\n".join(lines) + "\n"
