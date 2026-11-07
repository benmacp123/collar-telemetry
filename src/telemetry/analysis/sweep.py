"""Threshold sweeps: replay the tuning set under alternative settings.

The mortality and gap detectors do not affect each other (the lifecycle
keeps one incident stream per detector), so each is swept on its own
rather than over the full product: the mortality window and box with the
gap margin at its default, then the gap margin with mortality at its
defaults. Each setting is scored with ``telemetry.analysis.evaluation`` so its
false-alarm rate, detection and precision (with intervals and the
base-rate ceiling) can be set side by side.

Only tuning-set deployments are passed in, so scoring-set tracks are never
replayed while thresholds are chosen.
"""

from telemetry.sim.arrival import ArrivalScenario
from telemetry.analysis.evaluation import Truth, evaluate
from telemetry.analysis.experiment import experiment
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.pipeline import Overrides
from telemetry.sim.replay import DEFAULT_SEED, replay


def grid() -> list[tuple[str, Overrides]]:
    """The settings to sweep, each tagged with the detector it varies.

    Returns:
        list[tuple[str, Overrides]]: ("mortality", ...) for every window and
        box, then ("gap", ...) for every upload margin.
    """
    settings = experiment()
    points = [
        ("mortality", Overrides(mortality_window=window, mortality_box_m=box))
        for box in settings.mortality_boxes_m
        for window in settings.mortality_windows
    ]
    points += [
        ("gap", Overrides(upload_margin=margin)) for margin in settings.upload_margins
    ]
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
    judged = scores["precision"]["mortality"]
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
        "mortality_true": judged["true"],
        "mortality_tag_event": judged["tag-event"],
        "mortality_judged": judged["judged"],
        "mortality_precision": judged["precision"],
        "mortality_death_precision": judged["death_precision"],
        "mortality_wilson": judged["wilson"],
        "mortality_bootstrap": judged["bootstrap"],
        "mortality_ceiling": judged["ceiling"],
        "mortality_clear_median_hours": scores["mortality_clear"]["median_hours"],
        "potential_death_precision": scores["precision"]["potential_death"][
            "precision"
        ],
        "gap_precision": scores["precision"]["gap"]["precision"],
        "gap_ceiling": scores["precision"]["gap"]["ceiling"],
        "random_precision": scores["random_precision"],
        "random_precision_tags": scores["random_precision_tags"],
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
