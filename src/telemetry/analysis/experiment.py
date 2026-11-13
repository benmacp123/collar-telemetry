"""The experiment definition: one committed file every analysis reads.

``config/experiment.toml`` holds set membership, how truth and metrics are
defined, the sweep grid and the targets, so that what a result is judged
against cannot differ between the sweep and the evaluation, or be chosen after
the result is known.

The detection core does not read it: the deployed Lambda carries no analysis
files, so ``telemetry.core`` stays the source of what the detectors run, and
the file quotes those values under ``[thresholds]`` with a test against drift.

Standard library only, so every other analysis module can import this one.
"""

import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

EXPERIMENT_PATH = Path(__file__).resolve().parents[3] / "config" / "experiment.toml"

LOAD = "load"
CLEAR_HOURS = "clear_hours"
RATE_AT_MARK = "rate_at_mark"
WILSON_LOWER = "wilson_lower"
CUE_PRECISION = "cue_precision"
METRIC_NAMES = {
    LOAD: "Load",
    CLEAR_HOURS: "Median time to clear on living birds",
    RATE_AT_MARK: "Carcasses flagged by the mark",
    WILSON_LOWER: "Precision, Wilson 95% lower bound",
    CUE_PRECISION: "Precision, keeping at least half the carcasses",
}
BOUNDS = ("at_most", "at_least", "above")
FRESH = "fresh"
BIRDS = 30
WEEK_DAYS = 7


@dataclass(frozen=True)
class Target:
    """One target fixed in advance.

    Attributes:
        tier: The alert tier, as printed.
        alert: The detector or cue the target applies to.
        metric: Which measure, one of ``METRIC_NAMES``.
        bound: ``at_most``, ``at_least`` or ``above``.
        value: The limit as the file writes it (for load, per 30 birds per
            week).
        limit: The same limit in the unit the metric is measured in.
        judged_on: Kinds of set the target is judged on.
    """

    tier: str
    alert: str
    metric: str
    bound: str
    value: float
    limit: float
    judged_on: tuple[str, ...]

    def met(self, measured: float) -> bool:
        """Whether a measured value meets the target.

        Args:
            measured: The value, in the metric's own unit.

        Returns:
            bool: True if it is within the limit.
        """
        if self.bound == "at_most":
            return measured <= self.limit
        if self.bound == "at_least":
            return measured >= self.limit
        return measured > self.limit

    def describe(self) -> str:
        """The target in words, for a table cell.

        Returns:
            str: For example "at most 12 h".
        """
        words = self.bound.replace("_", " ")
        if self.metric == LOAD:
            return (
                f"{words} {self.value:g} per {BIRDS} birds per week "
                f"({self.limit:.3f} per animal-month)"
            )
        if self.metric == CLEAR_HOURS:
            return f"{words} {self.value:g} h"
        return f"{words} {self.value:.0%}"

    def limit_text(self) -> str:
        """The limit in the unit measured, for a cell beside a measured value.

        Returns:
            str: For example "at most 0.435" for a load target; otherwise
            the same as ``describe``.
        """
        if self.metric == LOAD:
            return f"{self.bound.replace('_', ' ')} {self.limit:.3f}"
        return self.describe()

    def verdict(self, measured: float | None, set_kind: str) -> str:
        """The outcome to print beside a measured value.

        A target is only ever judged on the kinds of set it names, so a
        pass on a set already looked at can never be read as validation.

        Args:
            measured: The value, or None if it was not measured.
            set_kind: The kind of set scored.

        Returns:
            str: ``met``, ``missed``, ``not measured`` or a statement that
            this set does not judge the target.
        """
        if set_kind not in self.judged_on:
            return f"not judged on {set_kind} set"
        if measured is None:
            return "not measured"
        return "met" if self.met(measured) else "missed"


@dataclass(frozen=True)
class Experiment:
    """The parsed experiment file.

    Attributes:
        animal_month: Length of an animal-month.
        tag_event_correct: Alerts a tag event correctly explains.
        wilson_z: Normal quantile for the Wilson interval.
        bootstrap_resamples: Resamples in the clustered bootstrap.
        bootstrap_seed: Its seed.
        still_radius_m: Radius defining the final stationary period.
        sensitivity_radius_m: The same, for the sensitivity check.
        tail_fixes: Fixes whose median anchors that period.
        reference_mark_hours: The mark the targets name, as quoted.
        carcass_min: Shortest carcass period by taxon.
        studies: The file's ``[studies]`` table.
        thresholds: The file's ``[thresholds]`` table.
        mortality_windows: Windows the sweep tries.
        mortality_boxes_m: Boxes the sweep tries.
        upload_margins: Upload margins the sweep tries.
        species_taxon: The species whose window is swept on its own.
        species_windows: Windows tried for it, every other species at its
            own window.
        animal_months_per_carcass: Base rate for the arithmetic note.
        false_per_animal_month: Current false rate for the arithmetic note.
        precisions: Precisions the arithmetic note works through.
        cues: The file's ``[cues]`` table, one entry per escalation cue.
        targets: Every target, in the file's order.
    """

    animal_month: timedelta
    tag_event_correct: frozenset[str]
    wilson_z: float
    bootstrap_resamples: int
    bootstrap_seed: int
    still_radius_m: float
    sensitivity_radius_m: float
    tail_fixes: int
    reference_mark_hours: float
    carcass_min: dict[str, timedelta]
    studies: dict
    thresholds: dict
    mortality_windows: tuple[timedelta, ...]
    mortality_boxes_m: tuple[float, ...]
    upload_margins: tuple[timedelta, ...]
    species_taxon: str
    species_windows: tuple[timedelta, ...]
    animal_months_per_carcass: float
    false_per_animal_month: float
    precisions: tuple[float, ...]
    cues: dict
    targets: tuple[Target, ...]

    def scoring_from(self, study: str) -> datetime | None:
        """When a study's date-split scoring set starts.

        Args:
            study: Study slug.

        Returns:
            datetime | None: The date, or None if the study has no date
            split, in which case its deployments are not split.
        """
        return self.studies.get(study, {}).get("scoring_from")

    def set_kind(self, study: str, name: str) -> str | None:
        """What kind of set a study's set is.

        Args:
            study: Study slug.
            name: The set's name, such as ``tuning``.

        Returns:
            str | None: ``tuning``, ``seen`` or ``fresh``; None if the set
            is not in the file, in which case no target applies to it.
        """
        return self.studies.get(study, {}).get("sets", {}).get(name)

    def is_fresh(self, study: str, name: str | None) -> bool:
        """Whether a set is held out and still unseen.

        Nothing but the scoring run may replay or score a fresh set, so
        every routine script asks this before loading one.

        Args:
            study: Study slug, or the group its populations share.
            name: The set's name; None for a study that is not split.

        Returns:
            bool: True if the file marks the set ``fresh``.
        """
        return name is not None and self.set_kind(study, name) == FRESH

    def scenario(self, study: str) -> str | None:
        """The upload scenario a study's targets are judged under.

        Args:
            study: Study slug.

        Returns:
            str | None: The scenario, or None if none is named yet.
        """
        return self.studies.get(study, {}).get("scenario")

    def targets_for(self, alert: str) -> tuple[Target, ...]:
        """The targets on one alert.

        Args:
            alert: The detector or cue.

        Returns:
            tuple[Target, ...]: Its targets, in the file's order.
        """
        return tuple(t for t in self.targets if t.alert == alert)

    def false_rate_allowed(self, precision: float) -> float:
        """Most false alerts per animal-month a precision allows.

        Args:
            precision: The precision, above 0.

        Returns:
            float: The false-alert rate at the file's base rate, if every
            carcass raises one true alert.
        """
        return (1 - precision) / precision / self.animal_months_per_carcass


def _hours(values) -> tuple[timedelta, ...]:
    """Hours as durations.

    Args:
        values: Numbers of hours.

    Returns:
        tuple[timedelta, ...]: The durations, in the same order.
    """
    return tuple(timedelta(hours=v) for v in values)


def _target(entry: dict, animal_month: timedelta) -> Target:
    """Parse one ``[[targets]]`` entry.

    Args:
        entry: The entry.
        animal_month: Length of an animal-month, to convert load limits.

    Returns:
        Target: The parsed target.

    Raises:
        ValueError: If the metric is unknown, or the entry does not give
            exactly one bound, since a typo here would silently change
            what counts as a pass.
    """
    metric = entry["metric"]
    if metric not in METRIC_NAMES:
        raise ValueError(f"unknown metric {metric!r} in the experiment file")
    bounds = [b for b in BOUNDS if b in entry]
    if len(bounds) != 1:
        raise ValueError(f"target {metric!r} needs exactly one of {BOUNDS}")
    bound = bounds[0]
    value = entry[bound]
    limit = value
    if metric == LOAD:
        limit = value * (animal_month / timedelta(days=WEEK_DAYS)) / BIRDS
    return Target(
        tier=entry["tier"],
        alert=entry["alert"],
        metric=metric,
        bound=bound,
        value=value,
        limit=limit,
        judged_on=tuple(entry["judged_on"]),
    )


@cache
def experiment() -> Experiment:
    """The experiment file, parsed once per process.

    Returns:
        Experiment: The contents of ``EXPERIMENT_PATH``.
    """
    with EXPERIMENT_PATH.open("rb") as file:
        raw = tomllib.load(file)
    metrics, truth, sweep, arithmetic = (
        raw["metrics"],
        raw["truth"],
        raw["sweep"],
        raw["arithmetic"],
    )
    animal_month = timedelta(days=metrics["animal_month_days"])
    return Experiment(
        animal_month=animal_month,
        tag_event_correct=frozenset(metrics["tag_event_correct"]),
        wilson_z=metrics["wilson_z"],
        bootstrap_resamples=metrics["bootstrap_resamples"],
        bootstrap_seed=metrics["bootstrap_seed"],
        still_radius_m=truth["still_radius_m"],
        sensitivity_radius_m=truth["sensitivity_radius_m"],
        tail_fixes=truth["tail_fixes"],
        reference_mark_hours=truth["reference_mark_hours"],
        carcass_min={
            taxon: timedelta(hours=hours)
            for taxon, hours in truth["carcass_min_hours"].items()
        },
        studies=raw["studies"],
        thresholds=raw["thresholds"],
        mortality_windows=_hours(sweep["mortality_windows_hours"]),
        mortality_boxes_m=tuple(sweep["mortality_boxes_m"]),
        upload_margins=_hours(sweep["upload_margins_hours"]),
        species_taxon=sweep["species"]["taxon"],
        species_windows=_hours(sweep["species"]["windows_hours"]),
        animal_months_per_carcass=arithmetic["animal_months_per_carcass"],
        false_per_animal_month=arithmetic["false_per_animal_month"],
        precisions=tuple(arithmetic["precisions"]),
        cues=raw.get("cues", {}),
        targets=tuple(_target(entry, animal_month) for entry in raw["targets"]),
    )
