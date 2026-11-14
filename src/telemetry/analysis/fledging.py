"""How much of the alert load falls before a bird first leaves the place
it was tagged.

Most white storks here were tagged as nestlings, and a nestling sits in
its nest, inside the mortality detector's box, until it fledges. This
module splits each track at its **first departure**: the first fix more
than a radius from where the tag started (the median position of its
first fixes). Alerts and tracked time are counted on each side, so the
load the nest period adds can be read off before deciding whether to
treat that period differently.

The split describes alerts, not errors: every incident is counted, whether
or not the bird later proved dead, because no outcome labels are used. A
bird that died in the nest counts on the "before" side.

The radius and the number of anchoring fixes are provisional descriptive
choices, not detector settings; two radii are reported so the conclusion
can be seen not to hang on one.

Since step 3.1 (a) the detector itself marks watch alerts raised at the
natal nest (context ``natal_nest``). ``context_split`` counts the load
with and without them, and, on labelled birds, how many on each side
were right, so the cost of the marking (deaths caught only at the nest)
is shown beside the load it moves.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from telemetry.analysis.evaluation import ALIVE, DEAD, Truth, classify
from telemetry.core.alerts import MORTALITY, NATAL_NEST, Incident
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


def context_split(
    truths: list[Truth], incidents: list[Incident], animal_month: timedelta
) -> dict:
    """Watch load with and without natal-nest alerts, and how many were right.

    Args:
        truths: What is known about each of one population's birds.
        incidents: Every incident that population's replay raised.
        animal_month: Length of an animal-month.

    Returns:
        dict: Watch (mortality) alerts in all and at the natal nest, the
        rate per animal-month with and without them, true and false counts
        on each side for birds labelled dead or alive, and how many dead
        birds with a true alert had them only at the natal nest.
    """
    months = sum((t.last_fix - t.first_fix) / animal_month for t in truths)
    by_id = {truth.deployment_id: truth for truth in truths}
    watch = [i for i in incidents if i.detector == MORTALITY]
    at_nest = sum(1 for i in watch if i.context == NATAL_NEST)
    right = {side: {"true": 0, "false": 0} for side in ("natal_nest", "other")}
    true_sides: dict[str, set[str]] = defaultdict(set)
    for incident in watch:
        truth = by_id.get(incident.deployment_id)
        # Ambiguous birds and tag events cannot call an alert right or
        # wrong, as in the acceleration cue's cases.
        if truth is None or truth.label not in (DEAD, ALIVE):
            continue
        side = "natal_nest" if incident.context == NATAL_NEST else "other"
        kind = "true" if classify(truth, incident) == "true" else "false"
        right[side][kind] += 1
        if kind == "true":
            true_sides[incident.deployment_id].add(side)
    return {
        "animal_months": round(months, 1),
        "watch": len(watch),
        "at_natal_nest": at_nest,
        "per_animal_month_all": _rate(len(watch), months),
        "per_animal_month_without_nest": _rate(len(watch) - at_nest, months),
        "labelled": right,
        "deaths_alerted": len(true_sides),
        "deaths_only_at_nest": sum(
            1 for sides in true_sides.values() if sides == {"natal_nest"}
        ),
    }


def markdown(sets: list[dict], scenario: str) -> str:
    """The first-departure tables.

    Args:
        sets: One entry per population, as ``scripts/fledging.py`` writes
            them: ``study``, ``title``, ``radii`` (``measure`` results) and
            ``context`` (``context_split``'s result).
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
    lines += [
        "",
        "## Watch alerts marked at the natal nest",
        "",
        "The mortality detector marks a watch alert `natal_nest` when the bird",
        "has never left where its track began, or is back within 500 m of it in",
        "its first year (`telemetry.core.detectors.mortality`). Marked alerts are",
        "still raised; this table counts them apart. True and false use the",
        "labels, on birds labelled dead or alive only. *Deaths only at the nest*",
        "are dead birds whose every true alert was marked: they are the cost of",
        "anyone ignoring marked alerts.",
        "",
        "| Population | Watch alerts | At natal nest | Per animal-month, all "
        "| Per animal-month, unmarked | At nest, true / false "
        "| Elsewhere, true / false | Deaths only at the nest (of alerted) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for entry in sets:
        split = entry["context"]
        nest, other = split["labelled"]["natal_nest"], split["labelled"]["other"]
        lines.append(
            f"| {entry['title']} | {split['watch']} | {split['at_natal_nest']} "
            f"| {split['per_animal_month_all']} "
            f"| {split['per_animal_month_without_nest']} "
            f"| {nest['true']} / {nest['false']} | {other['true']} / {other['false']} "
            f"| {split['deaths_only_at_nest']} ({split['deaths_alerted']}) |"
        )
    return "\n".join(lines) + "\n"
