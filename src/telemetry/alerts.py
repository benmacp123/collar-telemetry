"""Alerts and their lifecycle: one incident per episode, not one per fix.

Detectors report **transitions**: an ``Alert`` with status ``open`` when an
episode starts (the animal stops moving, the collar goes quiet) and
``resolved`` when it ends. ``AlertLifecycle`` turns those transitions into
**incidents**, which are what an operator is told about:

- **One incident per episode.** An open while the same detector already
  has an incident open for the deployment is a duplicate and is dropped; so
  is a resolve with nothing open. Detectors already avoid both, so this is
  a guard rather than the main mechanism, and drops are counted in state so
  a misbehaving detector shows up.
- **Flaps reopen the same incident.** A resolve is reported at once, but
  the resolved incident is remembered for the detector's
  ``merge_within``; an open in that time reopens it (same ID, ``flaps``
  counted) instead of starting a new one. A carcass dragged a short way by
  scavengers therefore stays one mortality incident, and its detection
  delay still runs from the first open. The operator may see "resolved"
  then "reopened", which is better than learning late that an animal is
  moving again.
- **Late resolves are flagged.** A resolve whose evidence is older than the
  open, such as a fix uploaded late after a gap alert, still resolves the
  incident (the operator was alerted, so it counts as load), but with
  resolution ``late_fix`` so evaluation can count latency false alarms on
  their own.
- **Stable IDs.** An incident's ID is built from its deployment, detector
  and opening evidence time, so a retried invocation produces the same ID
  and a store can de-duplicate on it.

Detectors are independent: a dead animal can have a mortality incident and,
once its battery dies, a gap incident too. Overlap is reported by
evaluation, not suppressed here.

The merge decision compares evidence times only (the resolve's and the
reopen's), so it does not depend on when ticks or invocations happen.

State is plain JSON, kept in ``AnimalState.alerts``.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

OPEN = "open"
RESOLVED = "resolved"
LATE_FIX = "late_fix"


@dataclass(frozen=True)
class Alert:
    """A detector's transition for one deployment: an episode opening or
    resolving.

    Attributes:
        deployment_id: Deployment the alert is about.
        detector: Name of the detector that raised it.
        time: Time of the evidence: the triggering fix, or the tick time
            for alerts raised by the clock.
        message: Human-readable summary for the operator.
        status: ``OPEN`` or ``RESOLVED``.
        reason: Why a resolve happened (for example ``moved``); None for an
            open.
    """

    deployment_id: str
    detector: str
    time: datetime
    message: str
    status: str = OPEN
    reason: str | None = None

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
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Incident:
    """One episode for one deployment and detector, as told to an operator.

    Attributes:
        incident_id: Stable ID: deployment, detector and opening time.
        deployment_id: Deployment the incident is about.
        detector: Name of the detector that raised it.
        status: ``OPEN`` or ``RESOLVED``.
        opened_at: Evidence time of the first open.
        message: The opening alert's message.
        resolved_at: Evidence time of the final resolve, or None.
        resolution: The resolve's reason, or ``LATE_FIX`` if its evidence
            predates the open; None while open.
        resolve_message: The resolving alert's message, or None.
        flaps: Times the incident resolved and was reopened within the
            merge window.
    """

    incident_id: str
    deployment_id: str
    detector: str
    status: str
    opened_at: datetime
    message: str
    resolved_at: datetime | None = None
    resolution: str | None = None
    resolve_message: str | None = None
    flaps: int = 0

    def to_dict(self) -> dict:
        """JSON-ready form, for alert files, queues and state.

        Returns:
            dict: The incident's fields, with times as ISO 8601 text.
        """
        return {
            "incident_id": self.incident_id,
            "deployment_id": self.deployment_id,
            "detector": self.detector,
            "status": self.status,
            "opened_at": self.opened_at.isoformat(),
            "message": self.message,
            "resolved_at": self.resolved_at and self.resolved_at.isoformat(),
            "resolution": self.resolution,
            "resolve_message": self.resolve_message,
            "flaps": self.flaps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Incident":
        """Rebuild an incident saved with ``to_dict``.

        Args:
            data: A dict produced by ``Incident.to_dict``; extra keys are
                ignored.

        Returns:
            Incident: The equivalent incident.
        """
        resolved_at = data["resolved_at"]
        return cls(
            incident_id=data["incident_id"],
            deployment_id=data["deployment_id"],
            detector=data["detector"],
            status=data["status"],
            opened_at=datetime.fromisoformat(data["opened_at"]),
            message=data["message"],
            resolved_at=datetime.fromisoformat(resolved_at) if resolved_at else None,
            resolution=data["resolution"],
            resolve_message=data["resolve_message"],
            flaps=data["flaps"],
        )


def default_merge_within() -> dict[str, timedelta]:
    """Provisional merge windows, not yet chosen on the tuning set.

    Mortality gets one because a carcass moved a little by scavengers, or a
    GPS fix wandering past the cluster edge, would otherwise split one death
    into several incidents. A mortality reopen cannot come sooner than the
    detector's own ``window`` (24 h by default) after the resolve, since the
    new cluster has to last that long, so the merge window must exceed it;
    36 h leaves 12 h of slack. Gap and movement resolves are taken as final.

    Returns:
        dict[str, timedelta]: Merge window by detector name.
    """
    return {"mortality": timedelta(hours=36)}


@dataclass(frozen=True)
class LifecycleConfig:
    """Lifecycle settings.

    Attributes:
        merge_within: How long after a resolve, by detector name, an open
            reopens the same incident. Must exceed the detector's own time
            to raise an alert, or it never takes effect. Detectors not
            listed never reopen.
    """

    merge_within: dict[str, timedelta] = field(default_factory=default_merge_within)


class AlertLifecycle:
    """Turns detector transitions into incidents for one deployment at a
    time."""

    def __init__(self, config: LifecycleConfig | None = None):
        """Create a lifecycle.

        Args:
            config: Lifecycle settings; the provisional defaults if omitted.
        """
        self.config = config or LifecycleConfig()

    def apply(self, state: dict, alerts: list[Alert]) -> list[Incident]:
        """Apply detector transitions, in order, to a deployment's incidents.

        Args:
            state: The deployment's lifecycle state, updated in place;
                starts as an empty dict.
            alerts: Transitions from the deployment's detectors, in the
                order they were raised.

        Returns:
            list[Incident]: Incidents opened, reopened or resolved, in order.
        """
        if "open" not in state:
            state.update(
                open={},
                recent={},
                dropped={"duplicate_open": 0, "orphan_resolve": 0},
            )
        events = []
        for alert in alerts:
            if alert.status == OPEN:
                events += self._open(state, alert)
            else:
                events += self._resolve(state, alert)
        return events

    def _window(self, detector: str) -> timedelta:
        """Merge window for a detector.

        Args:
            detector: Detector name.

        Returns:
            timedelta: The configured window, or zero if none.
        """
        return self.config.merge_within.get(detector, timedelta(0))

    def _open(self, state: dict, alert: Alert) -> list[Incident]:
        """Open an incident, reopen a recent one, or drop a duplicate.

        Args:
            state: The deployment's lifecycle state, updated in place.
            alert: An open transition.

        Returns:
            list[Incident]: The opened or reopened incident, or nothing.
        """
        if alert.detector in state["open"]:
            state["dropped"]["duplicate_open"] += 1
            return []
        recent = state["recent"].pop(alert.detector, None)
        if recent is not None:
            since = alert.time - datetime.fromisoformat(recent["resolved_at"])
            if since <= self._window(alert.detector):
                incident = Incident.from_dict(
                    {
                        **recent,
                        "status": OPEN,
                        "resolved_at": None,
                        "resolution": None,
                        "resolve_message": None,
                        "flaps": recent["flaps"] + 1,
                    }
                )
                state["open"][alert.detector] = incident.to_dict()
                return [incident]
        incident = Incident(
            incident_id=f"{alert.deployment_id}:{alert.detector}:"
            f"{alert.time.isoformat()}",
            deployment_id=alert.deployment_id,
            detector=alert.detector,
            status=OPEN,
            opened_at=alert.time,
            message=alert.message,
        )
        state["open"][alert.detector] = incident.to_dict()
        return [incident]

    def _resolve(self, state: dict, alert: Alert) -> list[Incident]:
        """Resolve an open incident, remembering it if it may reopen.

        Args:
            state: The deployment's lifecycle state, updated in place.
            alert: A resolved transition.

        Returns:
            list[Incident]: The resolved incident, or nothing if none was
            open.
        """
        record = state["open"].pop(alert.detector, None)
        if record is None:
            state["dropped"]["orphan_resolve"] += 1
            return []
        late = alert.time < datetime.fromisoformat(record["opened_at"])
        incident = Incident.from_dict(
            {
                **record,
                "status": RESOLVED,
                "resolved_at": alert.time.isoformat(),
                "resolution": LATE_FIX if late else alert.reason,
                "resolve_message": alert.message,
            }
        )
        if self._window(alert.detector) > timedelta(0):
            state["recent"][alert.detector] = incident.to_dict()
        return [incident]


def open_incidents(state: dict) -> list[Incident]:
    """Incidents still open for a deployment.

    Args:
        state: The deployment's lifecycle state.

    Returns:
        list[Incident]: Open incidents, ordered by detector name.
    """
    return [
        Incident.from_dict(state["open"][name])
        for name in sorted(state.get("open", {}))
    ]
