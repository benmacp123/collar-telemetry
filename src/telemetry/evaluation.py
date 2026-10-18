"""Score replayed incidents against what is known about each deployment.

The replay runner says what the pipeline raised; this module says how
good that was. Everything here follows the evaluation decisions in the
project plan:

- **Labels.** A deployment is ``dead`` if its end type says so or
  ``data/labels.csv`` overrides it; ``dead-after-track`` (the animal died
  after the collar stopped) counts as alive for every fix the pipeline
  saw. Other unplanned ends whose track finishes with a stationary period
  at least the species' mortality window long are ``ambiguous``
  (possible unrecorded deaths or dropped tags): they are reported apart
  and left out of the false-alarm count. Everything else is ``alive``.
- **Split.** Vulture deployments starting before 2013 are the tuning set
  and those from 2013 on the scoring set; the mammal studies are not
  split. Callers choose which sets to score, so the scoring set can stay
  unseen until thresholds are frozen.
- **Death start** is the start of the track's final stationary period:
  the earliest fix from which every later fix lies within ``radius_m``
  of the median of the last ``TAIL_FIXES`` fixes. 100 m matches the
  observed carcass scatter; 200 m is reported as a sensitivity check.
- **Carcass deaths** (final stationary period at least the species'
  mortality window) are mortality-detector cases. A mortality incident
  still open after the death start detects it, even if it was raised
  earlier; its delay is ``raised_at`` minus death start, floored at 0,
  and early detections are counted. Deaths with a shorter stationary end
  (shot, struck, electrocuted) are gap-detector cases, scored from the
  last fix to the gap incident still open at the end of the replay.
- **Operator load** is incidents per animal-month, where an animal-month
  is 30.4375 days of track between first and last fix.

Times are on the processing clock (``raised_at``), so upload batching
shows in every delay.
"""

import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telemetry.alerts import LATE_FIX, OPEN, Incident
from telemetry.fixes import Deployment, Fix
from telemetry.geo import haversine_m
from telemetry.replay import PLANNED_ENDS
from telemetry.species import profile_for

DEAD = "dead"
DEAD_AFTER_TRACK = "dead-after-track"
AMBIGUOUS = "ambiguous"
ALIVE = "alive"
LABELS = (DEAD, DEAD_AFTER_TRACK, AMBIGUOUS, ALIVE)
DEAD_END_TYPES = frozenset({"dead", "dead/fall-off"})

TUNING = "tuning"
SCORING = "scoring"
ALL = "all"
SPLIT_STUDIES = frozenset({"vultures"})
SCORING_FROM = datetime(2013, 1, 1, tzinfo=timezone.utc)

STILL_RADIUS_M = 100.0
SENSITIVITY_RADIUS_M = 200.0
TAIL_FIXES = 5
ANIMAL_MONTH = timedelta(days=30.4375)
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class Truth:
    """What is known about one deployment, for scoring.

    Attributes:
        deployment_id: The deployment.
        taxon: Its taxon, which sets the mortality window.
        label: One of ``LABELS``.
        split: ``TUNING``, ``SCORING`` or ``ALL``.
        first_fix: Time of its first fix.
        last_fix: Time of its last fix.
        still_start: Start of the final stationary period at
            ``STILL_RADIUS_M``.
        still_start_wide: The same at ``SENSITIVITY_RADIUS_M``.
        window: The species' mortality detector window.
    """

    deployment_id: str
    taxon: str
    label: str
    split: str
    first_fix: datetime
    last_fix: datetime
    still_start: datetime
    still_start_wide: datetime
    window: timedelta

    @property
    def still_hours(self) -> float:
        """Length of the final stationary period at ``STILL_RADIUS_M``.

        Returns:
            float: Hours from death start to the last fix.
        """
        return (self.last_fix - self.still_start) / HOUR

    @property
    def carcass(self) -> bool:
        """Whether the final stationary period is long enough for the
        mortality detector to see.

        Returns:
            bool: True if it lasts at least the mortality window.
        """
        return self.last_fix - self.still_start >= self.window


def read_labels(path: Path) -> dict[str, str]:
    """Read label overrides.

    Args:
        path: ``data/labels.csv``, with ``deployment-id`` and ``label``
            columns.

    Returns:
        dict[str, str]: Label by deployment ID.

    Raises:
        ValueError: If a label is not one of ``DEAD`` or
            ``DEAD_AFTER_TRACK``, the only overrides the label review
            produces.
    """
    labels = {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            label = row["label"].strip()
            if label not in (DEAD, DEAD_AFTER_TRACK):
                raise ValueError(f"unexpected label {label!r} in {path}")
            labels[row["deployment-id"].strip()] = label
    return labels


def final_still_start(fixes: list[Fix], radius_m: float) -> datetime:
    """Start of a track's final stationary period.

    Args:
        fixes: The deployment's fixes in time order; not empty.
        radius_m: Distance from the final position allowed per fix.

    Returns:
        datetime: The earliest fix time from which every later fix lies
        within ``radius_m`` of the median of the last ``TAIL_FIXES``
        fixes. The last fix's time if even it lies outside, which only
        happens when the tail is badly scattered.
    """
    tail = fixes[-TAIL_FIXES:]
    lat = statistics.median(f.lat for f in tail)
    lon = statistics.median(f.lon for f in tail)
    start = fixes[-1].timestamp
    for fix in reversed(fixes):
        if haversine_m(lat, lon, fix.lat, fix.lon) > radius_m:
            break
        start = fix.timestamp
    return start


def split_for(study: str, deployment: Deployment) -> str:
    """Which evaluation set a deployment belongs to.

    Args:
        study: Study slug.
        deployment: The deployment.

    Returns:
        str: ``TUNING`` or ``SCORING`` for split studies, else ``ALL``.
    """
    if study not in SPLIT_STUDIES:
        return ALL
    return TUNING if deployment.deploy_on < SCORING_FROM else SCORING


def label_for(
    deployment: Deployment,
    overrides: dict[str, str],
    still: timedelta,
    window: timedelta,
) -> str:
    """A deployment's label.

    Args:
        deployment: The deployment.
        overrides: Label overrides by deployment ID.
        still: Length of the track's final stationary period.
        window: The species' mortality window.

    Returns:
        str: One of ``LABELS``.
    """
    if deployment.deployment_id in overrides:
        return overrides[deployment.deployment_id]
    if deployment.end_type in DEAD_END_TYPES:
        return DEAD
    if deployment.end_type in PLANNED_ENDS:
        return ALIVE
    return AMBIGUOUS if still >= window else ALIVE


def build_truth(
    study: str,
    deployments: list[Deployment],
    fixes: list[Fix],
    overrides: dict[str, str],
) -> list[Truth]:
    """What is known about every deployment that has fixes.

    Args:
        study: Study slug, which decides the split.
        deployments: The study's deployments.
        fixes: Their fixes, in any order.
        overrides: Label overrides by deployment ID.

    Returns:
        list[Truth]: One per deployment with fixes, by deployment ID.

    Raises:
        KeyError: If a deployment's taxon has no species profile.
    """
    by_deployment: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_deployment.setdefault(fix.deployment_id, []).append(fix)

    truths = []
    for deployment in sorted(deployments, key=lambda d: d.deployment_id):
        own = sorted(
            by_deployment.get(deployment.deployment_id, []), key=lambda f: f.timestamp
        )
        if not own:
            continue
        window = profile_for(deployment.taxon).mortality.window
        still_start = final_still_start(own, STILL_RADIUS_M)
        truths.append(
            Truth(
                deployment_id=deployment.deployment_id,
                taxon=deployment.taxon,
                label=label_for(
                    deployment, overrides, own[-1].timestamp - still_start, window
                ),
                split=split_for(study, deployment),
                first_fix=own[0].timestamp,
                last_fix=own[-1].timestamp,
                still_start=still_start,
                still_start_wide=final_still_start(own, SENSITIVITY_RADIUS_M),
                window=window,
            )
        )
    return truths


def read_incidents(path: Path) -> list[Incident]:
    """Read an ``incidents.jsonl`` file written by the replay script.

    Args:
        path: The file.

    Returns:
        list[Incident]: Its incidents, in file order.
    """
    with open(path, encoding="utf-8") as handle:
        return [Incident.from_dict(json.loads(line)) for line in handle if line.strip()]


def _hours(delta: timedelta) -> float:
    """A duration in hours, rounded for stable JSON.

    Args:
        delta: The duration.

    Returns:
        float: Hours, to 0.01 h.
    """
    return round(delta / HOUR, 2)


def mortality_detection(
    death_start: datetime, incidents: list[Incident]
) -> tuple[float, bool] | None:
    """How quickly a death was flagged by the mortality detector.

    Args:
        death_start: Start of the final stationary period.
        incidents: The deployment's mortality incidents.

    Returns:
        tuple[float, bool] | None: Delay in hours (floored at 0) and
        whether the detecting incident was raised before the death start;
        None if no incident was open after the death start. An incident
        resolved exactly at the death start was ended by the move to the
        death site, so it does not count.
    """
    candidates = [
        i.raised_at
        for i in incidents
        if i.raised_at is not None
        and (i.resolved_at is None or i.resolved_at > death_start)
    ]
    if not candidates:
        return None
    raised = min(candidates)
    return max(0.0, _hours(raised - death_start)), raised < death_start


def gap_detection(last_fix: datetime, incidents: list[Incident]) -> float | None:
    """How quickly a collar's final silence was flagged.

    Args:
        last_fix: Time of the deployment's last fix.
        incidents: The deployment's gap incidents.

    Returns:
        float | None: Hours from the last fix to the gap incident still
        open at the end of the replay, or None if there is none.
    """
    final = [i for i in incidents if i.status == OPEN and i.raised_at is not None]
    if not final:
        return None
    return _hours(min(i.raised_at for i in final) - last_fix)


def false_mortality(truth: Truth, incidents: list[Incident]) -> int:
    """Mortality incidents raised while the animal was known or assumed
    alive.

    Args:
        truth: The deployment.
        incidents: Its mortality incidents.

    Returns:
        int: Every incident for an alive deployment; for dead and
        ambiguous ones, those resolved by the death start (raised while the
        animal was still moving about).
    """
    if truth.label in (ALIVE, DEAD_AFTER_TRACK):
        return len(incidents)
    return sum(
        1
        for i in incidents
        if i.resolved_at is not None and i.resolved_at <= truth.still_start
    )


def detection_rate(delays: list[float | None], deadline_hours: float) -> float | None:
    """Share of deaths flagged within a deadline.

    Args:
        delays: Delay in hours per death, None where missed.
        deadline_hours: The deadline.

    Returns:
        float | None: The share, to 0.001, or None if there are no deaths.
    """
    if not delays:
        return None
    hit = sum(1 for d in delays if d is not None and d <= deadline_hours)
    return round(hit / len(delays), 3)


def reference_mark(truths: list[Truth]) -> float | None:
    """Median length of the observed carcass periods.

    Used as the reference deadline on delay curves: by then half of
    carcass collars have stopped reporting.

    Args:
        truths: Deployments to measure, normally the vulture tuning set.

    Returns:
        float | None: Median hours, or None if there are no carcass deaths.
    """
    periods = [t.still_hours for t in truths if t.label == DEAD and t.carcass]
    return round(statistics.median(periods), 1) if periods else None


def evaluate(
    truths: list[Truth], incidents: list[Incident], mark_hours: float | None
) -> dict:
    """Score one scenario's incidents on one set of deployments.

    Args:
        truths: The deployments to score.
        incidents: Every incident the replay raised; those for other
            deployments are ignored.
        mark_hours: Reference deadline for the summary rate, or None.

    Returns:
        dict: JSON-ready operator load, false mortality alerts, per-death
        detection, ambiguous tracks and cross-detector overlap.
    """
    ids = {t.deployment_id for t in truths}
    own: dict[tuple[str, str], list[Incident]] = {}
    for incident in incidents:
        if incident.deployment_id in ids:
            own.setdefault((incident.deployment_id, incident.detector), []).append(
                incident
            )

    months = sum((t.last_fix - t.first_fix) / ANIMAL_MONTH for t in truths)
    load = _load(own, months)
    false_alarms = sum(
        false_mortality(t, own.get((t.deployment_id, "mortality"), [])) for t in truths
    )

    deaths, ambiguous = [], []
    for truth in truths:
        mortality = own.get((truth.deployment_id, "mortality"), [])
        if truth.label == DEAD:
            deaths.append(_death_record(truth, mortality, own))
        elif truth.label == AMBIGUOUS:
            found = mortality_detection(truth.still_start, mortality)
            ambiguous.append(
                {
                    "deployment_id": truth.deployment_id,
                    "still_hours": round(truth.still_hours, 1),
                    "mortality_delay_hours": found[0] if found else None,
                }
            )

    carcass = [d for d in deaths if d["carcass"]]
    no_carcass = [d for d in deaths if not d["carcass"]]
    delays = [d["mortality_delay_hours"] for d in carcass]
    wide = [d["mortality_delay_hours_200m"] for d in carcass]
    return {
        "deployments": len(truths),
        "labels": dict(sorted(Counter(t.label for t in truths).items())),
        "animal_months": round(months, 1),
        "load": load,
        "false_mortality": {
            "incidents": false_alarms,
            "per_animal_month": _rate(false_alarms, months),
        },
        "mortality": {
            "deaths": len(carcass),
            "detected": sum(1 for d in delays if d is not None),
            "early": sum(1 for d in carcass if d["early"]),
            "mark_hours": mark_hours,
            "rate_at_mark": (
                detection_rate(delays, mark_hours) if mark_hours is not None else None
            ),
            "rate_at_mark_200m": (
                detection_rate(wide, mark_hours) if mark_hours is not None else None
            ),
        },
        "gap_on_deaths": {
            "deaths": len(no_carcass),
            "detected": sum(1 for d in no_carcass if d["gap_delay_hours"] is not None),
            "median_delay_hours": _median(d["gap_delay_hours"] for d in no_carcass),
        },
        "both_detectors": sum(
            1
            for d in deaths
            if d["mortality_delay_hours"] is not None
            and d["gap_delay_hours"] is not None
        ),
        "deaths": deaths,
        "ambiguous": ambiguous,
    }


def _death_record(
    truth: Truth, mortality: list[Incident], own: dict[tuple[str, str], list]
) -> dict:
    """Detection results for one death.

    Args:
        truth: The dead deployment.
        mortality: Its mortality incidents.
        own: All scored incidents by (deployment, detector).

    Returns:
        dict: Carcass period, mortality delay at both radii and gap delay.
    """
    found = mortality_detection(truth.still_start, mortality)
    found_wide = mortality_detection(truth.still_start_wide, mortality)
    return {
        "deployment_id": truth.deployment_id,
        "carcass": truth.carcass,
        "still_hours": round(truth.still_hours, 1),
        "still_hours_200m": round((truth.last_fix - truth.still_start_wide) / HOUR, 1),
        "mortality_delay_hours": found[0] if found else None,
        "early": bool(found and found[1]),
        "mortality_delay_hours_200m": found_wide[0] if found_wide else None,
        "gap_delay_hours": gap_detection(
            truth.last_fix, own.get((truth.deployment_id, "gap"), [])
        ),
    }


def _load(own: dict[tuple[str, str], list[Incident]], months: float) -> dict:
    """Incidents per animal-month by detector.

    Args:
        own: Incidents by (deployment, detector).
        months: Animal-months tracked.

    Returns:
        dict: Per detector, incident and late-fix counts and the rate.
    """
    counts: dict[str, Counter] = {}
    for (_, detector), incidents in own.items():
        tally = counts.setdefault(detector, Counter())
        tally["incidents"] += len(incidents)
        tally["late_fix"] += sum(1 for i in incidents if i.resolution == LATE_FIX)
    return {
        detector: {
            "incidents": tally["incidents"],
            "late_fix": tally["late_fix"],
            "per_animal_month": _rate(tally["incidents"], months),
        }
        for detector, tally in sorted(counts.items())
    }


def _rate(count: int, months: float) -> float | None:
    """A count per animal-month.

    Args:
        count: The count.
        months: Animal-months tracked.

    Returns:
        float | None: The rate to 0.001, or None with no tracking time.
    """
    return round(count / months, 3) if months else None


def _median(values) -> float | None:
    """Median of the values that are not None.

    Args:
        values: Numbers or None.

    Returns:
        float | None: The median, or None if there are none.
    """
    present = [v for v in values if v is not None]
    return round(statistics.median(present), 2) if present else None
