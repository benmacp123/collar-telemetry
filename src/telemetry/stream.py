"""Feed fixes through detectors one at a time, keeping per-animal state.

The unit of work is one fix for one deployment: ``process_fix`` takes that
deployment's state, updates it in place and returns any alerts. State is
plain JSON (``AnimalState.to_dict``), so a Lambda handler can load it from
a table, call ``process_fix`` and save it back; ``FixStream`` does the
same in memory for the local replay runner.

Detectors also receive clock ticks, because some alerts (a silent collar)
are raised by the absence of fixes rather than by a fix.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

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
        """JSON-ready form, for alert files and queues."""
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
        """Update ``state`` for a new fix and return any alerts."""

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Check ``state`` against the clock and return any alerts."""


def _fix_to_dict(fix: Fix) -> dict:
    return {
        "deployment_id": fix.deployment_id,
        "timestamp": fix.timestamp.isoformat(),
        "lat": fix.lat,
        "lon": fix.lon,
    }


def _fix_from_dict(data: dict) -> Fix:
    return Fix(
        data["deployment_id"],
        datetime.fromisoformat(data["timestamp"]),
        data["lat"],
        data["lon"],
    )


@dataclass
class AnimalState:
    """Everything remembered about one deployment between fixes.

    Attributes:
        deployment_id: Deployment this state belongs to.
        fixes_seen: Fixes processed so far, in any order.
        latest_fix: The fix with the latest timestamp seen, which is not
            necessarily the last to arrive.
        detectors: Each detector's own state, keyed by detector name.
    """

    deployment_id: str
    fixes_seen: int = 0
    latest_fix: Fix | None = None
    detectors: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-ready form, for storage between invocations."""
        return {
            "deployment_id": self.deployment_id,
            "fixes_seen": self.fixes_seen,
            "latest_fix": self.latest_fix and _fix_to_dict(self.latest_fix),
            "detectors": self.detectors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnimalState":
        """Rebuild state saved with ``to_dict``."""
        latest = data["latest_fix"]
        return cls(
            deployment_id=data["deployment_id"],
            fixes_seen=data["fixes_seen"],
            latest_fix=_fix_from_dict(latest) if latest else None,
            detectors=data["detectors"],
        )


def process_fix(state: AnimalState, fix: Fix, detectors: list[Detector]) -> list[Alert]:
    """Run one fix through every detector, updating ``state`` in place.

    Args:
        state: State of the fix's deployment.
        fix: The new fix, in arrival order.
        detectors: Detectors to run, in order.

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
    if state.latest_fix is None or fix.timestamp > state.latest_fix.timestamp:
        state.latest_fix = fix
    alerts = []
    for detector in detectors:
        own = state.detectors.setdefault(detector.name, {})
        alerts += detector.on_fix(own, state.deployment_id, fix)
    return alerts


def process_tick(
    state: AnimalState, now: datetime, detectors: list[Detector]
) -> list[Alert]:
    """Give every detector a clock tick for one deployment.

    Args:
        state: State of the deployment.
        now: Current time (replay time, or wall-clock time in the cloud).
        detectors: Detectors to run, in order.

    Returns:
        Alerts raised by any detector.
    """
    alerts = []
    for detector in detectors:
        own = state.detectors.setdefault(detector.name, {})
        alerts += detector.on_tick(own, state.deployment_id, now)
    return alerts


class FixStream:
    """In-memory state for every deployment, for the local replay runner."""

    def __init__(self, detectors: list[Detector]):
        names = [detector.name for detector in detectors]
        if len(set(names)) != len(names):
            raise ValueError(f"detector names must be unique: {names}")
        self.detectors = detectors
        self.states: dict[str, AnimalState] = {}

    def ingest(self, fix: Fix) -> list[Alert]:
        """Process one fix, creating its deployment's state if new."""
        state = self.states.setdefault(
            fix.deployment_id, AnimalState(fix.deployment_id)
        )
        return process_fix(state, fix, self.detectors)

    def tick(self, now: datetime) -> list[Alert]:
        """Give a clock tick to every deployment seen so far."""
        alerts = []
        for state in self.states.values():
            alerts += process_tick(state, now, self.detectors)
        return alerts

    def to_dict(self) -> dict:
        """JSON-ready snapshot of every deployment's state."""
        return {key: state.to_dict() for key, state in self.states.items()}

    @classmethod
    def from_dict(cls, data: dict, detectors: list[Detector]) -> "FixStream":
        """Resume a stream from a ``to_dict`` snapshot."""
        stream = cls(detectors)
        stream.states = {
            key: AnimalState.from_dict(value) for key, value in data.items()
        }
        return stream
