"""How the mortality detector decides a still tag has moved again.

The bounding-box test grows with every fix, so a carcass reporting
hundreds of scattered fixes eventually puts two in a row past the box's
far edge: the alert resolves as "moving again" and reopens within the
merge window (a flap), or, past it, splits one death into several
incidents. This module replays alternatives side by side:

- the box at 100 m (the frozen default), 150 m and 200 m;
- three fixes outside the cluster to confirm a move, not two;
- longer merge windows (72 h and 96 h, against 48 h);
- a fixed leaving radius once alerted (50, 75 and 100 m from the
  cluster's centre at the alert), which leaves every open unchanged.
  75 m was chosen (owner, 2026-10-22) and is now the default.

Each is scored on the vulture tuning set (false mortality alerts on
living birds, how long they stay open, and the six real carcasses) and on
synthetic mammal deaths drawn with ``TUNING_SEED``, not the seed of the
reported variants, so the choice is not made on the deaths it is then
reported on.
"""

import math
from datetime import datetime, timedelta

from telemetry.analysis.evaluation import (
    DEAD,
    Truth,
    classify,
    evaluate,
    score_synthetic,
)
from telemetry.core.alerts import POTENTIAL_DEATH, MORTALITY, Incident
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.pipeline import Overrides
from telemetry.sim.arrival import ArrivalScenario
from telemetry.sim.replay import DEFAULT_SEED, replay
from telemetry.sim.synthetic import REGIMES, InjectedDeath

HOUR = timedelta(hours=1)
# Seed for the synthetic deaths the choice is made on; the reported
# variants use ``DEFAULT_SEED``.
TUNING_SEED = 2027


def grid() -> list[tuple[str, Overrides]]:
    """The settings to compare, each with a short label.

    The radius was chosen from this comparison, so the other changes are
    each made to the box-only detector it was chosen against.

    Returns:
        list[tuple[str, Overrides]]: The box-only detector first, then one
        change to it at a time, then the radii.
    """
    box = {"mortality_box_only": True}
    return [
        ("box only", Overrides(**box)),
        ("box 150 m", Overrides(mortality_box_m=150.0, **box)),
        ("box 200 m", Overrides(mortality_box_m=200.0, **box)),
        ("leave 3 fixes", Overrides(mortality_leave_fixes=3, **box)),
        ("merge 72 h", Overrides(mortality_merge=72 * HOUR, **box)),
        ("merge 96 h", Overrides(mortality_merge=96 * HOUR, **box)),
        ("radius 50 m", Overrides(mortality_leave_radius_m=50.0)),
        ("radius 75 m (default)", Overrides()),
        ("radius 100 m", Overrides(mortality_leave_radius_m=100.0)),
    ]


def by_deployment(incidents: list[Incident], detector: str) -> dict:
    """One detector's incidents grouped by deployment, oldest first.

    Args:
        incidents: Every incident of a replay.
        detector: The detector to keep.

    Returns:
        dict[str, list[Incident]]: Incidents by deployment ID, by opening
        time.
    """
    out: dict[str, list[Incident]] = {}
    for incident in sorted(incidents, key=lambda i: i.opened_at):
        if incident.detector == detector:
            out.setdefault(incident.deployment_id, []).append(incident)
    return out


def death_outcome(death: datetime, incidents: list[Incident]) -> dict:
    """What a deployment's incidents of one detector did after a death.

    Args:
        death: When the animal died.
        incidents: The deployment's incidents of one detector, oldest
            first.

    Returns:
        dict: ``incidents`` still open after the death (more than one is a
        split death), their ``flaps`` (false "moving again" resolves taken
        back within the merge window) and ``ends_resolved`` (the last one
        says the carcass moved away).
    """
    after = [i for i in incidents if i.resolved_at is None or i.resolved_at > death]
    return {
        "incidents": len(after),
        "flaps": sum(i.flaps for i in after),
        "ends_resolved": bool(after) and after[-1].resolved_at is not None,
    }


def summarise_outcomes(outcomes: list[dict]) -> dict:
    """Counts over a group of deaths' outcomes.

    Args:
        outcomes: One ``death_outcome`` per death.

    Returns:
        dict: Deaths; how many were never flagged, split, flapped or ended
        resolved; and the total flaps.
    """
    return {
        "deaths": len(outcomes),
        "missed": sum(1 for o in outcomes if o["incidents"] == 0),
        "split": sum(1 for o in outcomes if o["incidents"] > 1),
        "flapped": sum(1 for o in outcomes if o["flaps"] > 0),
        "flaps": sum(o["flaps"] for o in outcomes),
        "ends_resolved": sum(1 for o in outcomes if o["ends_resolved"]),
    }


def false_alarm_hours(truths: list[Truth], incidents: list[Incident]) -> dict:
    """How long false mortality alerts on living animals stay open.

    A leaving radius can only keep an alert open longer, so this is what
    it costs on animals that are alive.

    Args:
        truths: The deployments.
        incidents: Every incident of a replay.

    Returns:
        dict: False alerts, how many never resolved, their flaps, and the
        median and 90th percentile hours from opening to resolving (evidence
        times) among those resolved.
    """
    by_id = {t.deployment_id: t for t in truths}
    false = [
        i
        for deployment_id, own in by_deployment(incidents, MORTALITY).items()
        for i in own
        if classify(by_id[deployment_id], i) == "false"
    ]
    hours = sorted((i.resolved_at - i.opened_at) / HOUR for i in false if i.resolved_at)
    return {
        "incidents": len(false),
        "never_resolved": sum(1 for i in false if i.resolved_at is None),
        "flaps": sum(i.flaps for i in false),
        "median_hours_open": _quantile(hours, 0.5),
        "p90_hours_open": _quantile(hours, 0.9),
    }


def _quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile, rounded to 0.1.

    Args:
        values: Sorted values.
        q: Quantile between 0 and 1.

    Returns:
        float | None: The value at rank ``ceil(q * n)``, or None if empty.
    """
    if not values:
        return None
    rank = max(1, math.ceil(q * len(values)))
    return round(values[rank - 1], 1)


def score_real(
    deployments: list[Deployment],
    fixes: list[Fix],
    truths: list[Truth],
    scenario: ArrivalScenario,
    overrides: Overrides,
    mark_hours: float,
) -> dict:
    """Replay and score one setting on real deployments (vulture tuning set).

    Args:
        deployments: The deployments.
        fixes: Their fixes.
        truths: Their truth records.
        scenario: The upload pattern.
        overrides: The setting.
        mark_hours: Reference deadline for the detection rate.

    Returns:
        dict: False mortality load, how long false alerts stay open,
        carcass detection, and what the mortality and ``potential_death``
        incidents did after each carcass death.
    """
    result = replay(deployments, fixes, scenario, DEFAULT_SEED, overrides=overrides)
    scores = evaluate(truths, result.incidents, mark_hours)
    carcasses = [t for t in truths if t.label == DEAD and t.carcass]
    return {
        "false_mortality_per_animal_month": scores["false_mortality"][
            "per_animal_month"
        ],
        "false_alarms": false_alarm_hours(truths, result.incidents),
        "carcass": {
            "deaths": scores["mortality"]["deaths"],
            "detected": scores["mortality"]["detected"],
            "rate_at_mark": scores["mortality"]["rate_at_mark"],
        },
        **_outcomes(
            {t.deployment_id: (t.still_start, "carcass") for t in carcasses},
            result.incidents,
            ["carcass"],
        ),
    }


def score_variant(
    deployments: list[Deployment],
    fixes: list[Fix],
    truths: list[Truth],
    deaths: list[InjectedDeath],
    scenario: ArrivalScenario,
    overrides: Overrides,
    mark_hours: float,
) -> dict:
    """Replay and score one setting on a synthetic variant.

    Args:
        deployments: The variant's deployments.
        fixes: Their fixes.
        truths: Their truth records.
        deaths: What was injected, one per deployment.
        scenario: The upload pattern.
        overrides: The setting.
        mark_hours: Reference deadline for the detection rate.

    Returns:
        dict: How long false alerts before the deaths stay open,
        detection by regime, and what the mortality and ``potential_death``
        incidents did after each injected death, by regime.
    """
    result = replay(deployments, fixes, scenario, DEFAULT_SEED, overrides=overrides)
    scores = score_synthetic(truths, result.incidents, mark_hours, deaths)
    return {
        "false_alarms": false_alarm_hours(truths, result.incidents),
        "detection": {
            regime: {
                "deaths": scores["synthetic"][regime]["deaths"],
                "detected": scores["synthetic"][regime]["mortality"][
                    "detected_injected"
                ],
                "rate_at_mark": scores["synthetic"][regime]["mortality"][
                    "rate_at_mark_injected"
                ],
            }
            for regime in REGIMES
        },
        **_outcomes(
            {d.deployment_id: (d.death_time, d.regime) for d in deaths},
            result.incidents,
            list(REGIMES),
        ),
    }


def _outcomes(
    deaths: dict[str, tuple[datetime, str]],
    incidents: list[Incident],
    groups: list[str],
) -> dict:
    """Death outcomes for mortality and ``potential_death``, by group.

    Args:
        deaths: Death time and group by deployment ID.
        incidents: Every incident of a replay.
        groups: Group names, in report order.

    Returns:
        dict: ``mortality`` and ``potential_death``, each mapping every group
        to ``summarise_outcomes``.
    """
    out = {}
    for detector in (MORTALITY, POTENTIAL_DEATH):
        own = by_deployment(incidents, detector)
        out[detector] = {
            group: summarise_outcomes(
                [
                    death_outcome(time, own.get(deployment_id, []))
                    for deployment_id, (time, name) in deaths.items()
                    if name == group
                ]
            )
            for group in groups
        }
    return out
