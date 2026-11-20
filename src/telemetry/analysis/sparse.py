"""The sparse-tag mark: which stork watch alerts come from tags that fix rarely.

A tag that fixes about once a day can find a living bird at the same roost
every time, so its still runs last for days and the mortality detector
alerts on them (``results/bouts/``). This module measures, for each watch
alert, the tag's fix rate **before** the still run began, and works through
the rule in ``config/experiment.toml`` under ``[gate.sparse_tag]``: which
threshold, if any, would mark alerts ``sparse_tag`` without hiding the
carcasses. The rate is taken before the run because carcass collars fix
less often than their own baseline after death (``results/fixrate/``): a
rate inside the run would mark exactly those.

Nothing here changes a detector; a chosen threshold is carried into core as
its own change, with a test that core marks what this module counted.
"""

import bisect
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.analysis.evaluation import ALIVE, DEAD, Truth, classify
from telemetry.analysis.fixrate import still_start
from telemetry.analysis.intervals import rate_bootstrap
from telemetry.core.alerts import MORTALITY, NATAL_NEST, Incident
from telemetry.core.fixes import Fix

DAY = timedelta(days=1)
TRUE = "true"
FALSE = "false"


@dataclass(frozen=True)
class Case:
    """One watch alert and what the rule needs to know about it.

    Attributes:
        deployment_id: The bird.
        rate: Fixes per day before the still run, or None if too little
            of the bird's track came before it.
        natal: Whether the detector already marked it ``natal_nest``.
        kind: ``true`` or ``false`` on a bird labelled dead or alive,
            otherwise None.
        found: Whether the bird's death is graded ``found``.
    """

    deployment_id: str
    rate: float | None
    natal: bool
    kind: str | None
    found: bool

    def marked(self, threshold: float) -> bool:
        """Whether a threshold would mark this alert ``sparse_tag``.

        Args:
            threshold: Fixes per day below which a tag counts as sparse.

        Returns:
            True if the alert has a rate and it is below the threshold.
        """
        return self.rate is not None and self.rate < threshold


def baseline_rate(
    times: list[datetime],
    start: datetime,
    baseline_days: int,
    min_baseline_days: float,
) -> float | None:
    """Fixes per tracked day in the span before a still run.

    Args:
        times: The bird's fix times, sorted.
        start: When the still run began.
        baseline_days: Days before ``start`` the span reaches back.
        min_baseline_days: Fewest tracked days the span needs.

    Returns:
        Fixes per day, or None if the bird was tracked for less than
        ``min_baseline_days`` of the span.
    """
    # The span starts at the bird's first fix when that is later, so a young
    # track is not diluted by days before its tag was on.
    begin = max(start - baseline_days * DAY, times[0])
    tracked = (start - begin) / DAY
    if tracked < min_baseline_days:
        return None
    count = bisect.bisect_left(times, start) - bisect.bisect_left(times, begin)
    return count / tracked


def build_cases(
    truths: list[Truth],
    incidents: list[Incident],
    fixes: list[Fix],
    grades: dict[str, str],
    gate: dict,
) -> list[Case]:
    """One case per watch alert in a population.

    Args:
        truths: What is known about each of the population's birds.
        incidents: Every incident its replay raised.
        fixes: The population's fixes, in any order.
        grades: Death-label grades by deployment ID.
        gate: The experiment file's ``[gate.sparse_tag]`` table.

    Returns:
        The cases, in incident order.

    Raises:
        ValueError: If a watch alert's text names no still-run start.
    """
    times: dict[str, list[datetime]] = defaultdict(list)
    for fix in fixes:
        times[fix.deployment_id].append(fix.timestamp)
    for own in times.values():
        own.sort()
    by_id = {truth.deployment_id: truth for truth in truths}
    cases = []
    for incident in incidents:
        if incident.detector != MORTALITY or incident.deployment_id not in by_id:
            continue
        start = still_start(incident.message)
        if start is None:
            raise ValueError(f"no still-run start in {incident.incident_id}")
        truth = by_id[incident.deployment_id]
        # Ambiguous birds and tag events cannot call an alert right or wrong,
        # as in the natal-nest split.
        kind = None
        if truth.label in (DEAD, ALIVE):
            kind = TRUE if classify(truth, incident) == TRUE else FALSE
        cases.append(
            Case(
                deployment_id=incident.deployment_id,
                rate=baseline_rate(
                    times[incident.deployment_id],
                    start,
                    gate["baseline_days"],
                    gate["min_baseline_days"],
                ),
                natal=incident.context == NATAL_NEST,
                kind=kind,
                found=grades.get(incident.deployment_id) == gate["found_grade"],
            )
        )
    return cases


def threshold_row(
    cases: list[Case],
    truths: list[Truth],
    threshold: float | None,
    animal_month: timedelta,
) -> dict:
    """What one threshold would do to one population.

    Args:
        cases: The population's watch alerts.
        truths: The population's birds.
        threshold: Fixes per day below which an alert is marked; None for
            no mark (the reference row).
        animal_month: Length of an animal-month.

    Returns:
        The threshold, alerts newly marked (all, true, true on ``found``
        birds, false), unmarked load per animal-month with a by-bird 95%
        interval, and dead birds whose every true alert carries a mark.
    """

    def sparse(case: Case) -> bool:
        """Whether this row's threshold marks the case.

        Args:
            case: A watch alert.

        Returns:
            True if a threshold is set and marks it.
        """
        return threshold is not None and case.marked(threshold)

    newly = [c for c in cases if sparse(c) and not c.natal]
    unmarked = [c for c in cases if not c.natal and not sparse(c)]
    months = {
        t.deployment_id: (t.last_fix - t.first_fix) / animal_month for t in truths
    }
    total = sum(months.values())
    per_bird = [
        (
            sum(1 for c in unmarked if c.deployment_id == t.deployment_id),
            months[t.deployment_id],
        )
        for t in truths
    ]
    true_by_bird: dict[str, list[Case]] = defaultdict(list)
    for case in cases:
        if case.kind == TRUE:
            true_by_bird[case.deployment_id].append(case)
    hidden = sum(
        1 for own in true_by_bird.values() if all(c.natal or sparse(c) for c in own)
    )
    return {
        "threshold_per_day": threshold,
        "newly_marked": len(newly),
        "newly_marked_true": sum(1 for c in newly if c.kind == TRUE),
        "newly_marked_true_found": sum(1 for c in newly if c.kind == TRUE and c.found),
        "newly_marked_false": sum(1 for c in newly if c.kind == FALSE),
        "unmarked": len(unmarked),
        "load_unmarked": round(len(unmarked) / total, 3) if total else None,
        "load_unmarked_by_bird": rate_bootstrap(per_bird),
        "deaths_alerted": len(true_by_bird),
        "deaths_only_marked": hidden,
    }


def population_summary(cases: list[Case]) -> dict:
    """How the baseline rate is spread over a population's watch alerts.

    Args:
        cases: The population's watch alerts.

    Returns:
        Alert counts (all, without a rate, true, false) and the median
        rate of true and of false alerts.
    """

    def median(kind: str) -> float | None:
        """Median rate over one kind of alert.

        Args:
            kind: ``true`` or ``false``.

        Returns:
            The median, or None if no alert of that kind has a rate.
        """
        rates = [c.rate for c in cases if c.kind == kind and c.rate is not None]
        return round(statistics.median(rates), 1) if rates else None

    return {
        "watch": len(cases),
        "no_rate": sum(1 for c in cases if c.rate is None),
        "true": sum(1 for c in cases if c.kind == TRUE),
        "false": sum(1 for c in cases if c.kind == FALSE),
        "median_rate_true": median(TRUE),
        "median_rate_false": median(FALSE),
    }


def choose(populations: list[dict], gate: dict) -> float | None:
    """The threshold the decision rule picks.

    Args:
        populations: One entry per population, each with ``rows`` from
            ``threshold_row`` (the reference row first).
        gate: The experiment file's ``[gate.sparse_tag]`` table.

    Returns:
        The highest threshold at which every population, on its own, has
        at most ``max_true_marked`` true alerts on ``found`` birds newly
        marked; None if none does.
    """
    passing = [
        threshold
        for threshold in gate["thresholds_per_day"]
        if all(
            row["newly_marked_true_found"] <= gate["max_true_marked"]
            for entry in populations
            for row in entry["rows"]
            if row["threshold_per_day"] == threshold
        )
    ]
    return max(passing) if passing else None


def _interval(bounds: list[float] | None) -> str:
    """A by-bird interval for a table cell.

    Args:
        bounds: Lower and upper bound, or None.

    Returns:
        The interval as text, or a dash.
    """
    return "-" if bounds is None else f"{bounds[0]:.3f}-{bounds[1]:.3f}"


def markdown(report: dict) -> str:
    """The sparse-tag report.

    Args:
        report: As ``scripts/sparse_gate.py`` writes it: ``scenario``,
            ``gate``, ``populations`` (each with ``title``, ``summary`` and
            ``rows``) and ``choice``.

    Returns:
        The report, as Markdown.
    """
    gate = report["gate"]
    choice = report["choice"]
    verdict = (
        f"**Chosen threshold: {choice:g} fixes a day.**"
        if choice is not None
        else "**No threshold meets the rule: no sparse-tag mark is added.**"
    )
    lines = [
        "# Sparse-tag mark (step 3.1 (f))",
        "",
        "Generated by `scripts/sparse_gate.py` (`make sparse-gate`); do not edit.",
        "",
        "Stork tuning populations only, each on its own, from the "
        f"`{report['scenario']}` replay. The rule is in `config/experiment.toml`",
        "under `[gate.sparse_tag]` and was written before this was first run.",
        f"The signal is the tag's fixes per day over the {gate['baseline_days']} days",
        "before the still run began (from the bird's first fix if later; no value",
        f"under {gate['min_baseline_days']} tracked days). True and false use the labels,",
        "on birds labelled dead or alive only.",
        "",
        verdict,
        "",
        "## Watch alerts",
        "",
        "| Population | Watch alerts | No rate | True | False "
        "| Median rate, true | Median rate, false |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in report["populations"]:
        s = entry["summary"]
        lines.append(
            f"| {entry['title']} | {s['watch']} | {s['no_rate']} | {s['true']} "
            f"| {s['false']} | {s['median_rate_true']} | {s['median_rate_false']} |"
        )
    lines += [
        "",
        "## Each threshold",
        "",
        "*Newly marked* leaves out alerts already marked `natal_nest`. *Load* is",
        "watch alerts with neither mark, per animal-month, with a 95% interval",
        "resampling whole birds. *Deaths only marked* are dead birds whose every",
        "true alert carries a mark: the cost of ignoring marked alerts.",
        "",
        "| Population | Fixes a day under | Newly marked | True (found) | False "
        "| Load | Load, by bird | Deaths only marked (of alerted) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in report["populations"]:
        for row in entry["rows"]:
            threshold = row["threshold_per_day"]
            lines.append(
                f"| {entry['title']} | {'none' if threshold is None else f'{threshold:g}'} "
                f"| {row['newly_marked']} | {row['newly_marked_true']} "
                f"({row['newly_marked_true_found']}) | {row['newly_marked_false']} "
                f"| {row['load_unmarked']} | {_interval(row['load_unmarked_by_bird'])} "
                f"| {row['deaths_only_marked']} ({row['deaths_alerted']}) |"
            )
    return "\n".join(lines) + "\n"


def figure(report: dict, path) -> None:
    """Plot unmarked load and newly marked true alerts against the threshold.

    Args:
        report: As for ``markdown``.
        path: Where to save the PNG.
    """
    # pylint: disable=import-outside-toplevel
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot

    fig, (load_ax, true_ax) = pyplot.subplots(1, 2, figsize=(10, 4))
    for entry, style in zip(report["populations"], ("-o", "--s")):
        rows = [r for r in entry["rows"] if r["threshold_per_day"] is not None]
        xs = [r["threshold_per_day"] for r in rows]
        load_ax.plot(
            xs, [r["load_unmarked"] for r in rows], style, label=entry["title"]
        )
        true_ax.plot(
            xs,
            [r["newly_marked_true_found"] for r in rows],
            style,
            label=entry["title"],
        )
    load_ax.set(
        xlabel="Mark tags fixing under (fixes a day)",
        ylabel="Unmarked watch alerts per animal-month",
        title="Load left unmarked",
    )
    true_ax.axhline(report["gate"]["max_true_marked"], color="grey", linestyle=":")
    true_ax.set(
        xlabel="Mark tags fixing under (fixes a day)",
        ylabel="True alerts on found birds, newly marked",
        title="Carcass alerts marked (rule limit dotted)",
    )
    for ax in (load_ax, true_ax):
        ax.legend()
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    pyplot.close(fig)
