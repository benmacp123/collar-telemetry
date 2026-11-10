"""Tables and figures from evaluation results.

Kept apart from ``telemetry.analysis.evaluation`` so the scoring has no plotting
dependency, and from the detection core, which the Lambda handlers load.
"""

from pathlib import Path

from telemetry.analysis.evaluation import TAG_EVENT
from telemetry.analysis.sweep import (
    CHOSEN_ON,
    WATCH_FIELDS,
    meets_chosen_on,
    species_choice,
    species_rows,
)
from telemetry.analysis.experiment import (
    BIRDS,
    CLEAR_HOURS,
    LOAD,
    METRIC_NAMES,
    RATE_AT_MARK,
    WEEK_DAYS,
    WILSON_LOWER,
    Target,
    experiment,
)

SCENARIO_ORDER = ("ideal", "gsm", "satellite_daily", "satellite_2day")
SCENARIO_LABELS = {
    "ideal": "Ideal",
    "gsm": "GSM",
    "satellite_daily": "Satellite, daily",
    "satellite_2day": "Satellite, 2-day",
}
DETECTORS = ("mortality", "movement", "gap", "geofence")
SYNTHETIC_GROUPS = ("pooled", "reporting", "sparse")


def _cell(value, digits: int = 2) -> str:
    """A table cell for a number that may be missing.

    Args:
        value: A number or None.
        digits: Decimal places for floats.

    Returns:
        str: The formatted number, or an en dash.
    """
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _share(value) -> str:
    """A share as a percentage cell.

    Args:
        value: A share between 0 and 1, or None.

    Returns:
        str: The percentage, or an en dash.
    """
    return "–" if value is None else f"{value:.0%}"


def _precision_cell(value) -> str:
    """A precision as a percentage cell, to one decimal place.

    Args:
        value: A share between 0 and 1, or None.

    Returns:
        str: The percentage, or an en dash.
    """
    return "–" if value is None else f"{value:.1%}"


def _interval_cell(bounds) -> str:
    """A 95% interval as a percentage range, to one decimal place.

    Args:
        bounds: [lower, upper] shares, or None (also when a report predates
            intervals).

    Returns:
        str: For example "1.4-6.6%", or an en dash.
    """
    if bounds is None:
        return "–"
    low, high = bounds
    return f"{low * 100:.1f}-{high:.1%}"


def _precision_with_intervals(scored: dict | None) -> str:
    """A precision with its Wilson and bootstrap intervals in one cell.

    Args:
        scored: One detector's precision record, or None.

    Returns:
        str: For example "3.1% [1.4-6.6%; by bird 1.0-8.1%]", or the bare
        precision when the record has no intervals.
    """
    if scored is None:
        return "–"
    value = _precision_cell(scored["precision"])
    if scored.get("wilson") is None:
        return value
    return (
        f"{value} [{_interval_cell(scored['wilson'])}; "
        f"by bird {_interval_cell(scored.get('bootstrap'))}]"
    )


def look_markdown(report: dict, day: str, commit: str, why: str) -> str:
    """One held-out look as an entry for ``results/LOOKS.md``.

    Args:
        report: The vulture scoring set's evaluation report.
        day: The look's date, ISO format.
        commit: The commit scored, noting any uncommitted changes.
        why: What changed since the last look, in the scorer's words.

    Returns:
        str: A level-two heading, the reason and one row of headline
        figures per scenario, ending in a newline.
    """
    lines = [
        f"## {day}, {commit}",
        "",
        why,
        "",
        "| Scenario | Mortality true + tag event / false "
        "| Mortality precision [Wilson 95%; by bird 95%] | Ceiling "
        "| False mortality per animal-month | Carcasses flagged by the mark "
        "| Potential death true / false | Potential death precision |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        result = report["scenarios"][name]
        mortality = result["precision"]["mortality"]
        potential = result["precision"]["potential_death"]
        carcasses = result["mortality"]
        rate = carcasses["rate_at_mark"]
        flagged = "–" if rate is None else str(round(rate * carcasses["deaths"]))
        lines.append(
            f"| {SCENARIO_LABELS[name]} "
            f"| {mortality['true']} + {mortality.get(TAG_EVENT, 0)} "
            f"/ {mortality['false']} "
            f"| {_precision_with_intervals(mortality)} "
            f"| {_precision_cell(mortality.get('ceiling'))} "
            f"| {_cell(result['false_mortality']['per_animal_month'], 3)} "
            f"| {flagged} of {carcasses['deaths']} "
            f"| {potential['true']} / {potential['false'] + potential.get(TAG_EVENT, 0)} "
            f"| {_precision_cell(potential['precision'])} |"
        )
    return "\n".join(lines) + "\n"


def markdown(reports: list[dict]) -> str:
    """The evaluation tables as Markdown.

    Args:
        reports: Evaluation reports as written by ``scripts/evaluate.py``.

    Returns:
        str: One section per study and set, synthetic variants after the
        real studies.
    """
    lines = [
        "# Evaluation",
        "",
        "Generated by `make evaluate` from the replay runner's incidents;",
        "do not edit by hand. Definitions are in `src/telemetry/analysis/evaluation.py`.",
        "Each setting's source and label (observed, literature or provisional) "
        "are in `docs/ASSUMPTIONS.md`.",
        "The vulture scoring set's figures come from the last `make score`, "
        "not from this run; each scoring is logged in `results/LOOKS.md`.",
        "",
    ]
    for report in reports:
        if report.get("synthetic"):
            lines += _synthetic_section(report)
        else:
            lines += _section(report)
    return "\n".join(lines).rstrip() + "\n"


def _synthetic_section(report: dict) -> list[str]:
    """Markdown for one synthetic variant: its deaths only.

    Args:
        report: One synthetic variant's evaluation report.

    Returns:
        list[str]: The section's lines.
    """
    scenarios = report["scenarios"]
    first = scenarios[SCENARIO_ORDER[0]]["synthetic"]
    pooled = first["pooled"]
    lines = [
        f"## {report['title']}",
        "",
        f"{pooled['deaths']} synthetic deaths (seed {report['seed']}), not "
        "observed ones: each real deployment dies once as a reporting and "
        "once as a sparse carcass, at the same time (`telemetry.sim.synthetic`; "
        "injected deaths in `results/replay/<variant>/deaths.json`). Only "
        "deaths are scored here; load and false alarms are in the real "
        f"study's section. {pooled['carcass']} of {pooled['deaths']} are long "
        f"enough to count as carcass deaths. Reference mark {report['mark_hours']} h "
        f"({report['mark_basis']}).",
        "",
        "Delays run from the computed death start, as for real deaths, and "
        "in brackets from the injected death time.",
        "",
        "| Scenario | Carcass | Deaths | Mortality detected | Early | By mark "
        "| Median delay (h) | Potential death detected | By mark | Any alert by mark |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        for group in SYNTHETIC_GROUPS:
            result = scenarios[name]["synthetic"][group]
            mortality, potential = result["mortality"], result["potential_death"]
            first = result["first_alert"]
            lines.append(
                f"| {SCENARIO_LABELS[name]} | {group.capitalize()} | "
                f"{result['deaths']} | {mortality['detected']} | "
                f"{mortality['early']} | {_share(mortality['rate_at_mark'])} "
                f"({_share(mortality['rate_at_mark_injected'])}) | "
                f"{_cell(mortality['median_delay_hours'], 1)} "
                f"({_cell(mortality['median_delay_hours_injected'], 1)}) | "
                f"{potential['detected']} | {_share(potential['rate_at_mark'])} "
                f"({_share(potential['rate_at_mark_injected'])}) | "
                f"{_share(first['rate_at_mark'])} "
                f"({_share(first['rate_at_mark_injected'])}) |"
            )
    offset = pooled["death_start_offset_hours"]
    lines += [
        "",
        "Against the injected death time, the computed death start is exact "
        f"for {offset['exact']}, earlier for {offset['earlier']} (the animal "
        f"was already still) and later for {offset['later']}; range "
        f"{_cell(offset['min'], 1)} to {_cell(offset['max'], 1)} h. A later "
        "start comes from one carcass fix scattered beyond the 100 m radius, "
        "which moves it to after that fix; an incident open since the death "
        "then counts as early, with no delay.",
    ]
    return lines + [""]


def _section(report: dict) -> list[str]:
    """Markdown for one study and set.

    Args:
        report: One evaluation report.

    Returns:
        list[str]: The section's lines.
    """
    scenarios = report["scenarios"]
    first = scenarios[SCENARIO_ORDER[0]]
    labels = ", ".join(f"{n} {label}" for label, n in first["labels"].items())
    mark = report["mark_hours"]
    lines = [
        f"## {report['title']} ({report['set']} set)",
        "",
        f"{first['deployments']} deployments ({labels}); "
        f"{first['animal_months']} animal-months. Reference mark {mark} h "
        f"({report['mark_basis']}).",
        "",
        "### Operator load (incidents per animal-month)",
        "",
        "*Gap, late upload* counts gap alerts resolved by a fix taken before "
        "the alert: the collar was working but its upload was late. They are "
        "load the operator sees, caused by upload latency, not false alarms "
        "about the animal; the gap threshold is not tuned on them.",
        "",
        "| Scenario | Mortality | False mortality | Movement | Gap "
        "| Gap, late upload | Gap resolved late | Geofence |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        result = scenarios[name]
        load = result["load"]

        def rate(detector, load=load):
            """Rate for one detector, or a dash if it raised nothing."""
            return _cell(load.get(detector, {}).get("per_animal_month"))

        gap = load.get("gap", {})
        late = gap["late_fix"] / gap["incidents"] if gap.get("incidents") else None
        lines.append(
            f"| {SCENARIO_LABELS[name]} | {rate('mortality')} | "
            f"{_cell(result['false_mortality']['per_animal_month'])} | "
            f"{rate('movement')} | {rate('gap')} | "
            f"{_cell(gap.get('late_fix_per_animal_month'))} | {_share(late)} | "
            f"{rate('geofence')} |"
        )

    lines += [
        "",
        "### Deaths",
        "",
        "Carcass deaths (final stationary period at least the mortality "
        "window) are scored on the mortality detector; the rest on the gap "
        "detector, from the last fix. *Any alert* scores carcass deaths on "
        "the first incident of any kind (mortality, potential death, or a gap "
        "opened after the death start), which is what the operator sees "
        "first.",
        "",
        "| Scenario | Carcass deaths | Detected | By mark | By mark (200 m) "
        "| Any alert by mark | Other deaths | Gap median delay (h) "
        "| Both detectors |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        result = scenarios[name]
        mortality = result["mortality"]
        gap = result["gap_on_deaths"]
        lines.append(
            f"| {SCENARIO_LABELS[name]} | {mortality['deaths']} | "
            f"{mortality['detected']} | {_share(mortality['rate_at_mark'])} | "
            f"{_share(mortality['rate_at_mark_200m'])} | "
            f"{_share(result['first_alert']['rate_at_mark'])} | {gap['deaths']} "
            f"({gap['detected']} flagged) | {_cell(gap['median_delay_hours'], 1)} | "
            f"{result['both_detectors']} |"
        )

    lines += [
        "",
        "### Priority alerts",
        "",
        "`potential_death` is raised while a mortality and a gap incident are "
        "both open. Its precision is the share of incidents on real deaths "
        "(ambiguous tracks left out; tag events count as wrong). Mortality "
        "precision also credits tag events.",
        "",
        "| Scenario | Potential death per animal-month | Precision | "
        "Mortality precision | Carcass deaths flagged | By mark |",
        "|---|---|---|---|---|---|",
    ]
    for name in SCENARIO_ORDER:
        result = scenarios[name]
        potential = result["potential_death"]
        rate = result["load"].get("potential_death", {}).get("per_animal_month")
        lines.append(
            f"| {SCENARIO_LABELS[name]} | {_cell(rate)} | "
            f"{_share(result['precision']['potential_death']['precision'])} | "
            f"{_share(result['precision']['mortality']['precision'])} | "
            f"{potential['detected']} of {potential['deaths']} | "
            f"{_share(potential['rate_at_mark'])} |"
        )

    lines += _precision_lines(scenarios, report.get("study"), report.get("set"))
    lines += _target_lines(report)
    lines += _false_alert_lines(first)
    lines += _tag_event_lines(first)

    geofence = first.get("geofence")
    if geofence:
        lines += [
            "",
            "### Geofence",
            "",
            f"Exit fence on {geofence['fence']} (OpenStreetMap boundary, 100 m "
            "edge band, 2 fixes to confirm). There is no ground truth for "
            "crossings, so this reports volume and how long animals stayed out. "
            "Crossings do not depend on upload timing.",
            "",
            "| Scenario | Alerts per animal-month | Alerts | Animals | "
            "Median hours outside | Under 6 h | Exits by nearest edge |",
            "|---|---|---|---|---|---|---|",
        ]
        for name in SCENARIO_ORDER:
            fence = scenarios[name]["geofence"]
            edges = ", ".join(f"{e} {n}" for e, n in fence["exits_by_edge"].items())
            lines.append(
                f"| {SCENARIO_LABELS[name]} | {_cell(fence['per_animal_month'])} | "
                f"{fence['incidents']} | {fence['deployments']} | "
                f"{_cell(fence['median_hours_outside'], 1)} | "
                f"{_share(fence['short_share'])} | {edges or '–'} |"
            )

    ambiguous = first["ambiguous"]
    if ambiguous:
        lines += [
            "",
            "### Possible unrecorded deaths",
            "",
            "Unplanned ends that finish stationary; not counted as false "
            "alarms. Mortality delay under ideal arrival.",
            "",
            "| Deployment | Stationary (h) | Mortality delay (h) |",
            "|---|---|---|",
        ]
        for track in ambiguous:
            lines.append(
                f"| {track['deployment_id']} | {_cell(track['still_hours'], 1)} | "
                f"{_cell(track['mortality_delay_hours'], 1)} |"
            )
    return lines + [""]


PRECISION_ROWS = (
    ("mortality", "Mortality"),
    ("potential_death", "Potential death"),
    ("gap", "Gap only (baseline)"),
)


def _precision_target(study: str | None, name: str | None, detector: str) -> str:
    """The precision target beside one detector's precision.

    Args:
        study: Study slug.
        name: The set's name.
        detector: The detector.

    Returns:
        str: The target on its Wilson lower bound, or "none" if the detector
        has none or the set is not one targets apply to.
    """
    settings = experiment()
    if settings.set_kind(study, name) is None:
        return "none"
    for target in settings.targets_for(detector):
        if target.metric == WILSON_LOWER:
            return f"lower bound {target.describe()}"
    return "none"


def _precision_lines(
    scenarios: dict, study: str | None = None, name: str | None = None
) -> list[str]:
    """Precision against the ceiling, baselines and target, per scenario.

    Args:
        scenarios: One report's results by scenario.
        study: Study slug, to find the precision targets.
        name: The set's name.

    Returns:
        list[str]: The section's lines, or none if the report predates
        intervals (a held-out set last scored before them).
    """
    if "random_precision" not in scenarios[SCENARIO_ORDER[0]]:
        return []
    lines = [
        "",
        "### Precision against the ceiling and baselines",
        "",
        "Precision is correct over *judged* incidents (ambiguous tracks left "
        "out), whereas load counts every incident. A tag event (dropped, "
        "stuck or failing tag; grounded bird) is correct for mortality and "
        "the gap baseline, whose alerts it fits, and wrong for potential "
        "death, which claims a death. *Death only* is true over judged. "
        "*By bird* resamples whole deployments, so a bird with many false "
        "alerts counts once; it is the interval to quote. The *ceiling* is "
        "the precision of a detector firing once on each case (carcass "
        "deaths; every death for the gap baseline) at the observed false "
        "count; precision passes it only when one death raises more than "
        "one true alert. *Gap only* scores gap incidents the same way: the rule "
        "stillness has to beat. *Random* alerts at uniformly random moments "
        "score the share of judged time after a death start, or after a "
        "death start or tag event for detectors credited with tag events. "
        "The *precision target* is on the Wilson lower bound; a detector "
        "judged on other measures shows none.",
        "",
        "| Scenario | Alert | True + tag event / judged (ambiguous) | Precision "
        "| Death only | Wilson 95% | By bird 95% | Cases | Ceiling "
        "| Precision target |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for scenario in SCENARIO_ORDER:
        result = scenarios[scenario]
        for detector, label in PRECISION_ROWS:
            scored = result["precision"][detector]
            lines.append(
                f"| {SCENARIO_LABELS[scenario]} | {label} | {scored['true']} + "
                f"{scored.get(TAG_EVENT, 0)} / "
                f"{scored['judged']} ({scored['ambiguous']}) | "
                f"{_precision_cell(scored['precision'])} | "
                f"{_precision_cell(scored.get('death_precision', scored['precision']))} | "
                f"{_interval_cell(scored['wilson'])} | "
                f"{_interval_cell(scored['bootstrap'])} | {scored['cases']} | "
                f"{_precision_cell(scored['ceiling'])} | "
                f"{_precision_target(study, name, detector)} |"
            )
    first = scenarios[SCENARIO_ORDER[0]]
    random = first["random_precision"]
    tags = first.get("random_precision_tags", random)
    lines += [
        "",
        f"Random baseline (any scenario): {_share_fine(random)} for deaths; "
        f"{_share_fine(tags)} also crediting tag events. The second is weighted "
        "by time, so one tag stuck for years dominates it, however few fixes "
        "it sent.",
    ]
    return lines


def _arithmetic_note() -> str:
    """How far false alerts must fall for the precision targets to be possible.

    Returns:
        str: One sentence per precision in the experiment file.
    """
    settings = experiment()
    today = settings.false_per_animal_month
    parts = []
    for precision in settings.precisions:
        allowed = settings.false_rate_allowed(precision)
        parts.append(
            f"{precision:.0%} precision allows at most {allowed:.3f}, "
            f"{today / allowed:.0f} times fewer than today"
        )
    return (
        f"At the seen held-out base rate (one carcass per "
        f"{settings.animal_months_per_carcass:g} animal-months, {today} false "
        f"alerts per animal-month): {'; '.join(parts)}. About 5 true alerts "
        "need 33% measured precision for a Wilson lower bound above 15%."
    )


def _measured(target: Target, result: dict) -> float | None:
    """What one scenario's evaluation result measured for a target.

    Args:
        target: The target.
        result: One scenario's results.

    Returns:
        float | None: The value in the metric's own unit; None if the result
        does not hold it, such as a held-out set last scored before the
        measure existed, or a cue not yet built.
    """
    if target.metric == LOAD:
        # An alert that never fired has no load entry: its load is zero.
        return result["load"].get(target.alert, {}).get("per_animal_month", 0.0)
    if target.metric == CLEAR_HOURS:
        return result.get("mortality_clear", {}).get("median_hours")
    if target.metric == RATE_AT_MARK:
        return result[target.alert]["rate_at_mark"]
    if target.metric == WILSON_LOWER:
        bounds = result["precision"][target.alert]["wilson"]
        return None if bounds is None else bounds[0]
    return None


def _measure_cell(target: Target, value: float | None) -> str:
    """A measured value in the target's unit.

    Args:
        target: The target.
        value: The value, or None.

    Returns:
        str: The formatted value, or an en dash.
    """
    if value is None:
        return "–"
    if target.metric == LOAD:
        return f"{value:.3f}"
    if target.metric == CLEAR_HOURS:
        return f"{value:.1f} h"
    return _precision_cell(value)


def _target_lines(report: dict) -> list[str]:
    """One set's measured values against every target.

    Args:
        report: One evaluation report.

    Returns:
        list[str]: The section's lines, or none if no target applies to
        this set (the mammals) or the study's scenario is not named.
    """
    settings = experiment()
    study, name = report.get("study"), report.get("set")
    kind = settings.set_kind(study, name)
    scenario = settings.scenario(study)
    if kind is None or scenario is None:
        return []
    result = report["scenarios"][scenario]
    lines = [
        "",
        "### Against the targets",
        "",
        "Fixed in advance in `config/experiment.toml`. Judged under "
        f"{SCENARIO_LABELS[scenario].lower()} uploads only, this study's real "
        f"pattern. This is a *{kind}* set, and a target is judged only on the "
        "kinds of set it names, so a value here may meet a limit without "
        f"being judged. The *ceiling* is the alert's, at the same scenario. "
        f"Load is per animal-month: {WEEK_DAYS} days for {BIRDS} birds is "
        f"{WEEK_DAYS * BIRDS / (settings.animal_month.total_seconds() / 86400):.2f} "
        "animal-months.",
        "",
        _arithmetic_note(),
        "",
        "| Tier | Metric | Target | Measured | Ceiling | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for target in settings.targets:
        value = (
            None
            if target.alert not in result["precision"]
            else (_measured(target, result))
        )
        scored = result["precision"].get(target.alert, {})
        lines.append(
            f"| {target.tier} | {METRIC_NAMES[target.metric]} | "
            f"{target.describe()} | {_measure_cell(target, value)} | "
            f"{_precision_cell(scored.get('ceiling'))} | "
            f"{target.verdict(value, kind)} |"
        )
    return lines


def _tag_event_lines(first: dict) -> list[str]:
    """The labelled tag events, if the set has any.

    Args:
        first: One scenario's results; the labels are the same in all.

    Returns:
        list[str]: The section's lines, or none without tag events.
    """
    tag_events = first.get("tag_events")
    if not tag_events:
        return []
    lines = [
        "",
        "### Tag events",
        "",
        "Evidence and the rule for each start time are in `data/labels.csv` "
        "and `data/SOURCES.md`.",
        "",
        "| Deployment | Event from | Mortality incidents credited |",
        "|---|---|---|",
    ]
    lines += [
        f"| {t['deployment_id']} | {t['event_from'][:16]} | "
        f"{t['mortality_incidents']} |"
        for t in tag_events
    ]
    return lines


def _share_fine(value) -> str:
    """A small share as a percentage, to two decimal places.

    Args:
        value: A share between 0 and 1, or None.

    Returns:
        str: The percentage, or an en dash.
    """
    return "–" if value is None else f"{value:.2%}"


def _false_alert_lines(result: dict) -> list[str]:
    """False mortality alerts by taxon and by deployment.

    Args:
        result: One scenario's results; false mortality alerts do not
            depend on the arrival scenario.

    Returns:
        list[str]: The section's lines, or none if the report predates
        the breakdown.
    """
    by = result.get("false_mortality_by")
    if by is None:
        return []
    lines = [
        "",
        "### False mortality alerts by species and bird",
        "",
        "Under ideal arrival. Birds with no false alert are left out of the "
        "second table.",
        "",
        "| Taxon | Animal-months | True | False | False per animal-month |",
        "|---|---|---|---|---|",
    ]
    lines += _false_alert_rows(by["by_taxon"])
    lines += [
        "",
        "| Deployment | Animal-months | True | False | False per animal-month |",
        "|---|---|---|---|---|",
    ]
    return lines + _false_alert_rows(by["by_deployment"])


def _false_alert_rows(rows: list[dict]) -> list[str]:
    """Table rows for ``_false_alert_lines``.

    Args:
        rows: Rows from ``evaluation.false_alerts``.

    Returns:
        list[str]: One Markdown row each.
    """
    return [
        f"| {row['name']} | {_cell(row['animal_months'], 1)} | {row['true']} | "
        f"{row['false']} | {_cell(row['false_per_animal_month'])} |"
        for row in rows
    ]


def write_markdown(reports: list[dict], path: Path) -> None:
    """Write the evaluation tables.

    Args:
        reports: Evaluation reports.
        path: Output Markdown file.
    """
    path.write_text(markdown(reports), encoding="utf-8")


def detection_curve(
    delays: list[float | None], horizon: float
) -> tuple[list[float], list[float]]:
    """Step-curve points for the share of deaths flagged by each deadline.

    Args:
        delays: Delay in hours per death, None where missed.
        horizon: Last deadline to draw, in hours.

    Returns:
        tuple[list[float], list[float]]: Deadlines and shares, starting at
        (0, share flagged at once) and ending at ``horizon``.
    """
    hits = sorted(d for d in delays if d is not None and d <= horizon)
    xs, ys = [0.0], [0.0]
    for i, delay in enumerate(hits, start=1):
        xs.append(delay)
        ys.append(i / len(delays))
    xs.append(horizon)
    ys.append(ys[-1])
    return xs, ys


def write_figures(reports: list[dict], directory: Path) -> None:
    """Write the evaluation figures as PNG.

    One delay-curve figure per study and set that has deaths, and one
    operator-load figure covering every real study (synthetic variants
    repeat their real study's load).

    Args:
        reports: Evaluation reports.
        directory: Output directory, created if needed.
    """
    # Imported here so scoring and the tables work without matplotlib.
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    directory.mkdir(parents=True, exist_ok=True)
    pyplot.rcParams.update(STYLE)
    for report in reports:
        if any(r["deaths"] for r in report["scenarios"].values()):
            figure = _delay_figure(pyplot, report)
            _save(figure, directory / f"{report['study']}-{report['set']}-delay.png")
            pyplot.close(figure)
    figure = _load_figure(pyplot, [r for r in reports if not r.get("synthetic")])
    _save(figure, directory / "load.png")
    pyplot.close(figure)


# Reference palette (dataviz skill, light mode): categorical slots in fixed
# order, validated for adjacent-pair colour-vision separation. Slots 3-4 sit
# below 3:1 contrast, so scenarios also differ by line style and every
# figure has its table in EVALUATION.md.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
LINE_STYLES = ("-", "--", ":", "-.")
STYLE = {
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_SECONDARY,
    "axes.titlecolor": INK,
    "axes.titlesize": 11,
    "axes.titlelocation": "left",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "xtick.color": INK_SECONDARY,
    "ytick.color": INK_SECONDARY,
    "font.size": 9,
    "legend.frameon": False,
    "legend.labelcolor": INK,
}


def _delay_figure(pyplot, report: dict):
    """Detection-rate curves for one study and set.

    Args:
        pyplot: ``matplotlib.pyplot``.
        report: One evaluation report.

    Returns:
        matplotlib.figure.Figure: Mortality detector on carcass deaths and
        gap detector on the other deaths, side by side; for a synthetic
        variant, the mortality detector on each carcass regime.
    """
    mark = report["mark_hours"]
    horizon = 2 * mark if mark else 200.0
    panels = []
    first = report["scenarios"][SCENARIO_ORDER[0]]
    carcass = [d for d in first["deaths"] if d["carcass"]]
    other = [d for d in first["deaths"] if not d["carcass"]]
    if report.get("synthetic"):
        for regime in SYNTHETIC_GROUPS[1:]:
            count = sum(1 for d in carcass if d["regime"] == regime)
            panels.append(
                (
                    f"{regime.capitalize()} carcasses, mortality detector (n={count})",
                    "Hours from death start",
                    True,
                    lambda r, regime=regime: [
                        d["mortality_delay_hours"]
                        for d in r["deaths"]
                        if d["carcass"] and d["regime"] == regime
                    ],
                )
            )
        carcass, other = [], []
    if carcass:
        panels.append(
            (
                f"Carcass deaths, mortality detector (n={len(carcass)})",
                "Hours from death start",
                True,
                lambda r: [
                    d["mortality_delay_hours"] for d in r["deaths"] if d["carcass"]
                ],
            )
        )
    if other:
        panels.append(
            (
                f"Other deaths, gap detector (n={len(other)})",
                "Hours from last fix",
                False,
                lambda r: [
                    d["gap_delay_hours"] for d in r["deaths"] if not d["carcass"]
                ],
            )
        )
    figure, axes = pyplot.subplots(
        1, len(panels), figsize=(4.2 * len(panels) + 0.6, 3.4), squeeze=False
    )
    # The mark is measured from the death start, so it belongs on the
    # mortality panel only; the gap panel counts from the last fix.
    for ax, (title, xlabel, show_mark, pick) in zip(axes[0], panels):
        for index, name in enumerate(SCENARIO_ORDER):
            xs, ys = detection_curve(pick(report["scenarios"][name]), horizon)
            ax.step(
                xs,
                ys,
                where="post",
                color=SERIES[index],
                linestyle=LINE_STYLES[index],
                linewidth=2,
                label=SCENARIO_LABELS[name],
            )
        if show_mark:
            ax.axvline(mark, color=INK_SECONDARY, linewidth=1, linestyle=(0, (2, 2)))
            ax.annotate(
                f"mark {mark:g} h",
                (mark, 0.02),
                xytext=(4, 0),
                textcoords="offset points",
                color=INK_SECONDARY,
            )
        ax.set_xlim(0, horizon)
        ax.set_ylim(0, 1.04)
        ax.yaxis.set_major_formatter(matplotlib_percent())  # share of deaths flagged
        ax.set_title(title)
        ax.set_xlabel(xlabel)
    axes[0][0].set_ylabel("Share of deaths flagged")
    axes[0][-1].legend(loc="lower right")
    title = report["title"]
    figure.suptitle(
        title if report.get("synthetic") else f"{title} ({report['set']} set)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    figure.tight_layout()
    return figure


def _load_figure(pyplot, reports: list[dict]):
    """Operator load by detector and scenario, one panel per report.

    Args:
        pyplot: ``matplotlib.pyplot``.
        reports: Evaluation reports.

    Returns:
        matplotlib.figure.Figure: Stacked horizontal bars of incidents per
        animal-month, segments separated by a surface-coloured gap.
    """
    figure, axes = pyplot.subplots(
        len(reports), 1, figsize=(7, 1.9 * len(reports) + 0.6), sharex=True
    )
    axes = axes if len(reports) > 1 else [axes]
    for ax, report in zip(axes, reports):
        names = list(reversed(SCENARIO_ORDER))
        left = [0.0] * len(names)
        for index, detector in enumerate(DETECTORS):
            widths = [
                report["scenarios"][n]["load"].get(detector, {}).get("per_animal_month")
                or 0.0
                for n in names
            ]
            ax.barh(
                [SCENARIO_LABELS[n] for n in names],
                widths,
                left=left,
                height=0.6,
                color=SERIES[index],
                edgecolor=SURFACE,
                linewidth=2,
                label=detector.capitalize(),
            )
            left = [a + b for a, b in zip(left, widths)]
        for y, total in enumerate(left):
            ax.annotate(
                f"{total:.1f}",
                (total, y),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                color=INK,
            )
        ax.grid(axis="y", visible=False)
        ax.set_title(f"{report['title']} ({report['set']} set)")
    axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, 1.45), ncol=3)
    axes[-1].set_xlabel("Incidents per animal-month")
    figure.suptitle(
        "Operator load by arrival scenario", x=0.01, ha="left", color=INK, fontsize=12
    )
    figure.tight_layout()
    return figure


def matplotlib_percent():
    """A tick formatter showing shares as percentages.

    Returns:
        matplotlib.ticker.PercentFormatter: Formatter for 0-1 values.
    """
    from matplotlib.ticker import (  # pylint: disable=import-outside-toplevel
        PercentFormatter,
    )

    return PercentFormatter(1.0, decimals=0)


def _save(figure, path: Path) -> None:
    """Save a figure as PNG with no build metadata, so reruns match.

    Args:
        figure: The figure.
        path: Output file.
    """
    figure.savefig(path, dpi=150, metadata={"Software": None})


def _sweep_measured(target: Target, row: dict) -> float | None:
    """What one sweep row measured for a watch target.

    Args:
        target: A target on the mortality alert.
        row: The sweep row.

    Returns:
        float | None: The value in the metric's own unit.
    """
    return row.get(WATCH_FIELDS[target.metric])


def _sweep_target_lines(report: dict, by_setting: dict) -> list[str]:
    """Every mortality setting against the watch targets.

    Args:
        report: The sweep report.
        by_setting: Sweep rows by (window, box), then by scenario.

    Returns:
        list[str]: The section's lines, or none if no target applies to the
        set swept or the study's scenario is not named.
    """
    settings = experiment()
    kind = settings.set_kind(report.get("study"), report.get("set"))
    scenario = settings.scenario(report.get("study"))
    if kind is None or scenario is None:
        return []
    watch = settings.targets_for("mortality")
    headers = " | ".join(f"{METRIC_NAMES[t.metric]} (target)" for t in watch)
    lines = [
        "",
        "### Mortality settings against the watch targets",
        "",
        f"Fixed in advance in `config/experiment.toml`; judged under "
        f"{SCENARIO_LABELS[scenario].lower()} uploads. Load is per animal-month. "
        f"The *ceiling* is at the same scenario. {_arithmetic_note()}",
        "",
        f"| Window (h) | Box (m) | {headers} | Ceiling | Verdict |",
        "|---|---|" + "---|" * (len(watch) + 2),
    ]
    for (window, box), scenarios in sorted(
        by_setting.items(), key=lambda kv: (kv[0][1], kv[0][0])
    ):
        row = scenarios[scenario]
        cells, missed = [], []
        for target in watch:
            value = _sweep_measured(target, row)
            cells.append(f"{_measure_cell(target, value)} ({target.limit_text()})")
            if target.verdict(value, kind) != "met":
                missed.append(METRIC_NAMES[target.metric].lower())
        verdict = f"missed: {', '.join(missed)}" if missed else "met"
        lines.append(
            f"| {window:g} | {box:g} | {' | '.join(cells)} | "
            f"{_precision_cell(row.get('mortality_ceiling'))} | {verdict} |"
        )
    return lines


def _carcasses_at_mark(scores: dict) -> str:
    """Carcass deaths flagged by the mark, as a count.

    Args:
        scores: A sweep row or one taxon's part of it.

    Returns:
        str: ``n of m``, or an en dash if there are no carcass deaths.
    """
    deaths, rate = scores["carcass_deaths"], scores["carcass_rate_at_mark"]
    if not deaths or rate is None:
        return "–"
    return f"{round(rate * deaths)} of {deaths}"


def _species_lines(report: dict) -> list[str]:
    """One species' window swept on its own, against the watch targets.

    Args:
        report: The sweep report.

    Returns:
        list[str]: The section's lines, or none if the sweep has no species
        rows or the study's scenario is not named.
    """
    settings = experiment()
    kind = settings.set_kind(report.get("study"), report.get("set"))
    scenario = settings.scenario(report.get("study"))
    pairs = species_rows(report["rows"], scenario) if scenario else []
    if kind is None or not pairs:
        return []
    taxon = settings.species_taxon
    watch = settings.targets_for("mortality")
    headers = " | ".join(f"{METRIC_NAMES[t.metric]} (target)" for t in watch)
    chosen_on = " and ".join(
        METRIC_NAMES[t.metric].lower() for t in watch if t.metric in CHOSEN_ON
    )
    others = sorted(set(pairs[0][1]["by_taxon"]) - {taxon})
    lines = [
        "",
        f"## *{taxon}* window on its own",
        "",
        f"Every other species keeps its own window ({', '.join(f'*{o}*' for o in others)}). "
        "Each deployment runs on its own, so a species' columns depend only "
        "on its own window. The whole-set columns are the ones the watch "
        f"targets judge, under {SCENARIO_LABELS[scenario].lower()} uploads. "
        "The rule, fixed in `config/experiment.toml` before this sweep was "
        f"first run: the shortest window meeting {chosen_on}. Carcasses "
        "flagged by the mark are reported, not chosen on: there are too few "
        "per species.",
        "",
        f"| Window (h) | {headers} | Meets {chosen_on} "
        f"| *{taxon}* load | *{taxon}* clear (h) | *{taxon}* false alerts "
        f"| *{taxon}* carcasses by the mark | Others' load | Others' clear (h) |",
        "|---|" + "---|" * (len(watch) + 7),
    ]
    for window, row in pairs:
        cells = [
            f"{_measure_cell(t, _sweep_measured(t, row))} ({t.limit_text()})"
            for t in watch
        ]
        own = row["by_taxon"][taxon]
        rest = [row["by_taxon"][o] for o in others]
        rest_months = sum(r["animal_months"] for r in rest)
        rest_load = (
            sum(r["mortality_per_animal_month"] * r["animal_months"] for r in rest)
            / rest_months
            if rest_months
            else None
        )
        # Medians cannot be pooled, so with several other species only
        # each one's own is meaningful; one other species is the usual case.
        rest_clear = (
            _cell(rest[0]["mortality_clear_median_hours"], 1) if len(rest) == 1 else "–"
        )
        lines.append(
            f"| {window:g} | {' | '.join(cells)} | "
            f"{'yes' if meets_chosen_on(row) else 'no'} | "
            f"{_cell(own['mortality_per_animal_month'], 3)} | "
            f"{_cell(own['mortality_clear_median_hours'], 1)} | "
            f"{own['mortality_false']} | {_carcasses_at_mark(own)} | "
            f"{_cell(rest_load, 3)} | {rest_clear} |"
        )
    choice = species_choice(report["rows"], scenario)
    lines += [
        "",
        (
            f"**Chosen by the rule: {choice:g} h.**"
            if choice is not None
            else f"**No window meets {chosen_on} together**, so by the rule "
            "the window stays at 36 h. No target is relaxed."
        ),
    ]
    return lines


def sweep_markdown(report: dict) -> str:
    """The threshold sweep as Markdown tables.

    Args:
        report: Sweep report as written by ``scripts/sweep.py``.

    Returns:
        str: One table for the mortality sweep and one for the gap sweep.
    """
    rows = report["rows"]
    lines = [
        "# Threshold sweep",
        "",
        "Generated by `make sweep`; do not edit by hand. Vulture tuning set "
        f"only ({report['deployments']} deployments starting before 2013); "
        "the scoring set was not replayed. Reference mark "
        f"{report['mark_hours']} h.",
        "",
        "## Mortality detector",
        "",
        "Gap settings at their defaults. False alarms do not depend on the "
        "arrival scenario; detection by the mark does, slightly.",
        "",
        "| Window (h) | Box (m) | False alarms per animal-month "
        "| Carcass deaths flagged | By mark, ideal | By mark, daily "
        "| By mark, 2-day | Slowest (h), 2-day |",
        "|---|---|---|---|---|---|---|---|",
    ]
    mortality = [r for r in rows if r["swept"] == "mortality"]
    by_setting: dict[tuple, dict] = {}
    for row in mortality:
        key = (row["mortality_window_hours"], row["mortality_box_m"])
        by_setting.setdefault(key, {})[row["scenario"]] = row
    for (window, box), scenarios in sorted(
        by_setting.items(), key=lambda kv: (kv[0][1], kv[0][0])
    ):
        ideal = scenarios["ideal"]
        lines.append(
            f"| {window:g} | {box:g} | "
            f"{_cell(ideal['false_mortality_per_animal_month'])} | "
            f"{ideal['carcass_detected']} of {ideal['carcass_deaths']} | "
            f"{_share(ideal['carcass_rate_at_mark'])} | "
            f"{_share(scenarios['satellite_daily']['carcass_rate_at_mark'])} | "
            f"{_share(scenarios['satellite_2day']['carcass_rate_at_mark'])} | "
            f"{_cell(scenarios['satellite_2day']['carcass_max_delay_hours'], 1)} |"
        )
    # Random alerts do not depend on the setting, so any row gives it.
    random = next(iter(by_setting.values()), {}).get("ideal", {})
    random_tags = random.get("random_precision_tags")
    random = random.get("random_precision")
    lines += [
        "",
        "### Mortality precision",
        "",
        "Ideal arrival. Correct (true plus tag events) over judged incidents "
        "(ambiguous tracks left out); *by bird* resamples whole deployments "
        "and is the interval to "
        "quote. The *ceiling* is a detector firing once on each carcass at "
        "the setting's false count. Potential death and gap-only precision "
        "at the same setting are beside it for comparison. Random alerts "
        f"score {_share_fine(random)} for deaths, {_share_fine(random_tags)} "
        "also crediting tag events.",
        "",
        "| Window (h) | Box (m) | True + tag event / judged | Precision "
        "| Death only | Wilson 95% "
        "| By bird 95% | Ceiling | Potential death | Potential death target "
        "| Gap only |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    escalated = _precision_target(
        report.get("study"), report.get("set"), "potential_death"
    )
    for (window, box), scenarios in sorted(
        by_setting.items(), key=lambda kv: (kv[0][1], kv[0][0])
    ):
        ideal = scenarios["ideal"]
        lines.append(
            f"| {window:g} | {box:g} | {ideal.get('mortality_true', '–')} + "
            f"{ideal.get('mortality_tag_event', '–')} / "
            f"{ideal.get('mortality_judged', '–')} | "
            f"{_precision_cell(ideal.get('mortality_precision'))} | "
            f"{_precision_cell(ideal.get('mortality_death_precision'))} | "
            f"{_interval_cell(ideal.get('mortality_wilson'))} | "
            f"{_interval_cell(ideal.get('mortality_bootstrap'))} | "
            f"{_precision_cell(ideal.get('mortality_ceiling'))} | "
            f"{_precision_cell(ideal.get('potential_death_precision'))} | "
            f"{escalated} | "
            f"{_precision_cell(ideal.get('gap_precision'))} |"
        )
    lines += _sweep_target_lines(report, by_setting)
    lines += _species_lines(report)
    lines += [
        "",
        "## Gap detector",
        "",
        "Silence allowed beyond the upload interval (ideal arrival has none). "
        "Mortality settings at their defaults. Delays are on deaths without "
        "a carcass period, from the last fix. Gap alerts are a baseline, so "
        "they have no target of their own.",
        "",
        "| Scenario | Margin (h) | Gap alerts per animal-month "
        "| Resolved late | Deaths flagged | Median delay (h) | Slowest (h) "
        "| Precision as a death signal | Ceiling | Target |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    gap = [r for r in rows if r["swept"] == "gap"]
    for name in SCENARIO_ORDER:
        for row in sorted(
            (r for r in gap if r["scenario"] == name),
            key=lambda r: r["upload_margin_hours"],
        ):
            lines.append(
                f"| {SCENARIO_LABELS[name]} | {row['upload_margin_hours']:g} | "
                f"{_cell(row['gap_per_animal_month'])} | "
                f"{_share(row['gap_late_fix_share'])} | "
                f"{row['other_deaths_detected']} of {row['other_deaths']} | "
                f"{_cell(row['other_deaths_median_gap_delay_hours'], 1)} | "
                f"{_cell(row['other_deaths_max_gap_delay_hours'], 1)} | "
                f"{_precision_cell(row.get('gap_precision'))} | "
                f"{_precision_cell(row.get('gap_ceiling'))} | none |"
            )
    return "\n".join(lines) + "\n"


def write_sweep(report: dict, markdown_path: Path, figures: Path) -> None:
    """Write the sweep tables and figure.

    Args:
        report: Sweep report.
        markdown_path: Output Markdown file.
        figures: Figure directory, created if needed.
    """
    markdown_path.write_text(sweep_markdown(report), encoding="utf-8")
    figures.mkdir(parents=True, exist_ok=True)
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    pyplot.rcParams.update(STYLE)
    figure = _sweep_figure(pyplot, report)
    _save(figure, figures / f"sweep-{report['study']}-{report['set']}.png")
    pyplot.close(figure)
    figure = _species_figure(pyplot, report)
    if figure is not None:
        _save(figure, figures / f"sweep-{report['study']}-{report['set']}-species.png")
        pyplot.close(figure)


def departure_markdown(report: dict) -> str:
    """The departure comparison as Markdown tables.

    Args:
        report: Report as written by ``scripts/departure.py``.

    Returns:
        str: One table for the vulture tuning set, then one per synthetic
        variant.
    """
    rows = report["rows"]
    settings = list(dict.fromkeys(r["setting"] for r in rows))

    def row(name: str, setting: str, scenario: str = "ideal") -> dict:
        """The row for one set, setting and scenario.

        Args:
            name: Set name.
            setting: Setting label.
            scenario: Scenario name.

        Returns:
            dict: The row.
        """
        return next(
            r
            for r in rows
            if r["set"] == name
            and r["setting"] == setting
            and r["scenario"] == scenario
        )

    def outcome(counts: dict) -> str:
        """Flapped, split and ended-resolved deaths as one cell.

        Args:
            counts: ``summarise_outcomes`` for one group.

        Returns:
            str: ``flapped / split / ended resolved`` of the deaths.
        """
        return (
            f"{counts['flapped']} / {counts['split']} / "
            f"{counts['ends_resolved']} of {counts['deaths']}"
        )

    sets = report["sets"]
    vultures = "vultures"
    lines = [
        "# How a still tag is judged to have moved",
        "",
        "Generated by `make departure`; do not edit by hand. Each row makes "
        "one change to the box-only detector (100 m box, two fixes to leave, "
        "48 h merge), except the radius rows. Death outcomes are *flapped / split / "
        'ended resolved*: deaths with a false "moving again" resolve taken '
        "back within the merge window, deaths raising more than one "
        "incident, and deaths whose last incident says the carcass moved. "
        "Outcomes and false-alert durations use evidence times, so they are "
        "shown under ideal arrival; detection by the mark is shown per "
        "scenario. Hours open are from opening to resolving, among resolved "
        "false alerts.",
        "",
        f"## Vulture tuning set ({sets[vultures]['deployments']} deployments, "
        f"mark {sets[vultures]['mark_hours']} h)",
        "",
        "| Setting | False alerts per animal-month | Never resolved "
        "| Median h open | p90 h open | Carcass deaths: flapped / split / "
        "ended resolved | By mark, ideal | By mark, daily | By mark, 2-day |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for setting in settings:
        ideal = row(vultures, setting)
        false = ideal["false_alarms"]
        lines.append(
            f"| {setting} | {_cell(ideal['false_mortality_per_animal_month'])} | "
            f"{false['never_resolved']} of {false['incidents']} | "
            f"{_cell(false['median_hours_open'], 1)} | "
            f"{_cell(false['p90_hours_open'], 1)} | "
            f"{outcome(ideal['mortality']['carcass'])} | "
            + " | ".join(
                _share(row(vultures, setting, s)["carcass"]["rate_at_mark"])
                for s in ("ideal", "satellite_daily", "satellite_2day")
            )
            + " |"
        )
    for name in sets:
        if name == vultures:
            continue
        lines += [
            "",
            f"## {name}, seed {report['tuning_seed']} "
            f"({sets[name]['deployments']} deployments, mark "
            f"{sets[name]['mark_hours']} h)",
            "",
            "Detection is from the injected death time. False alerts are "
            "those on the real track before the death.",
            "",
            "| Setting | Reporting: flapped / split / ended resolved "
            "| Sparse: flapped / split / ended resolved | Flaps "
            "| By mark, ideal | By mark, 2-day | False alerts | Median h open "
            "| p90 h open |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for setting in settings:
            ideal = row(name, setting)
            mortality = ideal["mortality"]

            lines.append(
                f"| {setting} | {outcome(mortality['reporting'])} | "
                f"{outcome(mortality['sparse'])} | "
                f"{mortality['reporting']['flaps'] + mortality['sparse']['flaps']} | "
                f"{_pooled_by_mark(row(name, setting)['detection'])} | "
                f"{_pooled_by_mark(row(name, setting, 'satellite_2day')['detection'])} | "
                f"{ideal['false_alarms']['incidents']} | "
                f"{_cell(ideal['false_alarms']['median_hours_open'], 1)} | "
                f"{_cell(ideal['false_alarms']['p90_hours_open'], 1)} |"
            )
    return "\n".join(lines) + "\n"


def _pooled_by_mark(detection: dict) -> str:
    """Synthetic deaths flagged by the mark, both regimes pooled.

    Args:
        detection: A variant row's ``detection``, by regime.

    Returns:
        str: The pooled share as a percentage.
    """
    deaths = sum(d["deaths"] for d in detection.values())
    hit = sum(d["rate_at_mark"] * d["deaths"] for d in detection.values())
    return _share(hit / deaths if deaths else None)


def write_departure(report: dict, markdown_path: Path) -> None:
    """Write the departure comparison's tables.

    Args:
        report: Report as written by ``scripts/departure.py``.
        markdown_path: Output Markdown file.
    """
    markdown_path.write_text(departure_markdown(report), encoding="utf-8")


def _species_figure(pyplot, report: dict):
    """The species window against each watch target, one panel per target.

    Args:
        pyplot: ``matplotlib.pyplot``.
        report: Sweep report.

    Returns:
        matplotlib.figure.Figure | None: Whole-set load, clear time and
        carcasses flagged by the mark against the swept species' window,
        each with its target as a dashed line and the species' own value
        beside the whole set's; None if the sweep has no species rows.
    """
    settings = experiment()
    scenario = settings.scenario(report.get("study"))
    pairs = species_rows(report["rows"], scenario) if scenario else []
    if not pairs:
        return None
    taxon = settings.species_taxon
    windows = [w for w, _ in pairs]
    watch = settings.targets_for("mortality")
    figure, axes = pyplot.subplots(1, len(watch), figsize=(13, 3.8))
    for ax, target in zip(axes, watch):
        field = WATCH_FIELDS[target.metric]
        series = (
            ("Whole tuning set", [row.get(field) for _, row in pairs]),
            (
                f"{taxon} only",
                [row["by_taxon"][taxon].get(field) for _, row in pairs],
            ),
        )
        for index, (label, ys) in enumerate(series):
            ax.plot(
                windows,
                [float("nan") if y is None else y for y in ys],
                color=SERIES[index],
                linestyle=LINE_STYLES[index],
                linewidth=2,
                marker="o",
                markersize=5,
                label=label,
            )
        ax.axhline(
            target.limit,
            color=INK_SECONDARY,
            linestyle="--",
            linewidth=1,
            label=f"Target: {target.limit_text()}",
        )
        ax.set_title(METRIC_NAMES[target.metric])
        ax.set_xlabel(f"{taxon} window (h)")
        if target.metric == RATE_AT_MARK:
            ax.yaxis.set_major_formatter(matplotlib_percent())
        # The detection lines are flat, so "best" can land on the target line.
        ax.legend(
            loc="center right" if target.metric == RATE_AT_MARK else "best",
            fontsize=8,
        )
    axes[0].set_ylabel("Per animal-month")
    axes[1].set_ylabel("Median hours, living birds")
    axes[2].set_ylabel("Share of carcasses")
    figure.suptitle(
        f"Watch targets by {taxon} window, others at their own; "
        f"{SCENARIO_LABELS[scenario].lower()} uploads",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    figure.tight_layout()
    return figure


def _sweep_figure(pyplot, report: dict):
    """The sweep's trade-offs in three panels.

    Args:
        pyplot: ``matplotlib.pyplot``.
        report: Sweep report.

    Returns:
        matplotlib.figure.Figure: False mortality alerts by window and box;
        carcass deaths flagged by the mark, by window and scenario (100 m
        box); gap alerts against median delay, one point per margin.
    """
    rows = report["rows"]
    mortality = [r for r in rows if r["swept"] == "mortality"]
    gap = [r for r in rows if r["swept"] == "gap"]
    windows = sorted({r["mortality_window_hours"] for r in mortality})
    boxes = sorted({r["mortality_box_m"] for r in mortality})
    figure, (ax_false, ax_hit, ax_gap) = pyplot.subplots(1, 3, figsize=(13, 3.8))

    for index, box in enumerate(boxes):
        ys = [
            next(
                r["false_mortality_per_animal_month"]
                for r in mortality
                if r["scenario"] == "ideal"
                and r["mortality_box_m"] == box
                and r["mortality_window_hours"] == w
            )
            for w in windows
        ]
        ax_false.plot(
            windows,
            ys,
            color=SERIES[index],
            linestyle=LINE_STYLES[index],
            linewidth=2,
            marker="o",
            markersize=5,
            label=f"{box:g} m box",
        )
    ax_false.set_title("False mortality alerts")
    ax_false.set_ylabel("Per animal-month")
    ax_false.legend(loc="upper right")

    for index, name in enumerate(SCENARIO_ORDER):
        ys = [
            next(
                r["carcass_rate_at_mark"]
                for r in mortality
                if r["scenario"] == name
                and r["mortality_box_m"] == boxes[0]
                and r["mortality_window_hours"] == w
            )
            for w in windows
        ]
        ax_hit.plot(
            windows,
            ys,
            color=SERIES[index],
            linestyle=LINE_STYLES[index],
            linewidth=2,
            marker="o",
            markersize=5,
            label=SCENARIO_LABELS[name],
            # Scenarios often coincide here; the dotted daily line is
            # drawn over the 2-day one so both stay visible.
            zorder=5 if name == "satellite_daily" else 3,
        )
    n = mortality[0]["carcass_deaths"]
    ax_hit.set_title(
        f"Carcass deaths flagged by {report['mark_hours']:g} h "
        f"(n={n}, {boxes[0]:g} m box)"
    )
    ax_hit.set_ylim(0, 1.04)
    ax_hit.yaxis.set_major_formatter(matplotlib_percent())
    ax_hit.legend(loc="lower left")
    for ax in (ax_false, ax_hit):
        ax.set_xticks(windows)
        ax.set_xlabel("Mortality window (h)")

    for index, name in enumerate(SCENARIO_ORDER):
        points = sorted(
            (r for r in gap if r["scenario"] == name),
            key=lambda r: r["upload_margin_hours"],
        )
        xs = [r["gap_per_animal_month"] for r in points]
        ys = [r["other_deaths_median_gap_delay_hours"] for r in points]
        ax_gap.plot(
            xs,
            ys,
            color=SERIES[index],
            linestyle=LINE_STYLES[index],
            linewidth=2,
            marker="o",
            markersize=5,
            label=SCENARIO_LABELS[name],
        )
        # Label the margins on one series only, to keep the panel legible.
        if name == "ideal":
            for row, x, y in zip(points, xs, ys):
                ax_gap.annotate(
                    f"+{row['upload_margin_hours']:g} h",
                    (x, y),
                    xytext=(5, 4),
                    textcoords="offset points",
                    color=INK_SECONDARY,
                )
    ax_gap.set_title("Gap detector: load against delay")
    ax_gap.set_xlabel("Gap alerts per animal-month")
    ax_gap.set_ylabel("Median delay on deaths (h)")
    ax_gap.legend(loc="upper right")

    figure.suptitle(
        f"Threshold sweep, vulture {report['set']} set",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    figure.tight_layout()
    return figure


def write_geofence_map(fence, fixes: list, incidents: list, path: Path) -> None:
    """Map a study's fixes, its fence and where the geofence alerted.

    Args:
        fence: The study's ``Fence``.
        fixes: The study's fixes.
        incidents: Incidents from one replay; geofence opens are plotted.
        path: Output PNG.
    """
    import math  # pylint: disable=import-outside-toplevel

    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    pyplot.rcParams.update(STYLE)
    where = {(f.deployment_id, f.timestamp): f for f in fixes}
    exits = [
        where[(i.deployment_id, i.opened_at)]
        for i in incidents
        if i.detector == "geofence" and (i.deployment_id, i.opened_at) in where
    ]
    figure, ax = pyplot.subplots(figsize=(5.4, 7.6))
    # Every 20th fix is plenty to show where the animals ranged.
    sample = fixes[::20]
    ax.scatter(
        [f.lon for f in sample],
        [f.lat for f in sample],
        s=1,
        color=GRID,
        rasterized=True,
        label="Fixes (1 in 20)",
    )
    for part in getattr(fence.polygon, "geoms", [fence.polygon]):
        xs, ys = part.exterior.xy
        ax.plot(xs, ys, color=INK_SECONDARY, linewidth=1.5)
    ax.plot([], [], color=INK_SECONDARY, linewidth=1.5, label=f"{fence.name} boundary")
    ax.scatter(
        [f.lon for f in exits],
        [f.lat for f in exits],
        s=36,
        color=SERIES[1],
        edgecolor=SURFACE,
        linewidth=1.5,
        zorder=3,
        label=f"Geofence alerts ({len(exits)})",
    )
    lons = [f.lon for f in fixes]
    lats = [f.lat for f in fixes]
    pad = 0.05
    ax.set_xlim(min(lons) - pad, max(lons) + pad)
    ax.set_ylim(min(lats) - pad, max(lats) + pad)
    # Equal distances on both axes at this latitude.
    ax.set_aspect(1 / math.cos(math.radians(sum(lats) / len(lats))))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.08), ncol=1, markerscale=1)
    figure.suptitle(
        f"Where the geofence alerted: {fence.name}",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    figure.text(
        0.99,
        0.01,
        "Boundary © OpenStreetMap contributors (ODbL)",
        ha="right",
        color=INK_SECONDARY,
        fontsize=7,
    )
    figure.tight_layout()
    _save(figure, path)
    pyplot.close(figure)


# Lanes of the death timeline, top to bottom, with each detector's colour.
TIMELINE_LANES = (
    ("mortality", "Mortality", SERIES[0]),
    ("gap", "Data gap", SERIES[1]),
    ("potential_death", "Potential death", SERIES[2]),
)


def write_death_timeline(
    timeline: dict, mark_hours: float, window: tuple[float, float], path: Path
) -> None:
    """Draw one death as each arrival scenario saw it.

    The top panel shows how far each fix lay from where the carcass ended
    up; below it, one panel per scenario shows when fixes arrived and when
    each incident was open, all in hours from the death start.

    Args:
        timeline: From ``evaluation.death_timeline``.
        mark_hours: The reference mark, drawn as a line.
        window: First and last hour on the axis.
        path: Output PNG.
    """
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    pyplot.rcParams.update(STYLE)
    names = [n for n in SCENARIO_ORDER if n in timeline["scenarios"]]
    figure, axes = pyplot.subplots(
        1 + len(names),
        1,
        figsize=(7.6, 2.2 + 1.5 * len(names)),
        sharex=True,
        gridspec_kw={"height_ratios": [1.6] + [1.0] * len(names)},
    )
    first, last = window

    ax = axes[0]
    # Log scale cannot show 0 m, and anything under a metre is the same
    # place at GPS accuracy.
    ax.scatter(
        [h for h, _ in timeline["fixes"]],
        [max(m, 1.0) for _, m in timeline["fixes"]],
        s=10,
        color=INK_SECONDARY,
        zorder=3,
    )
    ax.set_yscale("log")
    ax.axhline(100, color=INK_SECONDARY, linewidth=1, linestyle="--")
    ax.text(first + 1, 120, "100 m", color=INK_SECONDARY, fontsize=8)
    ax.set_ylabel("Metres from carcass")
    ax.set_title("Fixes taken: distance from where the carcass lay")

    for ax, name in zip(axes[1:], names):
        scenario = timeline["scenarios"][name]
        rows = len(TIMELINE_LANES)
        ax.scatter(
            scenario["arrivals"],
            [rows] * len(scenario["arrivals"]),
            marker="|",
            s=60,
            color=INK_SECONDARY,
        )
        for row, (detector, _, colour) in enumerate(TIMELINE_LANES):
            y = rows - 1 - row
            for incident in scenario["incidents"]:
                if incident["detector"] != detector:
                    continue
                start = max(incident["raised"], first)
                end = last if incident["resolved"] is None else incident["resolved"]
                ax.barh(y, end - start, left=start, height=0.5, color=colour)
                if incident["raised"] >= first:
                    ax.text(
                        incident["raised"] + 1.5,
                        y + 0.3,
                        f"{incident['raised']:.0f} h",
                        color=INK,
                        fontsize=8,
                        va="bottom",
                    )
        ax.set_yticks(
            range(rows + 1),
            [label for _, label, _ in reversed(TIMELINE_LANES)] + ["Fixes arrive"],
        )
        ax.set_ylim(-0.6, rows + 0.8)
        ax.grid(axis="y", visible=False)
        ax.set_title(f"{SCENARIO_LABELS[name]}: fixes arriving and alerts open")

    for ax in axes:
        ax.set_axisbelow(True)
        ax.axvline(0, color=INK, linewidth=1)
        ax.axvline(mark_hours, color=INK_SECONDARY, linewidth=1, linestyle=":")
    # After the death every fix is near the carcass, so the space above
    # the 100 m line is free for the labels.
    axes[0].text(1.5, 3e3, "Death start", color=INK, fontsize=8)
    axes[0].text(
        mark_hours + 1.5, 3e3, f"{mark_hours:g} h mark", color=INK_SECONDARY, fontsize=8
    )
    axes[-1].set_xlim(first, last)
    axes[-1].set_xlabel(
        f"Hours from death start (last fix at {timeline['still_hours']:.0f} h)"
    )
    figure.suptitle(
        f"One vulture's death under two upload patterns ({timeline['deployment_id']})",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
    )
    figure.tight_layout()
    _save(figure, path)
    pyplot.close(figure)


SPECIES_NAMES = {
    "Cathartes aura": "Turkey vulture",
    "Coragyps atratus": "Black vulture",
    "Canis mesomelas": "Black-backed jackal",
    "Loxodonta africana": "African elephant",
}
TAG_NAMES = {
    "Argos PTT GPS transmitter": "Argos PTT",
    "solar-powered GPS/GSM transmitter": "solar GPS/GSM",
}


def _group_name(group: dict) -> str:
    """A group's species, or "all" when it covers several.

    Args:
        group: One group as written by ``scripts/stillness.py``.

    Returns:
        str: The common name, or "all".
    """
    if len(group["taxa"]) > 1:
        return "all"
    return SPECIES_NAMES.get(group["taxa"][0], group["taxa"][0])


def _tail_series(sets: list[dict]) -> list[tuple[str, dict]]:
    """One group per species: the taxon rows, or the whole set if it has one.

    Args:
        sets: Sets as written by ``scripts/stillness.py``.

    Returns:
        list[tuple[str, dict]]: Species name and its group, in set order.
    """
    series = []
    for result in sets:
        groups = result["groups"]
        taxa = [g for g in groups if g["taxon"] is not None and g["tag_model"] is None]
        for group in taxa or groups[:1]:
            series.append((_group_name(group), group))
    return series


def stillness_markdown(sets: list[dict]) -> str:
    """The living still-bout tails as Markdown tables.

    Args:
        sets: Sets as written by ``scripts/stillness.py``.

    Returns:
        str: One table for every set, then the carcass periods to compare.
    """
    thresholds = [b["hours"] for b in sets[0]["groups"][0]["beyond"]]
    lines = [
        "# How often living animals stay still",
        "",
        "Generated by `make stillness`; do not edit by hand. A still bout is "
        "one of the mortality detector's own clusters (100 m box, at least 6 "
        "fixes), run with no window so nothing alerts. The final stationary "
        "period of a dead or ambiguous track is left out, as it may be a "
        "carcass, and so is everything after a tag event began, as it is "
        "not an animal resting. Each cell is *bouts longer than the column (per "
        "animal-month)*; animal-months run from first to last fix on every "
        "deployment, as in the evaluation's load. Vultures are the tuning set "
        "only: every tuning bird wears an Argos PTT tag and every solar "
        "GPS/GSM tag is in the held-out set, so tag types cannot be compared "
        "here.",
        "",
        "| Set | Group | Tag | Deployments | Animal-months | Window | "
        + " | ".join(f"> {h:g} h" for h in thresholds)
        + " | > window | Longest (h) |",
        "|---|---|---|---:|---:|---:|" + "---:|" * (len(thresholds) + 2),
    ]
    for result in sets:
        for group in result["groups"]:
            name = _group_name(group)
            tags = ", ".join(TAG_NAMES.get(m, m) for m in group["tag_models"])
            cells = [
                f"{b['count']} ({b['per_animal_month']:.3f})"
                for b in group["beyond"] + [group["beyond_window"]]
            ]
            lines.append(
                f"| {result['study']} {result['set']} | {name} | {tags} | "
                f"{group['deployments']} | {group['animal_months']:.1f} | "
                f"{group['window_hours']:g} h | "
                + " | ".join(cells)
                + f" | {group['longest_hours']:.0f} |"
            )
    lines += [
        "",
        "## Carcasses in the same sets",
        "",
        "Final stationary periods of dead tracks long enough to count as a "
        "carcass, for comparison with the living tail above.",
        "",
        "| Set | Carcass periods (h) | Per animal-month |",
        "|---|---|---:|",
    ]
    for result in sets:
        carcasses = result["carcasses"]
        hours = ", ".join(f"{h:.0f}" for h in carcasses["hours"]) or "none"
        lines.append(
            f"| {result['study']} {result['set']} | {hours} | "
            f"{carcasses['per_animal_month']:.4f} |"
        )
    return "\n".join(lines) + "\n"


def _stillness_figure(pyplot, sets: list[dict]):
    """Living still bouts longer than each length, one line per species.

    Args:
        pyplot: ``matplotlib.pyplot``.
        sets: Sets as written by ``scripts/stillness.py``.

    Returns:
        matplotlib.figure.Figure: Rates on log axes, each species' window
        marked, with the vulture carcass rate and carcass periods for
        comparison.
    """
    figure, axes = pyplot.subplots(figsize=(7.5, 4.2))
    for index, (name, group) in enumerate(_tail_series(sets)):
        # A log axis cannot show zero, so a species with no bout past a
        # length stops there; one with none at all says so in the legend.
        points = [(p["hours"], p["per_animal_month"]) for p in group["curve"]]
        points = [(h, r) for h, r in points if r > 0]
        window = group["window_hours"]
        if not points:
            axes.plot(
                [],
                [],
                color=SERIES[index],
                linewidth=2,
                label=f"{name}: none past {window:g} h window",
            )
            continue
        axes.plot(
            [h for h, _ in points],
            [r for _, r in points],
            color=SERIES[index],
            linestyle=LINE_STYLES[index],
            linewidth=2,
            label=name,
        )
        at_window = group["beyond_window"]["per_animal_month"]
        if at_window > 0:
            axes.plot(window, at_window, "o", color=SERIES[index], markersize=6)
    vultures = next(s for s in sets if s["study"] == "vultures")
    carcass = vultures["carcasses"]
    axes.axhline(
        carcass["per_animal_month"],
        color=INK_SECONDARY,
        linestyle="--",
        linewidth=1,
        label="Vulture carcasses, any length",
    )
    for hours in carcass["hours"]:
        axes.axvline(hours, ymax=0.04, color=INK, linewidth=1.5)
    # Legend entries for the window dots and carcass ticks, drawn above.
    axes.plot(
        [], [], "o", color=INK_SECONDARY, markersize=6, label="Species' alert window"
    )
    axes.plot(
        [],
        [],
        "|",
        color=INK,
        markersize=9,
        markeredgewidth=1.5,
        label="Vulture carcass periods",
    )
    axes.set_xscale("log")
    axes.set_yscale("log")
    axes.set_xticks([12, 24, 36, 72, 168, 336, 720])
    axes.set_xticklabels(["12 h", "24 h", "36 h", "3 d", "1 wk", "2 wk", "30 d"])
    axes.set_title("Living still bouts longer than each length")
    axes.set_ylabel("Per animal-month")
    axes.legend(loc="upper right")
    figure.tight_layout()
    return figure


def write_stillness(sets: list[dict], markdown_path: Path, figures: Path) -> None:
    """Write the still-bout tables and figure.

    Args:
        sets: Sets as written by ``scripts/stillness.py``.
        markdown_path: Output Markdown file.
        figures: Figure directory, created if needed.
    """
    markdown_path.write_text(stillness_markdown(sets), encoding="utf-8")
    figures.mkdir(parents=True, exist_ok=True)
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    pyplot.rcParams.update(STYLE)
    figure = _stillness_figure(pyplot, sets)
    _save(figure, figures / "stillness-tail.png")
    pyplot.close(figure)
