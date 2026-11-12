"""How much of the alert load falls before a bird first leaves the place
it was tagged.

Most white storks here were tagged as nestlings, and a nestling sits in
its nest, inside the mortality detector's box, until it fledges. This
module splits each track at its **first departure**: the first fix more
than a radius from where the tag started (the median position of its
first fixes). Alerts and tracked time are counted on each side, so the
load the nest period adds can be read off before deciding whether to
treat that period differently.

It describes alerts, not errors: every incident is counted, whether or
not the bird later proved dead, because no outcome labels are used. A
bird that died in the nest counts on the "before" side.

The radius and the number of anchoring fixes are provisional descriptive
choices, not detector settings; two radii are reported so the conclusion
can be seen not to hang on one.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from telemetry.core.alerts import Incident
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m

ANCHOR_FIXES = 24
RADII_M = (500.0, 2000.0)
DETECTORS = ("mortality", "potential_death", "gap")
DAY = timedelta(days=1)


def first_departure(
    fixes: list[Fix], radius_m: float, anchor_fixes: int = ANCHOR_FIXES
) -> datetime | None:
    """When a track first leaves the place it started.

    Args:
        fixes: One deployment's fixes, in time order; not empty.
        radius_m: Distance from the start that counts as having left.
        anchor_fixes: How many of the first fixes set the start position,
            by their median, so one stray fix does not move it.

    Returns:
        datetime | None: Time of the first fix beyond the radius, or None
        if the track never leaves.
    """
    anchor = fixes[:anchor_fixes]
    lat = statistics.median(fix.lat for fix in anchor)
    lon = statistics.median(fix.lon for fix in anchor)
    for fix in fixes:
        if haversine_m(lat, lon, fix.lat, fix.lon) > radius_m:
            return fix.timestamp
    return None


def _rate(count: int, months: float) -> float | None:
    """Incidents per animal-month.

    Args:
        count: Incidents.
        months: Animal-months they fell in.

    Returns:
        float | None: The rate, or None over no time.
    """
    return round(count / months, 3) if months else None


def measure(
    fixes: list[Fix],
    incidents: list[Incident],
    radius_m: float,
    animal_month: timedelta,
) -> dict:
    """Alerts and tracked time before and after first departure, for one set.

    An incident is placed by ``opened_at``, the time of the evidence, so
    the split does not move with how fixes were uploaded.

    Args:
        fixes: The set's fixes, in any order.
        incidents: Every incident a replay of the set raised.
        radius_m: Distance from the start that counts as having left.
        animal_month: Length of an animal-month.

    Returns:
        dict: Birds, how many never left, days to first departure (median,
        90th percentile, longest), animal-months on each side, and per
        detector the incidents and rate on each side with the share
        before.
    """
    tracks: dict[str, list[Fix]] = defaultdict(list)
    for fix in fixes:
        tracks[fix.deployment_id].append(fix)
    departed: dict[str, datetime | None] = {}
    days = []
    before = after = timedelta(0)
    for deployment_id, own in tracks.items():
        own.sort(key=lambda fix: fix.timestamp)
        left = first_departure(own, radius_m)
        departed[deployment_id] = left
        split = left or own[-1].timestamp
        before += split - own[0].timestamp
        after += own[-1].timestamp - split
        if left is not None:
            days.append((left - own[0].timestamp) / DAY)
    days.sort()
    months_before, months_after = before / animal_month, after / animal_month
    detectors = {}
    for name in DETECTORS:
        early = late = 0
        for incident in incidents:
            if incident.detector != name:
                continue
            left = departed[incident.deployment_id]
            if left is None or incident.opened_at < left:
                early += 1
            else:
                late += 1
        detectors[name] = {
            "before": early,
            "after": late,
            "per_animal_month_before": _rate(early, months_before),
            "per_animal_month_after": _rate(late, months_after),
            "share_before": round(early / (early + late), 3) if early + late else None,
        }
    return {
        "radius_m": radius_m,
        "birds": len(tracks),
        "never_left": sum(1 for left in departed.values() if left is None),
        "days_to_leave": {
            "median": round(statistics.median(days), 1) if days else None,
            "p90": round(days[int(0.9 * (len(days) - 1))], 1) if days else None,
            "max": round(days[-1], 1) if days else None,
        },
        "animal_months_before": round(months_before, 1),
        "animal_months_after": round(months_after, 1),
        "share_of_time_before": (
            round(months_before / (months_before + months_after), 3)
            if months_before + months_after
            else None
        ),
        "detectors": detectors,
    }


def markdown(sets: list[dict], scenario: str) -> str:
    """The first-departure tables.

    Args:
        sets: One entry per population, as ``scripts/fledging.py`` writes
            them: ``study``, ``title`` and ``radii`` (``measure`` results).
        scenario: The upload scenario the incidents came from.

    Returns:
        str: The report, as Markdown.
    """
    lines = [
        "# Alerts before and after first departure",
        "",
        "Generated by `scripts/fledging.py` (`make fledging`); do not edit.",
        "",
        "Stork tuning populations only. Each track is split at its first fix",
        "beyond the radius from where the tag started (the median of its first",
        f"{ANCHOR_FIXES} hourly fixes). Incidents are from the `{scenario}` replay,",
        "placed by the time of their evidence. Every incident is counted, true",
        "or false: no outcome labels are used here.",
        "",
        "| Population | Radius, m | Birds | Never left | Days to leave, "
        "median (90th, max) | Share of tracked time before |",
        "|---|---|---|---|---|---|",
    ]
    for entry in sets:
        for result in entry["radii"]:
            days = result["days_to_leave"]
            lines.append(
                f"| {entry['title']} | {result['radius_m']:g} | {result['birds']} "
                f"| {result['never_left']} | {days['median']} ({days['p90']}, "
                f"{days['max']}) | {result['share_of_time_before']:.1%} |"
            )
    lines += [
        "",
        "| Population | Radius, m | Alert | Before | After | Per animal-month "
        "before | Per animal-month after | Share of alerts before |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in sets:
        for result in entry["radii"]:
            for name, row in result["detectors"].items():
                share = row["share_before"]
                lines.append(
                    f"| {entry['title']} | {result['radius_m']:g} | {name} "
                    f"| {row['before']} | {row['after']} "
                    f"| {row['per_animal_month_before']} "
                    f"| {row['per_animal_month_after']} "
                    f"| {'n/a' if share is None else f'{share:.1%}'} |"
                )
    return "\n".join(lines) + "\n"
