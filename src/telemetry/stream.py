"""Feed fixes through detectors one at a time, keeping per-animal state.

The unit of work is one fix for one deployment: ``process_fix`` takes that
deployment's state, updates it in place and returns any incidents. An
optional ``Cleaner`` sits in front of the detectors, so they see clean
fixes in time order whatever order the fixes arrive in. State is
plain JSON (``AnimalState.to_dict``), so a Lambda handler can load it from
a table, call ``advance`` and save it back; ``FixStream`` does the same in
memory for the local replay runner.

Detectors also receive clock ticks, because some alerts (a silent collar)
are raised by the absence of fixes rather than by a fix. ``advance`` is
the one place arrivals and ticks are interleaved: it runs a deployment's
arrivals with the ticks due between them, on a fixed hourly grid. Its tick
cursor lives in the state, so a timeline split into any number of pieces,
each run in a separate invocation, gives the same incidents as one run.
Both runners call it: the replay runner with a deployment's whole
timeline, the cloud runner with one slice per message.

Detectors report transitions (``Alert``); an ``AlertLifecycle`` behind
them turns those into incidents, so callers get one ``Incident`` when an
episode opens and one when it resolves, not one per fix.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from telemetry.alerts import Alert, AlertLifecycle, Incident, open_incidents
from telemetry.arrival import Arrival
from telemetry.cleaning import Cleaner
from telemetry.fixes import Fix

TICK = timedelta(hours=1)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def first_tick_after(time: datetime, tick: timedelta) -> datetime:
    """The first tick strictly after ``time``, on a grid fixed to the epoch.

    Args:
        time: Any UTC time.
        tick: Tick interval.

    Returns:
        datetime: The next grid point after ``time``.
    """
    return EPOCH + ((time - EPOCH) // tick + 1) * tick


class Detector(Protocol):
    """What the stream needs from a detector.

    Each detector owns one dict inside each deployment's state, starting
    empty, and may keep only JSON-serialisable values in it. It reports an
    open ``Alert`` when an episode starts and a resolved one when it ends.
    """

    name: str

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Update ``state`` for a new fix and return any transitions.

        Args:
            state: This detector's state for the deployment, updated in
                place; starts as an empty dict.
            deployment_id: Deployment the fix belongs to.
            fix: The next fix (clean and in time order behind a cleaner).

        Returns:
            list[Alert]: Transitions raised by this fix, often none.
        """

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Check ``state`` against the clock and return any transitions.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment being checked.
            now: Current time (replay or wall-clock).

        Returns:
            list[Alert]: Transitions raised by the passage of time, often
            none.
        """


@dataclass
class AnimalState:
    """Everything remembered about one deployment between fixes.

    Attributes:
        deployment_id: Deployment this state belongs to.
        fixes_seen: Fixes processed so far, in any order.
        latest_fix: The fix with the latest timestamp seen, which is not
            necessarily the last to arrive.
        cleaning: The cleaner's state (buffer, watermark, drop counts).
        detectors: Each detector's own state, keyed by detector name.
        alerts: The lifecycle's state (open incidents, drop counts).
        next_tick: The next tick ``advance`` will run. None until the first
            arrival.
        last_tick: The last tick ``advance`` ran, or None. Not always
            ``next_tick`` less one tick: no tick runs at the instant of the
            first arrival.
        last_arrival: Arrival time of the last fix run by ``advance``.
    """

    deployment_id: str
    fixes_seen: int = 0
    latest_fix: Fix | None = None
    cleaning: dict = field(default_factory=dict)
    detectors: dict[str, dict] = field(default_factory=dict)
    alerts: dict = field(default_factory=dict)
    next_tick: datetime | None = None
    last_tick: datetime | None = None
    last_arrival: datetime | None = None

    def to_dict(self) -> dict:
        """JSON-ready form, for storage between invocations.

        Returns:
            dict: Every field, with the latest fix as a dict.
        """
        return {
            "deployment_id": self.deployment_id,
            "fixes_seen": self.fixes_seen,
            "latest_fix": self.latest_fix and self.latest_fix.to_dict(),
            "cleaning": self.cleaning,
            "detectors": self.detectors,
            "alerts": self.alerts,
            "next_tick": _iso(self.next_tick),
            "last_tick": _iso(self.last_tick),
            "last_arrival": _iso(self.last_arrival),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnimalState":
        """Rebuild state saved with ``to_dict``.

        Args:
            data: A dict produced by ``AnimalState.to_dict``.

        Returns:
            AnimalState: The equivalent state.
        """
        latest = data["latest_fix"]
        return cls(
            deployment_id=data["deployment_id"],
            fixes_seen=data["fixes_seen"],
            latest_fix=Fix.from_dict(latest) if latest else None,
            cleaning=data["cleaning"],
            detectors=data["detectors"],
            alerts=data["alerts"],
            next_tick=_from_iso(data["next_tick"]),
            last_tick=_from_iso(data["last_tick"]),
            last_arrival=_from_iso(data["last_arrival"]),
        )


def _iso(time: datetime | None) -> str | None:
    """ISO 8601 text for a time that may be missing.

    Args:
        time: A time, or None.

    Returns:
        str | None: The time as text, or None.
    """
    return time and time.isoformat()


def _from_iso(text: str | None) -> datetime | None:
    """Parse text written by ``_iso``.

    Args:
        text: ISO 8601 text, or None.

    Returns:
        datetime | None: The time, or None.
    """
    return datetime.fromisoformat(text) if text else None


def process_fix(
    state: AnimalState,
    fix: Fix,
    detectors: list[Detector],
    cleaner: Cleaner | None = None,
    lifecycle: AlertLifecycle | None = None,
    now: datetime | None = None,
) -> list[Incident]:
    """Run one arriving fix through cleaning, every detector and the
    lifecycle.

    Args:
        state: State of the fix's deployment, updated in place.
        fix: The new fix, in arrival order.
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage; without one, fixes go straight to the
            detectors in arrival order.
        lifecycle: Alert lifecycle; one with default settings if omitted.
        now: Arrival time (replay clock, or wall clock in the cloud),
            recorded as when any incident was raised. Without it, incidents
            have no ``raised_at`` and detection delay cannot be measured.

    Returns:
        list[Incident]: Incidents opened or resolved by this fix.

    Raises:
        ValueError: If the fix belongs to a different deployment.
    """
    if fix.deployment_id != state.deployment_id:
        raise ValueError(
            f"fix for {fix.deployment_id!r} sent to state of {state.deployment_id!r}"
        )
    state.fixes_seen += 1
    # Track the newest fix by timestamp, since late fixes arrive after it.
    if state.latest_fix is None or fix.timestamp > state.latest_fix.timestamp:
        state.latest_fix = fix
    released = cleaner.arrive(state.cleaning, fix) if cleaner else [fix]
    alerts = _detect(state, released, detectors)
    return (lifecycle or AlertLifecycle()).apply(state.alerts, alerts, now)


def process_tick(
    state: AnimalState,
    now: datetime,
    detectors: list[Detector],
    cleaner: Cleaner | None = None,
    lifecycle: AlertLifecycle | None = None,
) -> list[Incident]:
    """Give one deployment a clock tick.

    The cleaner first releases any fixes now due, then every detector
    checks its state against the clock.

    Args:
        state: State of the deployment, updated in place.
        now: Current time (replay time, or wall-clock time in the cloud).
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage, as for ``process_fix``.
        lifecycle: Alert lifecycle, as for ``process_fix``.

    Returns:
        list[Incident]: Incidents opened or resolved by this tick.
    """
    released = cleaner.tick(state.cleaning, now) if cleaner else []
    alerts = _detect(state, released, detectors)
    for detector in detectors:
        own = state.detectors.setdefault(detector.name, {})
        alerts += detector.on_tick(own, state.deployment_id, now)
    return (lifecycle or AlertLifecycle()).apply(state.alerts, alerts, now)


def advance(
    state: AnimalState,
    arrivals: list[Arrival],
    until: datetime | None,
    detectors: list[Detector],
    cleaner: Cleaner | None = None,
    lifecycle: AlertLifecycle | None = None,
    tick: timedelta = TICK,
) -> list[Incident]:
    """Run a deployment's arrivals with the clock ticks due around them.

    Before each arrival, every tick strictly before its arrival time runs;
    a tick at the same instant runs after it, so the gap detector sees the
    fresh fix. Then, if ``until`` is given, every tick up to and including
    ``until`` runs. Ticks start at the first grid point after the
    deployment's first arrival and fall on a grid fixed to the epoch.

    Args:
        state: State of the deployment, updated in place.
        arrivals: The deployment's next arrivals, in arrival order.
        until: Time to run the clock to after the last arrival, or None to
            leave the clock at the last arrival (when an upload is split
            across several calls).
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage, as for ``process_fix``.
        lifecycle: Alert lifecycle, as for ``process_fix``.
        tick: Tick interval; must not change over a deployment's life.

    Returns:
        list[Incident]: Incidents opened or resolved, in the order raised;
        an incident that changes twice appears twice.

    Raises:
        ValueError: If an arrival is earlier than an arrival or tick
            already run, which would make the result depend on how the
            timeline was split.
    """
    incidents = []
    for arrival in arrivals:
        if state.last_arrival is not None and arrival.time < state.last_arrival:
            raise ValueError(
                f"arrival at {arrival.time} is before the last arrival "
                f"{state.last_arrival} for {state.deployment_id!r}"
            )
        if state.last_tick is not None and arrival.time <= state.last_tick:
            raise ValueError(
                f"arrival at {arrival.time} is not after the tick at "
                f"{state.last_tick} for {state.deployment_id!r}"
            )
        incidents += _run_ticks(
            state, arrival.time, False, detectors, cleaner, lifecycle, tick
        )
        incidents += process_fix(
            state, arrival.fix, detectors, cleaner, lifecycle, now=arrival.time
        )
        state.last_arrival = arrival.time
        if state.next_tick is None:
            state.next_tick = first_tick_after(arrival.time, tick)
    if until is not None:
        incidents += _run_ticks(state, until, True, detectors, cleaner, lifecycle, tick)
    return incidents


def _run_ticks(
    state: AnimalState,
    limit: datetime,
    inclusive: bool,
    detectors: list[Detector],
    cleaner: Cleaner | None,
    lifecycle: AlertLifecycle | None,
    tick: timedelta,
) -> list[Incident]:
    """Run every tick from the state's cursor up to ``limit``.

    Args:
        state: State of the deployment; its ``next_tick`` moves on.
        limit: Time to run up to.
        inclusive: Whether a tick exactly at ``limit`` runs.
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage, as for ``process_fix``.
        lifecycle: Alert lifecycle, as for ``process_fix``.
        tick: Tick interval.

    Returns:
        list[Incident]: Incidents opened or resolved by the ticks.
    """
    incidents = []
    # Nothing ticks before the first arrival: the collar is not yet known.
    while state.next_tick is not None and (
        state.next_tick < limit or (inclusive and state.next_tick == limit)
    ):
        incidents += process_tick(state, state.next_tick, detectors, cleaner, lifecycle)
        state.last_tick = state.next_tick
        state.next_tick += tick
    return incidents


def _detect(
    state: AnimalState, fixes: list[Fix], detectors: list[Detector]
) -> list[Alert]:
    """Run fixes through every detector, each detector seeing every fix.

    Args:
        state: State of the fixes' deployment, updated in place.
        fixes: Fixes to run, oldest first.
        detectors: Detectors to run, in order.

    Returns:
        list[Alert]: Transitions raised by any detector for any fix.
    """
    alerts = []
    for fix in fixes:
        for detector in detectors:
            own = state.detectors.setdefault(detector.name, {})
            alerts += detector.on_fix(own, state.deployment_id, fix)
    return alerts


class FixStream:
    """In-memory state for every deployment, for the local replay runner."""

    def __init__(
        self,
        detectors: list[Detector],
        cleaner: Cleaner | None = None,
        lifecycle: AlertLifecycle | None = None,
    ):
        """Create an empty stream.

        Args:
            detectors: Detectors every fix and tick is run through.
            cleaner: Optional cleaning stage in front of the detectors.
            lifecycle: Alert lifecycle; one with default settings if
                omitted.

        Raises:
            ValueError: If two detectors share a name, since each name keys
                its detector's state and its incidents.
        """
        names = [detector.name for detector in detectors]
        if len(set(names)) != len(names):
            raise ValueError(f"detector names must be unique: {names}")
        self.detectors = detectors
        self.cleaner = cleaner
        self.lifecycle = lifecycle or AlertLifecycle()
        self.states: dict[str, AnimalState] = {}

    def ingest(self, fix: Fix, now: datetime | None = None) -> list[Incident]:
        """Process one fix, creating its deployment's state if new.

        Args:
            fix: The arriving fix.
            now: Replay time at arrival, as for ``process_fix``.

        Returns:
            list[Incident]: Incidents opened or resolved for the fix's
            deployment.
        """
        state = self.states.setdefault(
            fix.deployment_id, AnimalState(fix.deployment_id)
        )
        return process_fix(
            state, fix, self.detectors, self.cleaner, self.lifecycle, now
        )

    def advance(
        self,
        deployment_id: str,
        arrivals: list[Arrival],
        until: datetime | None,
        tick: timedelta = TICK,
    ) -> list[Incident]:
        """Run one deployment's arrivals and ticks, as ``advance`` does.

        Args:
            deployment_id: The deployment, whose state is created if new.
            arrivals: Its next arrivals, in arrival order.
            until: Time to run its clock to afterwards, or None.
            tick: Tick interval.

        Returns:
            list[Incident]: Incidents opened or resolved, in the order
            raised.
        """
        state = self.states.setdefault(deployment_id, AnimalState(deployment_id))
        return advance(
            state,
            arrivals,
            until,
            self.detectors,
            self.cleaner,
            self.lifecycle,
            tick,
        )

    def tick(self, now: datetime) -> list[Incident]:
        """Give a clock tick to every deployment seen so far.

        Args:
            now: Current replay time.

        Returns:
            list[Incident]: Incidents opened or resolved for any deployment.
        """
        incidents = []
        for state in self.states.values():
            incidents += process_tick(
                state, now, self.detectors, self.cleaner, self.lifecycle
            )
        return incidents

    def open_incidents(self) -> list[Incident]:
        """Incidents still open, for reporting at the end of a replay.

        Returns:
            list[Incident]: Open incidents for every deployment.
        """
        return [
            incident
            for state in self.states.values()
            for incident in open_incidents(state.alerts)
        ]

    def to_dict(self) -> dict:
        """JSON-ready snapshot of every deployment's state.

        Returns:
            dict: ``AnimalState.to_dict`` output keyed by deployment ID.
        """
        return {key: state.to_dict() for key, state in self.states.items()}

    @classmethod
    def from_dict(
        cls,
        data: dict,
        detectors: list[Detector],
        cleaner: Cleaner | None = None,
        lifecycle: AlertLifecycle | None = None,
    ) -> "FixStream":
        """Resume a stream from a ``to_dict`` snapshot.

        Args:
            data: A dict produced by ``FixStream.to_dict``.
            detectors: Detectors, configured as when the snapshot was taken.
            cleaner: Cleaner, configured as when the snapshot was taken.
            lifecycle: Lifecycle, configured as when the snapshot was taken.

        Returns:
            FixStream: A stream that carries on where the snapshot left off.
        """
        stream = cls(detectors, cleaner, lifecycle)
        stream.states = {
            key: AnimalState.from_dict(value) for key, value in data.items()
        }
        return stream
