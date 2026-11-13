"""The fix-rate cue: a watch alert on a collar that has gone quiet.

A collar on a carcass may report less often than on a live bird. Two earlier
checks measured that differently and disagreed on the same bird, so this
module carries out the one definition frozen in ``config/experiment.toml``
under ``[cues.fix_rate]``, and the rule that chose it. The value is computed
from what an online alert knows: fixes up to the alert's evidence time and
the start of the stationary run, which the alert's own text states.
"""

import bisect
import itertools
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from telemetry.analysis.evaluation import ALIVE, DEAD, Truth, classify
from telemetry.analysis.experiment import Experiment
from telemetry.analysis.intervals import wilson
from telemetry.core.alerts import Incident
from telemetry.core.fixes import Fix

HOUR = timedelta(hours=1)
TRUE = "true"
FALSE = "false"

# The text the mortality detector writes (src/telemetry/core/detectors/
# mortality.py); a test pins that the pattern still matches it.
STILL_SINCE = re.compile(r"still since (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC")


@dataclass(frozen=True)
class Variant:
    """One way of computing the ratio.

    Attributes:
        baseline_days: Days before the stationary run that give the
            reference rate.
        repeats: ``count`` keeps fixes that resend the previous fix's
            coordinates, ``drop`` leaves them out of both rates.
        hour_matched: Whether both rates use only the hours of the day in
            which the bird had a fix in the baseline.
    """

    baseline_days: int
    repeats: str
    hour_matched: bool

    @property
    def label(self) -> str:
        """A short name for tables.

        Returns:
            str: For example ``7d/count/all-hours``.
        """
        hours = "matched-hours" if self.hour_matched else "all-hours"
        return f"{self.baseline_days}d/{self.repeats}/{hours}"


@dataclass(frozen=True)
class Case:
    """One watch alert with the ratio under every variant.

    Attributes:
        group: ``vultures`` or ``storks``.
        deployment_id: The bird.
        kind: ``true`` or ``false``, as ``classify`` calls it.
        values: The ratio per variant; None where it is undefined.
    """

    group: str
    deployment_id: str
    kind: str
    values: dict[Variant, float | None]


def variants(settings: Experiment) -> list[Variant]:
    """Every variant the experiment file lists, simplest first.

    Args:
        settings: The experiment file.

    Returns:
        list[Variant]: The product of the lists, with the first value of
        each list varying slowest, so earlier means fewer options switched
        on when a tie is broken.
    """
    cue = settings.cues["fix_rate"]
    return [
        Variant(days, repeats, matched)
        for days, repeats, matched in itertools.product(
            cue["baseline_days"], cue["repeats"], cue["hour_matched"]
        )
    ]


def frozen(settings: Experiment) -> tuple[Variant, float]:
    """The definition and cut frozen after the run.

    Args:
        settings: The experiment file.

    Returns:
        tuple[Variant, float]: The variant and the cut at or below which
        the cue fires.
    """
    chosen = settings.cues["fix_rate"]["frozen"]
    return (
        Variant(chosen["baseline_days"], chosen["repeats"], chosen["hour_matched"]),
        chosen["cut"],
    )


def still_start(message: str) -> datetime | None:
    """When the stationary run began, from an alert's text.

    Args:
        message: A mortality alert's message.

    Returns:
        datetime | None: The start (UTC), or None if the text has none.
    """
    found = STILL_SINCE.search(message)
    if found is None:
        return None
    return datetime.strptime(found.group(1), "%Y-%m-%d %H:%M").replace(
        tzinfo=timezone.utc
    )


class Track:
    """One bird's fixes, ready for counting inside time ranges.

    Attributes:
        first: Time of the bird's first fix.
    """

    def __init__(self, fixes: list[Fix]):
        """Index a bird's fixes.

        Args:
            fixes: The bird's fixes in any order.
        """
        ordered = sorted(fixes, key=lambda fix: fix.timestamp)
        self.first = ordered[0].timestamp
        self._times = {
            "count": [fix.timestamp for fix in ordered],
            "drop": [
                b.timestamp
                for a, b in zip([None] + ordered, ordered)
                if a is None or (a.lat, a.lon) != (b.lat, b.lon)
            ],
        }

    def between(self, repeats: str, start: datetime, end: datetime) -> list[datetime]:
        """Fix times in a half-open range.

        Args:
            repeats: ``count`` or ``drop``.
            start: Range start, included.
            end: Range end, excluded.

        Returns:
            list[datetime]: The fix times in ``[start, end)``.
        """
        times = self._times[repeats]
        return times[bisect.bisect_left(times, start) : bisect.bisect_left(times, end)]


def _slots(start: datetime, end: datetime) -> list[datetime]:
    """Whole hours that begin in a range.

    Args:
        start: Range start, included.
        end: Range end, excluded.

    Returns:
        list[datetime]: Hour starts from the first whole hour at or after
        ``start`` to before ``end``.
    """
    first = start.replace(minute=0, second=0, microsecond=0)
    if first < start:
        first += HOUR
    count = max(0, math.ceil((end - first) / HOUR))
    return [first + HOUR * step for step in range(count)]


def cue_value(
    track: Track,
    start: datetime,
    end: datetime,
    variant: Variant,
    min_baseline_hours: float,
) -> float | None:
    """The fix-rate ratio for one alert under one variant.

    Args:
        track: The bird's fixes.
        start: Start of the stationary run.
        end: The alert's evidence time; no later fix is read.
        variant: How to compute it.
        min_baseline_hours: Shortest baseline for the ratio to be defined.

    Returns:
        float | None: The rate from ``start`` to ``end`` over the rate in
        the baseline, both per elapsed hour. None if the baseline is too
        short or holds no fixes, or the run has no hours.
    """
    base_from = max(start - timedelta(days=variant.baseline_days), track.first)
    if (start - base_from) / HOUR < min_baseline_hours:
        return None
    before = track.between(variant.repeats, base_from, start)
    inside = track.between(variant.repeats, start, end + timedelta(microseconds=1))
    if not before:
        return None
    if variant.hour_matched:
        matched = {time.hour for time in before}
        base_hours = sum(slot.hour in matched for slot in _slots(base_from, start))
        run_hours = sum(slot.hour in matched for slot in _slots(start, end))
        before = [time for time in before if time.hour in matched]
        inside = [time for time in inside if time.hour in matched]
    else:
        base_hours = (start - base_from) / HOUR
        run_hours = (end - start) / HOUR
    if not base_hours or not run_hours:
        return None
    rate_before = len(before) / base_hours
    return (len(inside) / run_hours) / rate_before


def build_cases(
    group: str,
    truths: list[Truth],
    incidents: list[Incident],
    fixes: list[Fix],
    grades: dict[str, str],
    settings: Experiment,
) -> list[Case]:
    """The watch alerts that can score the cue.

    A bird is left out unless it is labelled dead or alive, and also if its
    death was graded as inferred from the accelerometer.

    Args:
        group: ``vultures`` or ``storks``.
        truths: The birds that may be used, already restricted to tuning.
        incidents: Their incidents.
        fixes: Their fixes (other birds' fixes are ignored).
        grades: Death-label grades by deployment ID.
        settings: The experiment file.

    Returns:
        list[Case]: One per mortality watch alert on a usable bird.
    """
    cue = settings.cues["fix_rate"]
    by_id = {truth.deployment_id: truth for truth in truths}
    by_bird: dict[str, list[Fix]] = {}
    for fix in fixes:
        if fix.deployment_id in by_id:
            by_bird.setdefault(fix.deployment_id, []).append(fix)
    tracks: dict[str, Track] = {}
    cases = []
    for incident in incidents:
        truth = by_id.get(incident.deployment_id)
        if incident.detector != "mortality" or truth is None:
            continue
        if (
            truth.label not in (DEAD, ALIVE)
            or grades.get(truth.deployment_id) in cue["excluded_grades"]
        ):
            continue
        start = still_start(incident.message)
        if start is None:
            continue
        if incident.deployment_id not in tracks:
            tracks[incident.deployment_id] = Track(by_bird[incident.deployment_id])
        track = tracks[incident.deployment_id]
        cases.append(
            Case(
                group,
                truth.deployment_id,
                classify(truth, incident),
                {
                    variant: cue_value(
                        track,
                        start,
                        incident.opened_at,
                        variant,
                        cue["min_baseline_hours"],
                    )
                    for variant in variants(settings)
                },
            )
        )
    return [case for case in cases if case.kind in (TRUE, FALSE)]


def _share(cases: list[Case], variant: Variant, cut: float) -> dict:
    """The share of defined cases whose ratio is at or below a cut.

    Args:
        cases: Cases of one kind.
        variant: Which ratio.
        cut: The cue passes at or below this.

    Returns:
        dict: ``passing``, ``total`` (cases with a ratio), ``undefined``,
        ``share`` and its ``wilson`` interval.
    """
    defined = [c.values[variant] for c in cases if c.values[variant] is not None]
    passing = sum(value <= cut for value in defined)
    return {
        "passing": passing,
        "total": len(defined),
        "undefined": len(cases) - len(defined),
        "share": round(passing / len(defined), 6) if defined else None,
        "wilson": wilson(passing, len(defined)) if defined else None,
    }


def balanced_row(
    cases: list[Case], groups: list[str], variant: Variant, cut: float
) -> dict:
    """True and false shares at one cut, groups weighted equally.

    Args:
        cases: Watch alerts from every group.
        groups: The groups to weight equally.
        variant: Which ratio.
        cut: The cue passes at or below this.

    Returns:
        dict: ``cut``, each group's true and false shares, the balanced
        shares (mean over groups that have a share) and their ratio, None
        when the balanced false share is zero.
    """
    per_group = {}
    for group in groups:
        mine = [case for case in cases if case.group == group]
        per_group[group] = {
            "true": _share([c for c in mine if c.kind == TRUE], variant, cut),
            "false": _share([c for c in mine if c.kind == FALSE], variant, cut),
        }

    def mean(kind: str) -> float | None:
        """Mean share over the groups that have one.

        Args:
            kind: ``true`` or ``false``.

        Returns:
            float | None: The mean, or None if no group has a share.
        """
        shares = [
            g[kind]["share"] for g in per_group.values() if g[kind]["share"] is not None
        ]
        return sum(shares) / len(shares) if shares else None

    true, false = mean("true"), mean("false")
    return {
        "cut": cut,
        "groups": per_group,
        "true": true,
        "false": false,
        "ratio": round(true / false, 3) if true is not None and false else None,
    }


def _rank(row: dict) -> float:
    """Sort key for a row's ratio, treating a zero false share as best.

    Args:
        row: A ``balanced_row``.

    Returns:
        float: The ratio, infinite if no false alert passes, -1 if the
        ratio cannot be formed at all.
    """
    if row["true"] is None or row["false"] is None:
        return -1.0
    return row["ratio"] if row["false"] else math.inf if row["true"] else -1.0


def fit(cases: list[Case], groups: list[str], settings: Experiment) -> dict:
    """Run the frozen rule over the tuning alerts.

    Args:
        cases: Watch alerts, every group pooled.
        groups: The groups, weighted equally.
        settings: The experiment file.

    Returns:
        dict: Every variant's row at its operating cut, the chosen
        variant with whether it keeps ``keep_share`` of true alerts, and
        alert counts.
    """
    cue = settings.cues["fix_rate"]
    table = []
    for variant in variants(settings):
        rows = [balanced_row(cases, groups, variant, cut) for cut in cue["cuts"]]
        keeping = [r for r in rows if r["true"] and r["true"] >= cue["keep_share"]]
        table.append(
            {
                "variant": variant,
                "rows": rows,
                "point": keeping[0] if keeping else None,
            }
        )
    kept = [entry for entry in table if entry["point"] is not None]
    if kept:
        best = max(_rank(entry["point"]) for entry in kept)
        # Earliest in the list is the simplest; a ratio within the tolerance
        # of the best counts as tied.
        chosen = next(
            entry
            for entry in kept
            if _rank(entry["point"]) >= best * (1 - cue["tie_tolerance"])
        )
        meets = True
    else:
        fallback = [(e, next(r for r in e["rows"] if r["cut"] == 0.5)) for e in table]
        best = max(_rank(row) for _, row in fallback)
        entry, row = next(pair for pair in fallback if _rank(pair[1]) >= best)
        chosen = {**entry, "point": row}
        meets = False
    variant = chosen["variant"]
    return {
        "table": table,
        "chosen": chosen,
        "true_alerts": [
            {
                "group": c.group,
                "deployment_id": c.deployment_id,
                "ratio": c.values[variant],
            }
            for c in cases
            if c.kind == TRUE
        ],
        "meets_keep_share": meets,
        "alerts": {
            group: {
                kind: sum(c.group == group and c.kind == kind for c in cases)
                for kind in (TRUE, FALSE)
            }
            for group in groups
        },
    }


def _pct(share: float | None) -> str:
    """A share as a whole percentage.

    Args:
        share: A share between 0 and 1, or None.

    Returns:
        str: For example ``25%``, or ``-`` for None.
    """
    return "-" if share is None else f"{share:.0%}"


def markdown(result: dict, settings: Experiment) -> str:
    """The report, as written to ``results/fixrate/FIXRATE.md``.

    Args:
        result: The output of ``fit``.
        settings: The experiment file.

    Returns:
        str: Markdown text.
    """
    cue = settings.cues["fix_rate"]
    chosen = result["chosen"]
    point = chosen["point"]
    lines = [
        "# Fix-rate cue (step 3.3)",
        "",
        "Fitted on tuning birds only, under the experiment file's scenarios.",
        "Each group counts equally: the shares are the mean of the vulture and",
        "stork shares. The rule is written in `config/experiment.toml` under",
        "`[cues.fix_rate]` and was fixed before this run.",
        "",
        f"**Frozen definition: `{chosen['variant'].label}`, cut {point['cut']}.** "
        + (
            f"It keeps {_pct(point['true'])} of true alerts "
            f"(target {_pct(cue['keep_share'])}) and passes {_pct(point['false'])} "
            f"of false alerts: ratio {point['ratio']}."
            if result["meets_keep_share"]
            else "No variant keeps the target share of true alerts at any cut, "
            "so this is the best ratio at cut 0.5, frozen for Phase 4 to score "
            "but not an escalation rule."
        ),
        "",
        "## Alerts used",
        "",
        "| Group | True | False |",
        "|---|---|---|",
    ]
    for group, counts in result["alerts"].items():
        lines.append(f"| {group} | {counts['true']} | {counts['false']} |")
    lines += [
        "",
        "## Every variant at its operating cut",
        "",
        "The lowest cut keeping the target share of true alerts; blank if none does.",
        "",
        "| Variant | Cut | True passing | False passing | Ratio |",
        "|---|---|---|---|---|",
    ]
    for entry in result["table"]:
        row = entry["point"]
        label = entry["variant"].label
        if row is None:
            lines.append(f"| {label} | - | - | - | - |")
        else:
            lines.append(
                f"| {label} | {row['cut']} | {_pct(row['true'])} | "
                f"{_pct(row['false'])} | {row['ratio']} |"
            )
    lines += [
        "",
        "## Chosen variant by group and cut",
        "",
        "| Cut | Group | True passing | False passing | Undefined (true / false) |",
        "|---|---|---|---|---|",
    ]
    for row in chosen["rows"]:
        for group, shares in row["groups"].items():
            t, f = shares["true"], shares["false"]
            lines.append(
                f"| {row['cut']} | {group} | {t['passing']}/{t['total']} | "
                f"{f['passing']}/{f['total']} | {t['undefined']} / {f['undefined']} |"
            )
    lines += [
        "",
        "## True alerts under the chosen variant",
        "",
        "| Group | Bird | Ratio |",
        "|---|---|---|",
    ]
    for alert in result["true_alerts"]:
        ratio = "undefined" if alert["ratio"] is None else f"{alert['ratio']:.2f}"
        lines.append(f"| {alert['group']} | {alert['deployment_id']} | {ratio} |")
    return "\n".join(lines) + "\n"
