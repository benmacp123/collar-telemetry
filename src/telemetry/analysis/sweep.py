"""Threshold sweeps: replay the tuning set under alternative settings.

The mortality and gap detectors do not affect each other (the lifecycle
keeps one incident stream per detector), so each is swept on its own
rather than over the full product: the mortality window and box with the
gap margin at its default, then the gap margin with mortality at its
defaults. Each setting is scored with ``telemetry.analysis.evaluation`` so its
false-alarm rate and detection can be set side by side.

Only tuning-set deployments are passed in, so scoring-set tracks are never
replayed while thresholds are chosen.
"""

from datetime import timedelta

from telemetry.sim.arrival import ArrivalScenario
from telemetry.analysis.evaluation import Truth, evaluate
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.pipeline import Overrides
from telemetry.sim.replay import DEFAULT_SEED, replay

HOUR = timedelta(hours=1)
MORTALITY_WINDOWS_H = (24, 36, 48, 72)
MORTALITY_BOXES_M = (100.0, 150.0, 200.0)
UPLOAD_MARGINS_H = (6, 12, 24, 36, 48)


def grid() -> list[tuple[str, Overrides]]:
    """The settings to sweep, each tagged with the detector it varies.

    Returns:
        list[tuple[str, Overrides]]: ("mortality", ...) for every window and
        box, then ("gap", ...) for every upload margin.
    """
    points = [
        ("mortality", Overrides(mortality_window=w * HOUR, mortality_box_m=box))
        for box in MORTALITY_BOXES_M
        for w in MORTALITY_WINDOWS_H
    ]
    points += [("gap", Overrides(upload_margin=m * HOUR)) for m in UPLOAD_MARGINS_H]
    return points


def sweep_point(
    deployments: list[Deployment],
    fixes: list[Fix],
    truths: list[Truth],
    scenario: ArrivalScenario,
    swept: str,
    overrides: Overrides,
    mark_hours: float,
) -> dict:
    """Replay and score one setting under one scenario.

    Args:
        deployments: Tuning-set deployments.
        fixes: Their fixes.
        truths: Their truth records.
        scenario: The upload pattern.
        swept: Which detector the setting varies, "mortality" or "gap".
        overrides: The setting.
        mark_hours: Reference deadline for the mortality detection rate.

    Returns:
        dict: The setting and its headline scores, JSON-ready.
    """
    result = replay(deployments, fixes, scenario, DEFAULT_SEED, overrides=overrides)
    scores = evaluate(truths, result.incidents, mark_hours)
    gap = scores["load"].get("gap", {})
    mortality = scores["mortality"]
    delays = [
        d["mortality_delay_hours"]
        for d in scores["deaths"]
        if d["carcass"] and d["mortality_delay_hours"] is not None
    ]
    return {
        "swept": swept,
        "scenario": scenario.name,
        **overrides.to_dict(),
        "mortality_per_animal_month": scores["load"]
        .get("mortality", {})
        .get("per_animal_month", 0.0),
        "false_mortality_per_animal_month": scores["false_mortality"][
            "per_animal_month"
        ],
        "carcass_deaths": mortality["deaths"],
        "carcass_detected": mortality["detected"],
        "carcass_rate_at_mark": mortality["rate_at_mark"],
        "carcass_rate_at_mark_200m": mortality["rate_at_mark_200m"],
        "carcass_max_delay_hours": max(delays) if delays else None,
        "gap_per_animal_month": gap.get("per_animal_month", 0.0),
        "gap_late_fix_share": (
            round(gap["late_fix"] / gap["incidents"], 3)
            if gap.get("incidents")
            else None
        ),
        "other_deaths": scores["gap_on_deaths"]["deaths"],
        "other_deaths_detected": scores["gap_on_deaths"]["detected"],
        "other_deaths_median_gap_delay_hours": scores["gap_on_deaths"][
            "median_delay_hours"
        ],
        "other_deaths_max_gap_delay_hours": max(
            (
                d["gap_delay_hours"]
                for d in scores["deaths"]
                if not d["carcass"] and d["gap_delay_hours"] is not None
            ),
            default=None,
        ),
    }
