"""Replay a study's fixes through the detection core under one arrival
scenario.

This is the local runner every reported result comes from. It needs no
AWS account: fixes are read from committed files, arrival is simulated
with a fixed seed, and the same ``FixStream`` core the Lambda handlers
wrap does the detection.

Deployments are independent, so each one's timeline runs on its own
through ``FixStream.advance``, the same function the cloud handler calls
with one slice at a time. Each fix is ingested at its arrival time, which
becomes the incident's ``raised_at``, so detection delay reflects upload
batching. Between arrivals the clock ticks every ``tick`` (hourly by
default), which is what raises a silent-collar alert and flushes the
cleaner's hold. A gap alert can therefore be raised up to one tick after
its threshold is crossed.

Each deployment is ticked from its first arrival until its end of watch:

- A **planned end** (``PLANNED_ENDS``: the tag was removed, or the animal
  captured or released) is known to the operator when it happens, so
  ticking stops at deploy-off and the end raises no gap alert.
- Any **other end** (death, transmission end, fall-off, equipment failure,
  unknown, none recorded) is only known afterwards, so the collar is
  watched for ``SILENT_HORIZON`` after its last arrival, as an operator
  would, and its final silence can raise a gap alert.

The gap detector's ``allowance`` (clock time, not active hours) is the
upload interval plus ``UPLOAD_MARGIN``: with daily uploads the newest fix is up to a day old
when it arrives, so a fixed threshold would raise a gap alert every day.
The 36 h margin was chosen on the tuning-set sweep (``results/SWEEP.md``);
it also absorbs whole GSM out-of-coverage days. The tick and watch horizon
are provisional; see ``docs/ASSUMPTIONS.md``.
"""

from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from telemetry.alerts import (
    LATE_FIX,
    LIKELY_DEATH,
    MORTALITY,
    OPEN,
    AlertLifecycle,
    Incident,
    LifecycleConfig,
)
from telemetry.arrival import Arrival, ArrivalScenario, simulate_arrival
from telemetry.cleaning import DROP_REASONS, Cleaner
from telemetry.detectors.gap import GapConfig, GapDetector
from telemetry.detectors.geofence import Fence, GeofenceDetector
from telemetry.detectors.mortality import MortalityDetector
from telemetry.detectors.movement import MovementDetector
from telemetry.fixes import Deployment, Fix
from telemetry.species import SpeciesProfile, profile_for
from telemetry.stream import TICK, Detector, FixStream

PLANNED_ENDS = frozenset({"removal", "captured", "released"})
SILENT_HORIZON = timedelta(days=7)
UPLOAD_MARGIN = timedelta(hours=36)
MERGE_SLACK = timedelta(hours=12)
DEFAULT_SEED = 2026


@dataclass(frozen=True)
class Overrides:
    """Settings that replace the defaults, for threshold sweeps.

    The defaults reproduce a plain replay exactly.

    Attributes:
        mortality_window: Replaces every species' mortality window; None
            keeps them. The mortality merge window follows it, at the
            window plus ``MERGE_SLACK``, since a reopen can never come
            sooner than the window.
        mortality_box_m: Replaces the mortality detector's stationary box
            (``max_extent_m``); None keeps it.
        upload_margin: Silence allowed beyond the upload interval before a
            gap alert.
    """

    mortality_window: timedelta | None = None
    mortality_box_m: float | None = None
    upload_margin: timedelta = UPLOAD_MARGIN

    def profile(self, profile: SpeciesProfile) -> SpeciesProfile:
        """A species profile with these overrides applied.

        Args:
            profile: The species' own settings.

        Returns:
            SpeciesProfile: The profile, with the mortality window and box
            replaced where set.
        """
        mortality = profile.mortality
        if self.mortality_window is not None:
            mortality = replace(mortality, window=self.mortality_window)
        if self.mortality_box_m is not None:
            mortality = replace(mortality, max_extent_m=self.mortality_box_m)
        return replace(profile, mortality=mortality)

    def lifecycle(self) -> AlertLifecycle:
        """The alert lifecycle for these overrides.

        Returns:
            AlertLifecycle: Default merge windows, or a mortality merge
            window following an overridden mortality window.
        """
        if self.mortality_window is None:
            return AlertLifecycle()
        return AlertLifecycle(
            LifecycleConfig(
                {
                    MORTALITY: self.mortality_window + MERGE_SLACK,
                    LIKELY_DEATH: self.mortality_window + MERGE_SLACK,
                }
            )
        )

    def to_dict(self) -> dict:
        """JSON-ready form, in hours and metres.

        Returns:
            dict: The three settings; None where a default is kept.
        """
        return {
            "mortality_window_hours": (
                self.mortality_window / timedelta(hours=1)
                if self.mortality_window is not None
                else None
            ),
            "mortality_box_m": self.mortality_box_m,
            "upload_margin_hours": self.upload_margin / timedelta(hours=1),
        }


@dataclass(frozen=True)
class ReplayResult:
    """What one replay produced.

    Attributes:
        incidents: Final state of every incident, ordered by when it was
            first raised, then by ID.
        summary: Counts and settings for the run, JSON-ready.
    """

    incidents: list[Incident]
    summary: dict


def gap_config(
    scenario: ArrivalScenario, margin: timedelta = UPLOAD_MARGIN
) -> GapConfig:
    """Gap settings for an arrival scenario.

    Args:
        scenario: The upload pattern.
        margin: Silence allowed beyond the upload interval.

    Returns:
        GapConfig: The defaults, with ``allowance`` set to the upload
        interval (none for ideal arrival) plus ``margin``.
    """
    upload = scenario.upload_every or timedelta(0)
    return replace(GapConfig(), allowance=upload + margin)


def detectors_for(
    profile: SpeciesProfile,
    scenario: ArrivalScenario,
    margin: timedelta = UPLOAD_MARGIN,
    fence: Fence | None = None,
) -> list[Detector]:
    """The detectors a deployment is run through.

    Args:
        profile: The deployment's species settings.
        scenario: The upload pattern, which sets the gap threshold.
        margin: Silence allowed beyond the upload interval.
        fence: The study's geofence, or None.

    Returns:
        list[Detector]: Mortality, unusual-movement and gap detectors, and
        a geofence detector when there is a fence.
    """
    detectors = [
        MortalityDetector(profile.mortality),
        MovementDetector(profile.movement),
        GapDetector(gap_config(scenario, margin)),
    ]
    if fence is not None:
        detectors.append(GeofenceDetector(fence))
    return detectors


@dataclass(frozen=True)
class Timeline:
    """What one deployment receives in a replay.

    Attributes:
        deployment: The deployment.
        arrivals: Its arrivals under the scenario, in arrival order.
        until: End of watch (``watch_until``).
    """

    deployment: Deployment
    arrivals: list[Arrival]
    until: datetime


def timelines(
    deployments: list[Deployment],
    fixes: list[Fix],
    scenario: ArrivalScenario,
    seed: int = DEFAULT_SEED,
) -> Iterator[Timeline]:
    """Each deployment's arrivals and end of watch, the input to a replay.

    The replay runner and the cloud publisher both read this, so they feed
    the core the same thing.

    Args:
        deployments: The study's deployments.
        fixes: Their fixes, in any order.
        scenario: The upload pattern.
        seed: Arrival seed.

    Yields:
        Timeline: One per deployment with fixes, by deployment ID.
    """
    by_deployment = defaultdict(list)
    for fix in fixes:
        by_deployment[fix.deployment_id].append(fix)
    for deployment in sorted(deployments, key=lambda d: d.deployment_id):
        own = sorted(
            by_deployment.get(deployment.deployment_id, []), key=lambda f: f.timestamp
        )
        if not own:
            continue
        arrivals = simulate_arrival(own, scenario, seed)
        yield Timeline(
            deployment, arrivals, watch_until(deployment, arrivals, scenario)
        )


def stream_for(
    taxon: str,
    scenario: ArrivalScenario,
    overrides: Overrides | None = None,
    fence: Fence | None = None,
    lifecycle: AlertLifecycle | None = None,
) -> FixStream:
    """An empty stream configured for one deployment.

    Each deployment gets its own stream, since detector and cleaner
    settings depend on the species; the detectors themselves hold no
    state. The cloud handler builds its stream here too, so both runners
    use the same settings.

    Args:
        taxon: The deployment's taxon, which picks the species profile.
        scenario: The upload pattern, which sets the gap allowance and the
            cleaner's hold.
        overrides: Settings replacing the defaults, for sweeps; None keeps
            the defaults.
        fence: The study's geofence, or None.
        lifecycle: A lifecycle to share between streams; built from
            ``overrides`` if omitted.

    Returns:
        FixStream: A stream with no state yet.

    Raises:
        KeyError: If the taxon has no species profile.
    """
    overrides = overrides or Overrides()
    profile = overrides.profile(profile_for(taxon))
    return FixStream(
        detectors_for(profile, scenario, overrides.upload_margin, fence),
        Cleaner(profile.cleaning(scenario.max_lateness)),
        lifecycle or overrides.lifecycle(),
    )


def watch_until(
    deployment: Deployment, arrivals: list[Arrival], scenario: ArrivalScenario
) -> datetime:
    """When the replay stops ticking a deployment.

    Args:
        deployment: The deployment.
        arrivals: Its arrivals, in arrival order; not empty.
        scenario: The upload pattern, whose hold time the last fixes need
            to clear the cleaner.

    Returns:
        datetime: Deploy-off for a planned end (or later, if the last fixes
        are still held by the cleaner); otherwise the last arrival plus
        ``SILENT_HORIZON``.
    """
    last = arrivals[-1].time
    if deployment.end_type in PLANNED_ENDS and deployment.deploy_off is not None:
        return max(deployment.deploy_off, last + scenario.max_lateness)
    return last + SILENT_HORIZON


def replay(
    deployments: list[Deployment],
    fixes: list[Fix],
    scenario: ArrivalScenario,
    seed: int = DEFAULT_SEED,
    tick: timedelta = TICK,
    overrides: Overrides | None = None,
    fence: Fence | None = None,
) -> ReplayResult:
    """Replay a study under one arrival scenario.

    Args:
        deployments: The study's deployments.
        fixes: Their fixes, in any order.
        scenario: The upload pattern.
        seed: Arrival seed; the same seed gives the same result.
        tick: Interval between clock ticks.
        overrides: Settings replacing the defaults, for sweeps; None keeps
            the defaults.
        fence: Geofence applied to every deployment, or None.

    Returns:
        ReplayResult: Every incident and a summary of the run.

    Raises:
        KeyError: If a deployment's taxon has no species profile.
    """
    overrides = overrides or Overrides()
    lifecycle = overrides.lifecycle()
    streams: dict[str, FixStream] = {}
    latest: dict[str, Incident] = {}
    arrived = 0
    for timeline in timelines(deployments, fixes, scenario, seed):
        deployment = timeline.deployment
        arrived += len(timeline.arrivals)
        stream = stream_for(deployment.taxon, scenario, overrides, fence, lifecycle)
        streams[deployment.deployment_id] = stream
        # Keep only the newest state of each incident.
        for incident in stream.advance(
            deployment.deployment_id, timeline.arrivals, timeline.until, tick
        ):
            latest[incident.incident_id] = incident

    incidents = sorted(latest.values(), key=lambda i: (i.raised_at, i.incident_id))
    summary = summarise(scenario, seed, tick, streams, incidents)
    if overrides != Overrides():
        summary["overrides"] = overrides.to_dict()
        summary["settings"]["gap_allowance_hours"] = gap_config(
            scenario, overrides.upload_margin
        ).allowance / timedelta(hours=1)
    summary["fixes"] = len(fixes)
    summary["arrivals"] = arrived
    return ReplayResult(incidents, summary)


def summarise(
    scenario: ArrivalScenario,
    seed: int,
    tick: timedelta,
    streams: dict[str, FixStream],
    incidents: list[Incident],
) -> dict:
    """Counts and settings for one replay.

    Args:
        scenario: The upload pattern.
        seed: Arrival seed.
        tick: Tick interval.
        streams: Each deployment's stream after the replay.
        incidents: Final state of every incident.

    Returns:
        dict: Settings, cleaner and lifecycle drop counts, and incident
        counts by detector.
    """
    cleaner_dropped = Counter(dict.fromkeys(DROP_REASONS, 0))
    lifecycle_dropped = Counter()
    for stream in streams.values():
        for state in stream.states.values():
            cleaner_dropped.update(state.cleaning.get("dropped", {}))
            lifecycle_dropped.update(state.alerts.get("dropped", {}))

    by_detector = {}
    for incident in incidents:
        counts = by_detector.setdefault(
            incident.detector,
            {"incidents": 0, "open_at_end": 0, "late_fix": 0, "flaps": 0},
        )
        counts["incidents"] += 1
        counts["open_at_end"] += incident.status == OPEN
        counts["late_fix"] += incident.resolution == LATE_FIX
        counts["flaps"] += incident.flaps

    return {
        "scenario": scenario.name,
        "seed": seed,
        "settings": {
            "tick_hours": tick / timedelta(hours=1),
            "max_lateness_hours": scenario.max_lateness / timedelta(hours=1),
            "gap_min_silence_hours": gap_config(scenario).min_silence
            / timedelta(hours=1),
            "gap_allowance_hours": gap_config(scenario).allowance / timedelta(hours=1),
            "silent_horizon_days": SILENT_HORIZON / timedelta(days=1),
            "planned_ends": sorted(PLANNED_ENDS),
        },
        "deployments": len(streams),
        "cleaner_dropped": dict(sorted(cleaner_dropped.items())),
        "lifecycle_dropped": dict(sorted(lifecycle_dropped.items())),
        "incidents": dict(sorted(by_detector.items())),
    }
