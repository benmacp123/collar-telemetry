"""The white-stork window sweep (step 3.1 (c)).

Replays the stork tuning populations under each window in
``[sweep.storks]`` (box and every other setting at their defaults) and
scores each population on its own, as the decision rule asks. The load the
window is chosen on leaves out watch alerts whose context is listed in
``load_excludes_context`` (the natal-nest marking); every other measure,
clear time included, counts every watch alert. Only the scenario the
experiment file judges storks under is run, since no other decides the
choice.

The caller passes only tuning populations, so held-out storks are never
replayed here.
"""

import statistics
from dataclasses import dataclass
from pathlib import Path

from telemetry.analysis.evaluation import DEAD, Truth, evaluate
from telemetry.analysis.experiment import (
    CLEAR_HOURS,
    LOAD,
    METRIC_NAMES,
    RATE_AT_MARK,
    experiment,
)
from telemetry.analysis.intervals import rate_bootstrap
from telemetry.analysis.report import (
    INK_SECONDARY,
    LINE_STYLES,
    SCENARIO_LABELS,
    SERIES,
    STYLE,
    _cell,
    _save,
    matplotlib_percent,
)
from telemetry.core.alerts import MORTALITY, Incident
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.pipeline import Overrides
from telemetry.sim.arrival import ArrivalScenario
from telemetry.sim.replay import DEFAULT_SEED, replay

# The population row field holding each watch target's measure. Load is the
# one the rule names: alerts outside the excluded contexts.
FIELDS = {
    LOAD: "load_chosen",
    CLEAR_HOURS: "clear_median_hours",
    RATE_AT_MARK: "rate_at_mark",
}
# The watch targets the window is chosen on; carcass detection is reported.
CHOSEN_ON = (LOAD, CLEAR_HOURS)


@dataclass(frozen=True)
class Population:
    """One stork tuning population, loaded.

    Attributes:
        slug: The study slug, for example ``storks-bavaria``.
        title: Its name in reports.
        deployments: Its deployments.
        fixes: Their fixes.
        truths: What is known about each bird.
    """

    slug: str
    title: str
    deployments: list[Deployment]
    fixes: list[Fix]
    truths: list[Truth]


def grid() -> list[Overrides]:
    """The settings to sweep: each stork window, everything else default.

    Returns:
        list[Overrides]: One per window in ``[sweep.storks]``, in file order.
    """
    settings = experiment()
    return [
        Overrides(species_windows=((settings.stork_taxon, window),))
        for window in settings.stork_windows
    ]


def population_row(
    truths: list[Truth], incidents: list[Incident], mark_hours: float | None
) -> dict:
    """The watch measures for one population at one setting.

    Args:
        truths: The population's birds.
        incidents: Every incident its replay raised.
        mark_hours: The stork reference mark, in hours.

    Returns:
        dict: Deployments, animal-months, watch alerts in all and outside
        the excluded contexts (count, per animal-month and, for the chosen
        load, a by-bird 95% interval), false alerts and their median clear
        time, carcass detection by the mark, and watch precision with its
        by-bird interval.
    """
    settings = experiment()
    excluded = settings.stork_load_excludes
    scores = evaluate(truths, incidents, mark_hours)
    ids = {t.deployment_id for t in truths}
    watch = [i for i in incidents if i.detector == MORTALITY and i.deployment_id in ids]
    kept = [i for i in watch if i.context not in excluded]
    months = {
        t.deployment_id: (t.last_fix - t.first_fix) / settings.animal_month
        for t in truths
    }
    total = sum(months.values())
    # One (alerts, animal-months) pair per bird, in truth order, so the
    # interval resamples whole birds as the decision rule asks.
    per_bird = [
        (
            sum(1 for i in kept if i.deployment_id == t.deployment_id),
            months[t.deployment_id],
        )
        for t in truths
    ]
    judged = scores["precision"]["mortality"]
    return {
        "deployments": len(truths),
        "animal_months": round(total, 1),
        "watch": len(watch),
        "chosen": len(kept),
        "load_all": round(len(watch) / total, 3) if total else None,
        "load_chosen": round(len(kept) / total, 3) if total else None,
        "load_chosen_by_bird": rate_bootstrap(per_bird),
        "false": scores["mortality_clear"]["false"],
        "never_resolved": scores["mortality_clear"]["never_resolved"],
        "clear_median_hours": scores["mortality_clear"]["median_hours"],
        "carcass_deaths": scores["mortality"]["deaths"],
        "carcass_detected": scores["mortality"]["detected"],
        "rate_at_mark": scores["mortality"]["rate_at_mark"],
        "precision": judged["precision"],
        "precision_by_bird": judged["bootstrap"],
    }


def sweep_point(
    populations: list[Population],
    scenario: ArrivalScenario,
    overrides: Overrides,
    mark_hours: float | None,
) -> dict:
    """Replay and score every population at one setting.

    Args:
        populations: The stork tuning populations.
        scenario: The storks' upload pattern.
        overrides: The setting.
        mark_hours: The stork reference mark, in hours.

    Returns:
        dict: The window in hours and one row per population, by slug.
    """
    taxon = experiment().stork_taxon
    rows = {}
    for population in populations:
        result = replay(
            population.deployments,
            population.fixes,
            scenario,
            DEFAULT_SEED,
            overrides=overrides,
        )
        rows[population.slug] = population_row(
            population.truths, result.incidents, mark_hours
        )
    return {
        "window_hours": overrides.to_dict()["species_windows_hours"][taxon],
        "populations": rows,
    }


def meets(row: dict) -> bool:
    """Whether one population's row meets every target the window is chosen on.

    Args:
        row: A population row from ``population_row``.

    Returns:
        bool: True if the chosen load and the clear time both meet their
        targets; a measure that is missing counts as a miss.
    """
    targets = [t for t in experiment().targets_for(MORTALITY) if t.metric in CHOSEN_ON]
    values = [row.get(FIELDS[t.metric]) for t in targets]
    return all(v is not None and t.met(v) for t, v in zip(targets, values))


def stork_choice(points: list[dict]) -> float | None:
    """The stork window chosen by the rule in ``[sweep.storks]``.

    The shortest window at which every population, each on its own, meets
    the load and clear-time watch targets.

    Args:
        points: Sweep points from ``sweep_point``, in any order.

    Returns:
        float | None: The window in hours, or None if no window meets the
        rule (the window then stays 24 h).
    """
    return next(
        (
            point["window_hours"]
            for point in sorted(points, key=lambda p: p["window_hours"])
            if all(meets(row) for row in point["populations"].values())
        ),
        None,
    )


def reference_mark(truths: list[Truth]) -> float | None:
    """The stork reference mark: the median carcass period over all populations.

    Args:
        truths: Every stork tuning bird, pooled.

    Returns:
        float | None: Median hours, or None if no bird is a carcass death.
    """
    periods = [t.still_hours for t in truths if t.label == DEAD and t.carcass]
    return round(statistics.median(periods), 1) if periods else None


def _interval(bounds: list[float] | None, digits: int = 3) -> str:
    """A by-bird interval as text.

    Args:
        bounds: Lower and upper bound, or None.
        digits: Decimal places.

    Returns:
        str: "low-high", or a dash if there is none.
    """
    return f"{bounds[0]:.{digits}f}-{bounds[1]:.{digits}f}" if bounds else "-"


def markdown(report: dict) -> str:
    """The stork sweep as Markdown.

    Args:
        report: As written by ``scripts/sweep_storks.py``: ``scenario``,
            ``mark_hours``, ``populations`` (slug to title), ``points`` and
            ``choice``.

    Returns:
        str: The tables and the rule's outcome.
    """
    settings = experiment()
    targets = {t.metric: t for t in settings.targets_for(MORTALITY)}
    titles = report["populations"]
    excluded = ", ".join(f"`{c}`" for c in sorted(settings.stork_load_excludes))
    lines = [
        "# Stork window sweep",
        "",
        "Generated by `make sweep-storks`; do not edit by hand. Stork tuning "
        f"populations only ({', '.join(titles.values())}); the held-out "
        f"populations were not replayed. {SCENARIO_LABELS[report['scenario']]} "
        f"uploads; box and every other setting at their defaults. Stork "
        f"reference mark {report['mark_hours']} h (median carcass period, both "
        "populations pooled).",
        "",
        "Decision rule (fixed in `[sweep.storks]` before this sweep first ran): "
        "the shortest window at which every population, each on its own, meets "
        f"the load ({targets[LOAD].limit_text()} per animal-month, alerts marked "
        f"{excluded} left out) and the clear-time ({targets[CLEAR_HOURS].limit_text()}) "
        "targets. Carcass detection by the mark is reported, not chosen on. "
        "Intervals resample whole birds.",
        "",
    ]
    for slug, title in titles.items():
        lines += [
            f"## {title}",
            "",
            "| Window (h) | Load, unmarked (by bird 95%) | Load, all | False alerts "
            "| Median clear (h) | Never cleared | Carcasses by the mark "
            "| Precision (by bird 95%) | Meets rule |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for point in sorted(report["points"], key=lambda p: p["window_hours"]):
            row = point["populations"][slug]
            rate = row["rate_at_mark"]
            precision = row["precision"]
            lines.append(
                f"| {point['window_hours']:g} "
                f"| {_cell(row['load_chosen'], 3)} ({_interval(row['load_chosen_by_bird'])}) "
                f"| {_cell(row['load_all'], 3)} | {row['false']} "
                f"| {_cell(row['clear_median_hours'], 1)} | {row['never_resolved']} "
                f"| {row['carcass_detected']} of {row['carcass_deaths']}, "
                f"{'-' if rate is None else f'{rate:.0%}'} "
                f"| {'-' if precision is None else f'{precision:.1%}'} "
                f"({_interval(row['precision_by_bird'] and [100 * b for b in row['precision_by_bird']], 1)}%) "
                f"| {'yes' if meets(row) else 'no'} |"
            )
        lines.append("")
    choice = report["choice"]
    lines += [
        "## Outcome",
        "",
        (
            f"The rule chooses **{choice:g} h**: the shortest window at which "
            "both populations meet the load and clear-time targets."
            if choice is not None
            else "No window meets the rule, so the stork window **stays 24 h** and "
            "the miss is reported; no target is relaxed."
        ),
        "",
        f"Carcass detection by the mark has a target of "
        f"{targets[RATE_AT_MARK].limit_text()}; it is reported above and did not "
        "decide the window.",
        "",
    ]
    return "\n".join(lines)


def write(report: dict, markdown_path: Path, figure_path: Path) -> None:
    """Write the stork sweep's Markdown and figure.

    Args:
        report: As for ``markdown``.
        markdown_path: Output Markdown file.
        figure_path: Output PNG; its folder is created if needed.
    """
    markdown_path.write_text(markdown(report), encoding="utf-8")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    pyplot.rcParams.update(STYLE)
    figure = _figure(pyplot, report)
    _save(figure, figure_path)
    pyplot.close(figure)


def _figure(pyplot, report: dict):
    """Each watch measure against the stork window, one line per population.

    Args:
        pyplot: ``matplotlib.pyplot``.
        report: As for ``markdown``.

    Returns:
        matplotlib.figure.Figure: Unmarked load, median clear time and
        carcasses flagged by the mark, each with its target dashed.
    """
    watch = experiment().targets_for(MORTALITY)
    points = sorted(report["points"], key=lambda p: p["window_hours"])
    windows = [p["window_hours"] for p in points]
    figure, axes = pyplot.subplots(1, len(watch), figsize=(13, 3.8))
    for ax, target in zip(axes, watch):
        field = FIELDS[target.metric]
        for index, (slug, title) in enumerate(report["populations"].items()):
            ys = [p["populations"][slug].get(field) for p in points]
            ax.plot(
                windows,
                [float("nan") if y is None else y for y in ys],
                color=SERIES[index],
                linestyle=LINE_STYLES[index],
                linewidth=2,
                marker="o",
                markersize=5,
                label=title.removeprefix("White stork, "),
            )
        ax.axhline(
            target.limit,
            color=INK_SECONDARY,
            linestyle="--",
            linewidth=1,
            label=f"Target: {target.limit_text()}",
        )
        title = METRIC_NAMES[target.metric]
        ax.set_title(f"{title}, unmarked" if target.metric == LOAD else title)
        ax.set_xlabel("Stork window (h)")
        if target.metric == RATE_AT_MARK:
            ax.yaxis.set_major_formatter(matplotlib_percent())
        ax.legend(fontsize=8)
    axes[0].set_ylabel("Per animal-month")
    axes[1].set_ylabel("Median hours, living birds")
    axes[2].set_ylabel("Share of carcasses")
    figure.suptitle(
        "Stork watch targets by window, tuning populations; "
        f"{SCENARIO_LABELS[report['scenario']]} uploads",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    figure.tight_layout()
    return figure
