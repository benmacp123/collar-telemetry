"""Feed fixes through detectors one at a time, keeping per-animal state.

The unit of work is one fix for one deployment: ``process_fix`` takes that
deployment's state, updates it in place and returns any alerts. An optional
``Cleaner`` sits in front of the detectors, so they see clean fixes in time
order whatever order the fixes arrive in. State is
plain JSON (``AnimalState.to_dict``), so a Lambda handler can load it from
a table, call ``process_fix`` and save it back; ``FixStream`` does the
same in memory for the local replay runner.

Detectors also receive clock ticks, because some alerts (a silent collar)
are raised by the absence of fixes rather than by a fix.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from telemetry.cleaning import Cleaner
from telemetry.fixes import Fix


@dataclass(frozen=True)
class Alert:
    """A detector's finding about one deployment.

    Attributes:
        deployment_id: Deployment the alert is about.
        detector: Name of the detector that raised it.
        time: Time of the evidence: the triggering fix, or the tick time
            for alerts raised by the clock.
        message: Human-readable summary for the operator.
    """

    deployment_id: str
    detector: str
    time: datetime
    message: str

    def to_dict(self) -> dict:
        """JSON-ready form, for alert files and queues.

        Returns:
            dict: The alert's fields, with the time as ISO 8601 text.
        """
        return {
            "deployment_id": self.deployment_id,
            "detector": self.detector,
            "time": self.time.isoformat(),
            "message": self.message,
        }


class Detector(Protocol):
    """What the stream needs from a detector.

    Each detector owns one dict inside each deployment's state, starting
    empty, and may keep only JSON-serialisable values in it.
    """

    name: str

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Update ``state`` for a new fix and return any alerts.

        Args:
            state: This detector's state for the deployment, updated in
                place; starts as an empty dict.
            deployment_id: Deployment the fix belongs to.
            fix: The next fix (clean and in time order behind a cleaner).

        Returns:
            list[Alert]: Alerts raised by this fix, often none.
        """

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Check ``state`` against the clock and return any alerts.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment being checked.
            now: Current time (replay or wall-clock).

        Returns:
            list[Alert]: Alerts raised by the passage of time, often none.
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
    """

    deployment_id: str
    fixes_seen: int = 0
    latest_fix: Fix | None = None
    cleaning: dict = field(default_factory=dict)
    detectors: dict[str, dict] = field(default_factory=dict)

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
        )


def process_fix(
    state: AnimalState,
    fix: Fix,
    detectors: list[Detector],
    cleaner: Cleaner | None = None,
) -> list[Alert]:
    """Run one arriving fix through cleaning and every detector.

    Args:
        state: State of the fix's deployment, updated in place.
        fix: The new fix, in arrival order.
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage; without one, fixes go straight to the
            detectors in arrival order.

    Returns:
        Alerts raised by any detector.

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
    return _detect(state, released, detectors)


def process_tick(
    state: AnimalState,
    now: datetime,
    detectors: list[Detector],
    cleaner: Cleaner | None = None,
) -> list[Alert]:
    """Give one deployment a clock tick.

    The cleaner first releases any fixes now due, then every detector
    checks its state against the clock.

    Args:
        state: State of the deployment, updated in place.
        now: Current time (replay time, or wall-clock time in the cloud).
        detectors: Detectors to run, in order.
        cleaner: Cleaning stage, as for ``process_fix``.

    Returns:
        Alerts raised by any detector.
    """
    released = cleaner.tick(state.cleaning, now) if cleaner else []
    alerts = _detect(state, released, detectors)
    for detector in detectors:
        own = state.detectors.setdefault(detector.name, {})
        alerts += detector.on_tick(own, state.deployment_id, now)
    return alerts


def _detect(
    state: AnimalState, fixes: list[Fix], detectors: list[Detector]
) -> list[Alert]:
    """Run fixes through every detector, each detector seeing every fix.

    Args:
        state: State of the fixes' deployment, updated in place.
        fixes: Fixes to run, oldest first.
        detectors: Detectors to run, in order.

    Returns:
        list[Alert]: Alerts raised by any detector for any fix.
    """
    alerts = []
    for fix in fixes:
        for detector in detectors:
            own = state.detectors.setdefault(detector.name, {})
            alerts += detector.on_fix(own, state.deployment_id, fix)
    return alerts


class FixStream:
    """In-memory state for every deployment, for the local replay runner."""

    def __init__(self, detectors: list[Detector], cleaner: Cleaner | None = None):
        """Create an empty stream.

        Args:
            detectors: Detectors every fix and tick is run through.
            cleaner: Optional cleaning stage in front of the detectors.

        Raises:
            ValueError: If two detectors share a name, since each name keys
                its detector's state.
        """
        names = [detector.name for detector in detectors]
        if len(set(names)) != len(names):
            raise ValueError(f"detector names must be unique: {names}")
        self.detectors = detectors
        self.cleaner = cleaner
        self.states: dict[str, AnimalState] = {}

    def ingest(self, fix: Fix) -> list[Alert]:
        """Process one fix, creating its deployment's state if new.

        Args:
            fix: The arriving fix.

        Returns:
            list[Alert]: Alerts raised for the fix's deployment.
        """
        state = self.states.setdefault(
            fix.deployment_id, AnimalState(fix.deployment_id)
        )
        return process_fix(state, fix, self.detectors, self.cleaner)

    def tick(self, now: datetime) -> list[Alert]:
        """Give a clock tick to every deployment seen so far.

        Args:
            now: Current replay time.

        Returns:
            list[Alert]: Alerts raised for any deployment.
        """
        alerts = []
        for state in self.states.values():
            alerts += process_tick(state, now, self.detectors, self.cleaner)
        return alerts

    def to_dict(self) -> dict:
        """JSON-ready snapshot of every deployment's state.

        Returns:
            dict: ``AnimalState.to_dict`` output keyed by deployment ID.
        """
        return {key: state.to_dict() for key, state in self.states.items()}

    @classmethod
    def from_dict(
        cls, data: dict, detectors: list[Detector], cleaner: Cleaner | None = None
    ) -> "FixStream":
        """Resume a stream from a ``to_dict`` snapshot.

        Args:
            data: A dict produced by ``FixStream.to_dict``.
            detectors: Detectors, configured as when the snapshot was taken.
            cleaner: Cleaner, configured as when the snapshot was taken.

        Returns:
            FixStream: A stream that carries on where the snapshot left off.
        """
        stream = cls(detectors, cleaner)
        stream.states = {
            key: AnimalState.from_dict(value) for key, value in data.items()
        }
        return stream
