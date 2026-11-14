"""What the long living still bouts are: each one sorted into a class.

``telemetry.analysis.stillness`` counts how often living animals stay
still past the mortality window. This module asks why: it takes each of
those bouts and puts it in one class by when and where it happened and
how often the tag was fixing (a nestling in the nest, a breeding adult
on a site it returns to, a tag fixing about once a day, and so on), so
the false-alert load can be read by cause before a rule is chosen for
any of it.

It describes bouts, not alerts: a bout is the detector's cluster run
with no window, so it is the stillness an alert would come from, without
the upload pattern or the alert's own resolve rule.

The class tests and their cut-offs are in the experiment file under
``[descriptive.still_bouts]``. They were chosen by eye on tuning data to
name what the bouts are; no detector reads them.
"""

import statistics
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.analysis.evaluation import Truth
from telemetry.analysis.fledging import ANCHOR_FIXES, first_departure
from telemetry.analysis.stillness import living_still_bouts
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m
from telemetry.core.species import profile_for

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)

# In the order the tests are applied; the first that fits wins.
CLASSES = (
    "nestling",
    "sparse",
    "natal_return",
    "breeding_site",
    "other_site",
    "season_site",
    "one_off",
)
TITLES = {
    "nestling": "Nestling, before first leaving",
    "sparse": "Sparse fixes",
    "natal_return": "Back at the natal nest, first year",
    "breeding_site": "Site used in several years, breeding season",
    "other_site": "Site used in several years, other",
    "season_site": "Site used in one year only",
    "one_off": "One-off place",
}


@dataclass(frozen=True)
class Rules:
    """The class cut-offs, from ``[descriptive.still_bouts]``.

    Attributes:
        departure_radius_m: Distance from the tag's start that counts as
            having left it.
        sparse_fixes_per_day: Below this many fixes a day inside a bout,
            the bout is put down to the tag.
        natal_radius_m: How near the tag's start counts as being back.
        natal_days: Days from the first fix that count as the first year.
        site_radius_m: How near two bouts must be to share a site.
        site_years: Calendar years a site needs to count as used over
            several years.
        site_bouts: Long bouts a site needs to count as used in one year.
        breeding_months: Months of the breeding season.
        breeding_min_lat: Southern edge of the breeding range, in degrees.
        marks_hours: Lengths, beyond the window, to count bouts past.
    """

    departure_radius_m: float
    sparse_fixes_per_day: float
    natal_radius_m: float
    natal_days: int
    site_radius_m: float
    site_years: int
    site_bouts: int
    breeding_months: frozenset[int]
    breeding_min_lat: float
    marks_hours: tuple[float, ...]

    @classmethod
    def from_table(cls, table: dict) -> "Rules":
        """Build the rules from the experiment file's table.

        Args:
            table: ``Experiment.descriptive["still_bouts"]``.

        Returns:
            Rules: The cut-offs.
        """
        return cls(
            **{
                **table,
                "breeding_months": frozenset(table["breeding_months"]),
                "marks_hours": tuple(table["marks_hours"]),
            }
        )


@dataclass(frozen=True)
class LongBout:
    """A living still bout longer than the window, with what classes it.

    Attributes:
        deployment_id: The deployment.
        start: Time of its first fix.
        hours: Length from first to last fix.
        fixes: Fixes in the cluster.
        lat: Median latitude of the track's fixes during it.
        lon: Median longitude of the same.
        from_start_m: Distance from where the tag started.
        age: Time since the track's first fix.
        departed: Whether the bird had already left the tag's start.
        spread: Median hourly acceleration spread during it, if read.
    """

    deployment_id: str
    start: datetime
    hours: float
    fixes: int
    lat: float
    lon: float
    from_start_m: float
    age: timedelta
    departed: bool
    spread: float | None = None

    @property
    def fixes_per_day(self) -> float:
        """How often the tag fixed during the bout.

        Returns:
            float: Fixes per 24 hours of its length.
        """
        return self.fixes / (self.hours / 24.0)


def long_bouts(
    truth: Truth,
    fixes: list[Fix],
    rules: Rules,
    spread: dict[datetime, float] | None = None,
) -> list[LongBout]:
    """One deployment's living still bouts longer than its window.

    Args:
        truth: What is known about the deployment.
        fixes: Its fixes, in time order; not empty.
        rules: The class cut-offs; only the departure radius is used.
        spread: Acceleration spread by the start of each hour, if the tag
            has an accelerometer.

    Returns:
        list[LongBout]: The bouts, in time order.
    """
    window = profile_for(truth.taxon).mortality.window / HOUR
    times = [fix.timestamp for fix in fixes]
    anchor = fixes[:ANCHOR_FIXES]
    start_lat = statistics.median(fix.lat for fix in anchor)
    start_lon = statistics.median(fix.lon for fix in anchor)
    left = first_departure(fixes, rules.departure_radius_m)
    found = []
    for bout in living_still_bouts(truth, fixes):
        if bout.hours <= window:
            continue
        # Every fix in the bout's span, strays included: the median places
        # the bout without needing the detector's own cluster members.
        inside = fixes[bisect_left(times, bout.start) : bisect_right(times, bout.end)]
        lat = statistics.median(fix.lat for fix in inside)
        lon = statistics.median(fix.lon for fix in inside)
        found.append(
            LongBout(
                deployment_id=truth.deployment_id,
                start=bout.start,
                hours=bout.hours,
                fixes=bout.fixes,
                lat=lat,
                lon=lon,
                from_start_m=haversine_m(start_lat, start_lon, lat, lon),
                age=bout.start - fixes[0].timestamp,
                departed=left is not None and bout.start >= left,
                spread=_spread_during(bout.start, bout.end, spread or {}),
            )
        )
    return found


def _spread_during(
    start: datetime, end: datetime, spread: dict[datetime, float]
) -> float | None:
    """Median hourly acceleration spread between two times.

    Args:
        start: First fix of the bout.
        end: Last fix of the bout.
        spread: Spread by the start of each hour.

    Returns:
        float | None: The median over the hours that have a reading, or
        None if none has.
    """
    hour = start.replace(minute=0, second=0, microsecond=0)
    values = []
    while hour <= end:
        if hour in spread:
            values.append(spread[hour])
        hour += HOUR
    return statistics.median(values) if values else None


def classify(bout: LongBout, own: list[LongBout], rules: Rules) -> str:
    """The class of one bout, given the same bird's other long bouts.

    Args:
        bout: The bout.
        own: Every long bout of its deployment, itself included.
        rules: The class cut-offs.

    Returns:
        str: One of ``CLASSES``: the first whose test the bout meets.
    """
    if not bout.departed:
        return "nestling"
    # Tested before place: a tag fixing once a day at the same roost shows
    # no departures whatever the bird does, so place says nothing about it.
    if bout.fixes_per_day < rules.sparse_fixes_per_day:
        return "sparse"
    if bout.from_start_m < rules.natal_radius_m and bout.age < rules.natal_days * DAY:
        return "natal_return"
    near = [
        other
        for other in own
        if haversine_m(bout.lat, bout.lon, other.lat, other.lon) < rules.site_radius_m
    ]
    if len({other.start.year for other in near}) >= rules.site_years:
        in_season = bout.start.month in rules.breeding_months
        if in_season and bout.lat >= rules.breeding_min_lat:
            return "breeding_site"
        return "other_site"
    if len(near) >= rules.site_bouts:
        return "season_site"
    return "one_off"


def _summary(bouts: list[LongBout], months: float, rules: Rules) -> dict:
    """Counts and medians for one class of bouts.

    Args:
        bouts: The class's bouts; may be empty.
        months: Animal-months of the whole set, for the rates.
        rules: The class cut-offs; only the marks are used.

    Returns:
        dict: Bouts, their rate, the birds they come from and the largest
        share one bird holds, counts and rates past each mark, median
        length and fixes per day, median acceleration spread with how
        many bouts had none, and bouts by calendar month of their start.
    """
    by_bird = Counter(bout.deployment_id for bout in bouts)
    spreads = [bout.spread for bout in bouts if bout.spread is not None]
    by_month = Counter(bout.start.month for bout in bouts)
    return {
        "bouts": len(bouts),
        "per_animal_month": round(len(bouts) / months, 4),
        "birds": len(by_bird),
        "top_bird_share": (
            round(max(by_bird.values()) / len(bouts), 3) if bouts else None
        ),
        "beyond": [
            {
                "hours": mark,
                "count": sum(bout.hours > mark for bout in bouts),
                "per_animal_month": round(
                    sum(bout.hours > mark for bout in bouts) / months, 4
                ),
            }
            for mark in rules.marks_hours
        ],
        "median_hours": (
            round(statistics.median(bout.hours for bout in bouts), 1) if bouts else None
        ),
        "median_fixes_per_day": (
            round(statistics.median(bout.fixes_per_day for bout in bouts), 1)
            if bouts
            else None
        ),
        "median_spread": round(statistics.median(spreads), 1) if spreads else None,
        "without_spread": len(bouts) - len(spreads),
        "by_month": [by_month.get(month, 0) for month in range(1, 13)],
    }


def measure(
    truths: list[Truth],
    fixes: list[Fix],
    rules: Rules,
    animal_month: timedelta,
    spread: dict[str, dict[datetime, float]] | None = None,
) -> dict:
    """The long living still bouts of one set, by class.

    Args:
        truths: The set's deployments.
        fixes: Their fixes, in any order.
        rules: The class cut-offs.
        animal_month: Length of an animal-month.
        spread: Acceleration spread by hour, for each deployment ID that
            has it.

    Returns:
        dict: ``animal_months`` (first to last fix over every deployment,
        as in the stillness table), ``window_hours``, ``all`` (a summary
        of every long bout) and ``classes`` (a summary per class, in
        ``CLASSES`` order, each with its ``share`` of the bouts).
    """
    tracks: dict[str, list[Fix]] = {}
    for fix in fixes:
        tracks.setdefault(fix.deployment_id, []).append(fix)
    months = sum((t.last_fix - t.first_fix) / animal_month for t in truths)
    sorted_bouts: dict[str, list[LongBout]] = {name: [] for name in CLASSES}
    for truth in truths:
        own_fixes = sorted(tracks[truth.deployment_id], key=lambda fix: fix.timestamp)
        own = long_bouts(
            truth, own_fixes, rules, (spread or {}).get(truth.deployment_id)
        )
        for bout in own:
            sorted_bouts[classify(bout, own, rules)].append(bout)
    everything = [bout for bouts in sorted_bouts.values() for bout in bouts]
    return {
        "animal_months": round(months, 1),
        # Every set here is a single taxon.
        "window_hours": profile_for(truths[0].taxon).mortality.window / HOUR,
        "all": _summary(everything, months, rules),
        "classes": [
            {
                "class": name,
                "share": (
                    round(len(sorted_bouts[name]) / len(everything), 3)
                    if everything
                    else None
                ),
                **_summary(sorted_bouts[name], months, rules),
            }
            for name in CLASSES
        ],
    }


def _row(title: str, name: str, row: dict, share: float | None) -> str:
    """One table line.

    Args:
        title: The population.
        name: The class title, or "All".
        row: A ``_summary`` result.
        share: The class's share of the set's bouts, or None.

    Returns:
        str: The Markdown table row.
    """

    def text(value, pattern="{}") -> str:
        """A cell, or a dash where there is nothing to show.

        Args:
            value: The value, or None.
            pattern: How to format it.

        Returns:
            str: The cell text.
        """
        return "-" if value is None else pattern.format(value)

    beyond = " | ".join(
        f"{mark['count']} ({mark['per_animal_month']:.3f})" for mark in row["beyond"]
    )
    return (
        f"| {title} | {name} | {row['bouts']} ({row['per_animal_month']:.3f}) "
        f"| {text(share, '{:.1%}')} | {row['birds']} "
        f"| {text(row['top_bird_share'], '{:.0%}')} | {beyond} "
        f"| {text(row['median_hours'])} | {text(row['median_fixes_per_day'])} "
        f"| {text(row['median_spread'])} ({row['without_spread']}) |"
    )


def markdown(sets: list[dict], rules: Rules) -> str:
    """The still-bout class tables.

    Args:
        sets: One entry per population, as ``scripts/bouts.py`` writes
            them: ``study``, ``title`` and the ``measure`` result.
        rules: The class cut-offs, quoted in the definitions.

    Returns:
        str: The report, as Markdown.
    """
    window = sets[0]["window_hours"]
    marks = " | ".join(f"> {mark:g} h" for mark in rules.marks_hours)
    months = ", ".join(str(month) for month in sorted(rules.breeding_months))
    lines = [
        "# What the long living still bouts are",
        "",
        "Generated by `scripts/bouts.py` (`make bouts`); do not edit.",
        "",
        "Stork tuning populations only. A bout is one of the mortality",
        "detector's own clusters, run with no window, on a bird that was alive",
        f"(as in `results/stillness/STILLNESS.md`); only bouts longer than the "
        f"{window:g} h",
        "window are counted. Each is put in the first class whose test it",
        "meets. The cut-offs were chosen by eye on these populations after",
        "seeing the bouts: they describe, and no detector uses them.",
        "",
        "| Class | Test |",
        "|---|---|",
        f"| {TITLES['nestling']} | Starts before the bird's first fix "
        f"{rules.departure_radius_m:g} m from where its tag started |",
        f"| {TITLES['sparse']} | Fewer than {rules.sparse_fixes_per_day:g} fixes "
        "a day inside the bout |",
        f"| {TITLES['natal_return']} | Within {rules.natal_radius_m:g} m of where "
        f"the tag started, under {rules.natal_days} days after its first fix |",
        f"| {TITLES['breeding_site']} | The bird has long bouts within "
        f"{rules.site_radius_m:g} m in {rules.site_years} or more calendar years; "
        f"this one starts in months {months} at or north of "
        f"{rules.breeding_min_lat:g} degrees |",
        f"| {TITLES['other_site']} | The same repeat, at another season or "
        "further south |",
        f"| {TITLES['season_site']} | {rules.site_bouts} or more long bouts "
        f"within {rules.site_radius_m:g} m, all in one calendar year |",
        f"| {TITLES['one_off']} | None of the above |",
        "",
        "Counts are bouts, with the rate per animal-month in brackets. *Top",
        "bird* is the largest share of the class's bouts that one bird holds.",
        "*Spread* is the median hourly acceleration spread during the bout",
        "(the acceleration cue's signal), with the bouts that had no reading",
        "in brackets.",
        "",
        f"| Population | Class | > {window:g} h | Share | Birds | Top bird | {marks} "
        "| Median h | Fixes a day | Spread |",
        "|---|---|---:|---:|---:|---:|"
        + "---:|" * len(rules.marks_hours)
        + "---:|---:|---:|",
    ]
    for entry in sets:
        lines.append(_row(entry["title"], "All", entry["all"], None))
        for row in entry["classes"]:
            lines.append(_row(entry["title"], TITLES[row["class"]], row, row["share"]))
    return "\n".join(lines) + "\n"
