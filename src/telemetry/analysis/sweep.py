"""Threshold sweeps: replay the tuning set under alternative settings.

The mortality and gap detectors do not affect each other (the lifecycle
keeps one incident stream per detector), so each is swept on its own
rather than over the full product: the mortality window and box with the
gap margin at its default, then the gap margin with mortality at its
defaults. Each setting is scored with ``telemetry.analysis.evaluation`` so its
false-alarm rate, detection and precision (with intervals and the
base-rate ceiling) can be set side by side.

A third sweep varies one species' window with every other species at its
own (step 2.4, black vultures). Each deployment runs its own stream, so
a species' rows depend only on its own window; the whole-set rows are what
the watch targets judge. Mortality rows are also broken down by species.

Only tuning-set deployments are passed in, so scoring-set tracks are never
replayed while thresholds are chosen.
"""

from telemetry.sim.arrival import ArrivalScenario
from telemetry.analysis.evaluation import Truth, evaluate
from telemetry.analysis.experiment import (
    CLEAR_HOURS,
    LOAD,
    RATE_AT_MARK,
    experiment,
)
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.pipeline import Overrides
from telemetry.sim.replay import DEFAULT_SEED, replay

# The sweep row field holding each watch target's measure.
WATCH_FIELDS = {
    LOAD: "mortality_per_animal_month",
    CLEAR_HOURS: "mortality_clear_median_hours",
    RATE_AT_MARK: "carcass_rate_at_mark",
}
# The watch targets the species window is chosen on; carcass detection is
# reported beside them, not chosen on.
CHOSEN_ON = (LOAD, CLEAR_HOURS)


def grid() -> list[tuple[str, Overrides]]:
    """The settings to sweep, each tagged with the detector it varies.

    Returns:
        list[tuple[str, Overrides]]: ("mortality", ...) for every window and
        box, then ("gap", ...) for every upload margin, then ("species",
        ...) for every window of the species swept on its own.
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
    points += [
        ("species", Overrides(species_windows=((settings.species_taxon, window),)))
        for window in settings.species_windows
    ]
    return points


def by_taxon(
    truths: list[Truth], incidents: list, mark_hours: float
) -> dict[str, dict]:
    """The watch measures for each species on its own.

    Args:
        truths: The deployments scored.
        incidents: Every incident the replay raised.
        mark_hours: Reference deadline for the detection rate.

    Returns:
        dict[str, dict]: By taxon: deployments, animal-months, mortality
        load, false alerts, median clear time and carcass detection.
    """
    out = {}
    for taxon in sorted({t.taxon for t in truths}):
        scores = evaluate(
            [t for t in truths if t.taxon == taxon], incidents, mark_hours
        )
        mortality = scores["mortality"]
        out[taxon] = {
            "deployments": scores["deployments"],
            "animal_months": scores["animal_months"],
            "mortality_per_animal_month": scores["load"]
            .get("mortality", {})
            .get("per_animal_month", 0.0),
            "mortality_false": scores["mortality_clear"]["false"],
            "mortality_clear_median_hours": scores["mortality_clear"]["median_hours"],
            "carcass_deaths": mortality["deaths"],
            "carcass_detected": mortality["detected"],
            "carcass_rate_at_mark": mortality["rate_at_mark"],
        }
    return out


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
        swept: What the setting varies: "mortality", "gap" or "species".
        overrides: The setting.
        mark_hours: Reference deadline for the mortality detection rate.

    Returns:
        dict: The setting and its headline scores, JSON-ready; mortality
        and species rows also carry them by taxon.
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
        **(
            {"by_taxon": by_taxon(truths, result.incidents, mark_hours)}
            if swept != "gap"
            else {}
        ),
    }


def species_rows(rows: list[dict], scenario: str) -> list[tuple[float, dict]]:
    """The species sweep's rows under one scenario, shortest window first.

    Args:
        rows: Every sweep row.
        scenario: The scenario name.

    Returns:
        list[tuple[float, dict]]: (window in hours, row) pairs.
    """
    taxon = experiment().species_taxon
    return sorted(
        (
            (row["species_windows_hours"][taxon], row)
            for row in rows
            if row["swept"] == "species" and row["scenario"] == scenario
        ),
        key=lambda pair: pair[0],
    )


def meets_chosen_on(row: dict) -> bool:
    """Whether a row meets every watch target the window is chosen on.

    Args:
        row: A sweep row, scored on the whole set.

    Returns:
        bool: True if load and clear time both meet their targets.
    """
    targets = [
        t for t in experiment().targets_for("mortality") if t.metric in CHOSEN_ON
    ]
    values = [row.get(WATCH_FIELDS[t.metric]) for t in targets]
    return all(v is not None and t.met(v) for t, v in zip(targets, values))


def species_choice(rows: list[dict], scenario: str) -> float | None:
    """The species window chosen by the rule in the experiment file.

    The shortest window at which the whole set meets the load and clear-time
    watch targets, since a shorter window flags carcasses sooner.

    Args:
        rows: Every sweep row.
        scenario: The study's scenario, the one targets are judged under.

    Returns:
        float | None: The window in hours, or None if no window meets both
        (the rule then keeps 36 h).
    """
    return next(
        (
            window
            for window, row in species_rows(rows, scenario)
            if meets_chosen_on(row)
        ),
        None,
    )
