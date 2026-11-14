"""Living still bouts: how often animals that are alive stay put, and for how long.

The mortality detector reads a long stationary cluster as a possible
death, so its false-alert rate is set by how often living animals stay
still for longer than its window. This module measures that tail per
species and tag type, so a window can be judged against it rather than
against a typical night's rest.

A bout is one of the detector's own clusters (its box and minimum fix
count), found by running the detector with no window: nothing alerts, so
every cluster runs until the animal leaves it. Fixes go in as loaded,
before the cleaner, as in the post-mortem check this reproduces. The final
stationary period of a dead or ambiguous track is left out, since it may
be a carcass; every other bout is a living one.

Rates are per animal-month, counted from first to last fix over every
deployment in the set (carcass tails included), the same denominator as
the evaluation's false-alert load.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from telemetry.analysis.evaluation import (
    AMBIGUOUS,
    ANIMAL_MONTH,
    DEAD,
    HOUR,
    TAG_EVENT,
    Truth,
)
from telemetry.core.detectors.mortality import MortalityConfig, MortalityDetector
from telemetry.core.fixes import Fix
from telemetry.core.species import profile_for

# The plan's four marks, plus the jackal (24 h) and elephant (12 h)
# windows so the mammals can be read against their own setting.
THRESHOLDS_H = (12, 24, 36, 48, 72, 168)
# Points for the tail figure, log-spaced by eye from half a day to a month.
CURVE_H = (12, 18, 24, 36, 48, 72, 96, 120, 168, 240, 336, 504, 720)
# Long enough that no cluster in any study reaches it, so nothing alerts.
NO_WINDOW = timedelta(days=10_000)


@dataclass(frozen=True)
class Bout:
    """One stationary cluster.

    Attributes:
        start: Time of its first fix.
        end: Time of its last fix.
        fixes: How many fixes it holds.
    """

    start: datetime
    end: datetime
    fixes: int

    @property
    def hours(self) -> float:
        """Length from first to last fix.

        Returns:
            float: Hours.
        """
        return (self.end - self.start) / HOUR


def still_bouts(fixes: list[Fix], config: MortalityConfig) -> list[Bout]:
    """Every stationary cluster in one deployment, under the detector's rule.

    Args:
        fixes: One deployment's fixes, in time order.
        config: The species' mortality settings; only the box and the
            leave rule matter, as the window is replaced.

    Returns:
        list[Bout]: Clusters in time order, of any length or fix count.
    """
    detector = MortalityDetector(replace(config, window=NO_WINDOW, leave_radius_m=None))
    state: dict = {}
    bouts = []

    def close(cluster: dict) -> None:
        """Record a finished cluster.

        Args:
            cluster: Cluster state as the detector keeps it.
        """
        bouts.append(
            Bout(
                datetime.fromisoformat(cluster["start"]),
                datetime.fromisoformat(cluster["last"]),
                cluster["n"],
            )
        )

    for fix in fixes:
        before = state.get("cluster")
        detector.on_fix(state, fix.deployment_id, fix)
        # The detector replaces the cluster object when the animal leaves;
        # an identity check sees that without reaching into its internals.
        if before is not None and state["cluster"] is not before:
            close(before)
    if state.get("cluster"):
        close(state["cluster"])
    return bouts


def living_bouts(truth: Truth, fixes: list[Fix]) -> list[float]:
    """Lengths of one deployment's living still bouts.

    Args:
        truth: What is known about the deployment.
        fixes: Its fixes, in time order.

    Returns:
        list[float]: Hours of each bout ``living_still_bouts`` keeps.
    """
    return [bout.hours for bout in living_still_bouts(truth, fixes)]


def living_still_bouts(truth: Truth, fixes: list[Fix]) -> list[Bout]:
    """One deployment's living still bouts, with their times.

    Args:
        truth: What is known about the deployment.
        fixes: Its fixes, in time order.

    Returns:
        list[Bout]: Every bout with at least the detector's minimum fixes
        that is not part of a possible carcass period or a tag event, in
        time order.
    """
    config = profile_for(truth.taxon).mortality
    return [
        bout
        for bout in still_bouts(fixes, config)
        if bout.fixes >= config.min_fixes
        and not (
            truth.label in (DEAD, AMBIGUOUS, TAG_EVENT)
            and bout.end > truth.outcome_start
        )
    ]


def _beyond(hours: list[float], months: float, threshold: float) -> dict:
    """Living bouts longer than ``threshold``, as a count and a rate.

    Args:
        hours: Bout lengths.
        months: Animal-months they come from.
        threshold: Hours.

    Returns:
        dict: ``hours``, ``count`` and ``per_animal_month``.
    """
    count = sum(h > threshold for h in hours)
    return {
        "hours": threshold,
        "count": count,
        "per_animal_month": round(count / months, 4),
    }


def tail(truths: list[Truth], bouts: dict[str, list[float]]) -> dict:
    """The living still-bout tail of a group of deployments.

    Args:
        truths: The group's deployments.
        bouts: Living bout lengths by deployment ID.

    Returns:
        dict: Deployments, animal-months, the window the group's species
        uses, bouts beyond each of ``THRESHOLDS_H`` and that window, the
        curve for the figure and the longest bout.
    """
    months = sum((t.last_fix - t.first_fix) / ANIMAL_MONTH for t in truths)
    hours = [h for t in truths for h in bouts[t.deployment_id]]
    # Every group is a single taxon or the vultures, which share a window.
    window = profile_for(truths[0].taxon).mortality.window / HOUR
    return {
        "deployments": len(truths),
        "animal_months": round(months, 1),
        "window_hours": window,
        "beyond": [_beyond(hours, months, h) for h in THRESHOLDS_H],
        "beyond_window": _beyond(hours, months, window),
        "curve": [_beyond(hours, months, h) for h in CURVE_H],
        "longest_hours": round(max(hours, default=0.0), 1),
    }


def measure(
    truths: list[Truth],
    fixes: list[Fix],
    tag_models: dict[str, str],
) -> dict:
    """Living still-bout tails for one set, overall and by species and tag.

    Args:
        truths: The set's deployments.
        fixes: Their fixes, in any order.
        tag_models: Tag model by deployment ID.

    Returns:
        dict: ``groups``, one row each for the whole set, each taxon and
        each taxon and tag model (the last two only where they split the
        set), and ``carcasses``: the set's carcass periods in hours and
        their rate per animal-month, for comparison with the living tail.
    """
    by_deployment: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_deployment.setdefault(fix.deployment_id, []).append(fix)
    bouts = {
        t.deployment_id: living_bouts(
            t, sorted(by_deployment[t.deployment_id], key=lambda f: f.timestamp)
        )
        for t in truths
    }

    def group(taxon: str | None, model: str | None, members: list[Truth]) -> dict:
        """One row, naming every tag model its members wear.

        Args:
            taxon: The row's taxon, or None for every taxon.
            model: The row's tag model, or None for every model.
            members: Its deployments.

        Returns:
            dict: The row, with the taxa and tag models its members cover.
        """
        return {
            "taxon": taxon,
            "tag_model": model,
            "taxa": sorted({t.taxon for t in members}),
            "tag_models": sorted({tag_models[t.deployment_id] for t in members}),
            **tail(members, bouts),
        }

    groups = [group(None, None, truths)]
    taxa = sorted({t.taxon for t in truths})
    for taxon in taxa:
        own = [t for t in truths if t.taxon == taxon]
        models = sorted({tag_models[t.deployment_id] for t in own})
        if len(taxa) > 1:
            groups.append(group(taxon, None, own))
        if len(models) > 1:
            for model in models:
                tagged = [t for t in own if tag_models[t.deployment_id] == model]
                groups.append(group(taxon, model, tagged))

    carcasses = sorted(
        round(t.still_hours, 1) for t in truths if t.label == DEAD and t.carcass
    )
    months = sum((t.last_fix - t.first_fix) / ANIMAL_MONTH for t in truths)
    return {
        "groups": groups,
        "carcasses": {
            "hours": carcasses,
            "per_animal_month": round(len(carcasses) / months, 4),
        },
    }
