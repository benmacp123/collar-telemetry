"""Replay a study's fixes through the detection core under one arrival
scenario.

This is the local runner every reported result comes from. It needs no
AWS account: fixes are read from committed files, arrival is simulated
with a fixed seed, and the same ``FixStream`` core the Lambda handlers
wrap does the detection.

The replay clock moves through the merged arrival feed. Each fix is
ingested at its arrival time, which becomes the incident's ``raised_at``,
so detection delay reflects upload batching. Between arrivals the clock
ticks every ``tick`` (hourly by default), which is what raises a
silent-collar alert and flushes the cleaner's hold. A gap alert can
therefore be raised up to one tick after its threshold is crossed.

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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from telemetry.alerts import (
    LATE_FIX,
    LIKELY_DEATH,
    MORTALITY,
    OPEN,
    AlertLifecycle,
    Incident,
    LifecycleConfig,
)
from telemetry.arrival import Arrival, ArrivalScenario, merge_arrivals, simulate_arrival
from telemetry.cleaning import DROP_REASONS, Cleaner
from telemetry.detectors.gap import GapConfig, GapDetector
from telemetry.detectors.mortality import MortalityDetector
from telemetry.detectors.movement import MovementDetector
from telemetry.fixes import Deployment, Fix
from telemetry.species import SpeciesProfile, profile_for
from telemetry.stream import Detector, FixStream

TICK = timedelta(hours=1)
PLANNED_ENDS = frozenset({"removal", "captured", "released"})
SILENT_HORIZON = timedelta(days=7)
UPLOAD_MARGIN = timedelta(hours=36)
MERGE_SLACK = timedelta(hours=12)
DEFAULT_SEED = 2026

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


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
) -> list[Detector]:
    """The detectors a deployment is run through.

    Args:
        profile: The deployment's species settings.
        scenario: The upload pattern, which sets the gap threshold.
        margin: Silence allowed beyond the upload interval.

    Returns:
        list[Detector]: Mortality, unusual-movement and gap detectors.
    """
    return [
        MortalityDetector(profile.mortality),
        MovementDetector(profile.movement),
        GapDetector(gap_config(scenario, margin)),
    ]


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


def first_tick_after(time: datetime, tick: timedelta) -> datetime:
    """The first tick strictly after ``time``, on a grid fixed to the epoch.

    Args:
        time: Any UTC time.
        tick: Tick interval.

    Returns:
        datetime: The next grid point after ``time``.
    """
    return EPOCH + ((time - EPOCH) // tick + 1) * tick


def replay(
    deployments: list[Deployment],
    fixes: list[Fix],
    scenario: ArrivalScenario,
    seed: int = DEFAULT_SEED,
    tick: timedelta = TICK,
    overrides: Overrides | None = None,
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

    Returns:
        ReplayResult: Every incident and a summary of the run.

    Raises:
        KeyError: If a deployment's taxon has no species profile.
    """
    by_deployment = defaultdict(list)
    for fix in fixes:
        by_deployment[fix.deployment_id].append(fix)

    overrides = overrides or Overrides()
    lifecycle = overrides.lifecycle()
    streams: dict[str, FixStream] = {}
    windows: list[tuple[datetime, datetime, str]] = []
    feeds = []
    for deployment in sorted(deployments, key=lambda d: d.deployment_id):
        own = sorted(
            by_deployment.get(deployment.deployment_id, []), key=lambda f: f.timestamp
        )
        if not own:
            continue
        profile = overrides.profile(profile_for(deployment.taxon))
        arrivals = simulate_arrival(own, scenario, seed)
        # One stream per deployment, since detector and cleaner settings
        # depend on the species; the detectors themselves hold no state.
        streams[deployment.deployment_id] = FixStream(
            detectors_for(profile, scenario, overrides.upload_margin),
            Cleaner(profile.cleaning(scenario.max_lateness)),
            lifecycle,
        )
        windows.append(
            (
                arrivals[0].time,
                watch_until(deployment, arrivals, scenario),
                deployment.deployment_id,
            )
        )
        feeds.append(arrivals)

    latest: dict[str, Incident] = {}
    clock = _Clock(streams, windows, tick, latest)
    arrivals = merge_arrivals(feeds)
    for arrival in arrivals:
        # Ticks due before this arrival run first; a tick at the same
        # instant runs after it, so the gap detector sees the fresh fix.
        clock.run_until(arrival.time, inclusive=False)
        stream = streams[arrival.fix.deployment_id]
        clock.record(stream.ingest(arrival.fix, now=arrival.time))
    clock.run_until(max((end for _, end, _ in windows), default=EPOCH), inclusive=True)

    incidents = sorted(latest.values(), key=lambda i: (i.raised_at, i.incident_id))
    summary = summarise(scenario, seed, tick, streams, incidents)
    if overrides != Overrides():
        summary["overrides"] = overrides.to_dict()
        summary["settings"]["gap_allowance_hours"] = gap_config(
            scenario, overrides.upload_margin
        ).allowance / timedelta(hours=1)
    summary["fixes"] = sum(len(feed) for feed in by_deployment.values())
    summary["arrivals"] = len(arrivals)
    return ReplayResult(incidents, summary)


class _Clock:
    """Hourly (or ``tick``) ticks for the deployments being watched."""

    def __init__(
        self,
        streams: dict[str, FixStream],
        windows: list[tuple[datetime, datetime, str]],
        tick: timedelta,
        latest: dict[str, Incident],
    ):
        """Set up a clock before the first arrival.

        Args:
            streams: Each deployment's stream, by deployment ID.
            windows: (first arrival, end of watch, deployment ID) per
                deployment.
            tick: Tick interval.
            latest: Incidents by ID, updated as ticks raise them.
        """
        self.streams = streams
        self.pending = sorted(windows)
        self.active: dict[str, datetime] = {}
        self.tick = tick
        self.latest = latest
        self.next = first_tick_after(self.pending[0][0], tick) if self.pending else None

    def record(self, incidents: list[Incident]) -> None:
        """Keep the newest state of each incident.

        Args:
            incidents: Incidents just opened, reopened or resolved.
        """
        for incident in incidents:
            self.latest[incident.incident_id] = incident

    def run_until(self, limit: datetime, inclusive: bool) -> None:
        """Run every tick up to ``limit``.

        Args:
            limit: Time to run up to.
            inclusive: Whether a tick exactly at ``limit`` runs.
        """
        while self.next is not None and (
            self.next < limit or (inclusive and self.next == limit)
        ):
            now = self.next
            while self.pending and self.pending[0][0] <= now:
                _, end, deployment_id = self.pending.pop(0)
                self.active[deployment_id] = end
            for deployment_id, end in list(self.active.items()):
                if end < now:
                    del self.active[deployment_id]
                    continue
                self.record(self.streams[deployment_id].tick(now))
            if self.active or not self.pending:
                self.next = now + self.tick
            else:
                # Nobody is being watched: skip ahead to the next start.
                self.next = first_tick_after(self.pending[0][0], self.tick)


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
