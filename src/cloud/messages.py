"""The cloud message: one slice of one deployment's timeline, with the
settings needed to process it.

A message describes itself, so the processor needs no configuration table:
it carries the run, the slice's sequence number within its deployment, the
deployment's taxon, the upload plan and the name of the study's boundary.
Boundaries are bundled with the handler, so only the name travels.

The sequence number is what makes processing idempotent. Slices of one
deployment are numbered from 0 in order; the processor applies slice ``n``
only to state that has applied ``n - 1``, so a redelivered message is
recognised and skipped, and a missing one stops the deployment rather than
being stepped over.

A clock tick (live mode) is a message with no sequence number and an
empty slice: it runs the deployment's clock to ``until`` so a silent
collar still raises its gap alert. It travels in the deployment's message
group, so it is applied in order with the slices around it, and it is
idempotent by itself: a tick to a time the clock has passed changes
nothing (see ``processor``).
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.core.slices import Slice


@dataclass(frozen=True)
class UploadSettings:
    """An upload plan as named in a message (``pipeline.UploadPlan``).

    Attributes:
        upload_every: Time between uploads; None if every fix is sent as it
            is taken.
        max_lateness: How long the cleaner holds fixes.
    """

    upload_every: timedelta | None
    max_lateness: timedelta

    def to_dict(self) -> dict:
        """JSON-ready form, in hours.

        Returns:
            dict: ``upload_every_hours`` (or None) and ``max_lateness_hours``.
        """
        return {
            "upload_every_hours": _hours(self.upload_every),
            "max_lateness_hours": _hours(self.max_lateness),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UploadSettings":
        """Rebuild settings written by ``to_dict``.

        Args:
            data: A dict produced by ``UploadSettings.to_dict``.

        Returns:
            UploadSettings: The equivalent settings.
        """
        every = data["upload_every_hours"]
        return cls(
            None if every is None else timedelta(hours=every),
            timedelta(hours=data["max_lateness_hours"]),
        )


def _hours(span: timedelta | None) -> float | None:
    """A time span in hours, or None.

    Args:
        span: A span, or None.

    Returns:
        float | None: Hours, or None.
    """
    return None if span is None else span / timedelta(hours=1)


@dataclass(frozen=True)
class Message:
    """One SQS message body.

    Attributes:
        run_id: The run (study and scenario), so runs can share tables.
        seq: The slice's position in its deployment's timeline, from 0;
            None for a clock tick.
        taxon: The deployment's taxon, which picks the species profile.
        uploads: The upload plan.
        boundary: Name of the bundled boundary file (an exit fence), or
            None for no geofence.
        slice: The deployment's arrivals and clock target.
        sent_at: Wall-clock time the publisher sent it, or None; used only
            for latency.
    """

    run_id: str
    seq: int | None
    taxon: str
    uploads: UploadSettings
    boundary: str | None
    slice: Slice
    sent_at: datetime | None = None

    @property
    def deployment_id(self) -> str:
        """The deployment the slice belongs to.

        Returns:
            str: Its ID.
        """
        return self.slice.deployment_id

    @property
    def key(self) -> str:
        """The deployment's key within its run, shared by its state item and
        its message group.

        Returns:
            str: ``<run_id>#<deployment_id>``.
        """
        return state_key(self.run_id, self.deployment_id)

    @property
    def is_tick(self) -> bool:
        """Whether this is a clock tick rather than a numbered slice.

        Returns:
            bool: True when ``seq`` is None.
        """
        return self.seq is None

    @property
    def dedup_id(self) -> str:
        """SQS FIFO deduplication ID: the same slice or tick sent twice
        within the dedup window is dropped by the queue.

        Returns:
            str: ``<run_id>#<deployment_id>#<seq>``, or for a tick
            ``<run_id>#<deployment_id>#tick#<until>``.
        """
        if self.is_tick:
            return f"{self.key}#tick#{self.slice.until.isoformat()}"
        return f"{self.key}#{self.seq}"

    def to_json(self) -> str:
        """Compact JSON, the message body.

        Returns:
            str: The body.
        """
        return json.dumps(
            {
                "run_id": self.run_id,
                "seq": self.seq,
                "taxon": self.taxon,
                "uploads": self.uploads.to_dict(),
                "boundary": self.boundary,
                "sent_at": self.sent_at and self.sent_at.isoformat(),
                "slice": self.slice.to_dict(),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, body: str) -> "Message":
        """Parse a body written by ``to_json``.

        Args:
            body: The message body.

        Returns:
            Message: The message.
        """
        data = json.loads(body)
        return cls(
            run_id=data["run_id"],
            seq=data["seq"],
            taxon=data["taxon"],
            uploads=UploadSettings.from_dict(data["uploads"]),
            boundary=data["boundary"],
            slice=Slice.from_dict(data["slice"]),
            sent_at=(
                datetime.fromisoformat(data["sent_at"]) if data["sent_at"] else None
            ),
        )


def state_key(run_id: str, deployment_id: str) -> str:
    """Key of one deployment's state within a run.

    Args:
        run_id: The run.
        deployment_id: The deployment.

    Returns:
        str: ``<run_id>#<deployment_id>``.
    """
    return f"{run_id}#{deployment_id}"


def fifo_dedup_id(plain: str) -> str:
    """A deduplication ID SQS accepts: hashed if longer than its 128
    characters.

    Args:
        plain: The readable ID.

    Returns:
        str: ``plain``, or its SHA-256 hex digest.
    """
    return plain if len(plain) <= 128 else hashlib.sha256(plain.encode()).hexdigest()
