"""Cut a deployment's timeline into slices, the cloud runner's unit of work.

A slice is one deployment's arrivals over a stretch of the replay clock,
plus the time to run its clock to afterwards. The cloud publisher sends
one slice per message and the handler passes it to ``advance``. Because
``advance`` keeps its tick cursor in the deployment's state, running the
slices one by one, with the state saved and reloaded between them, gives
the same incidents as running the whole timeline at once.

Slices end on a grid fixed to the epoch (daily by default), so a slice is
sent even for a day with no arrivals: that is the clock message that lets
a silent collar raise a gap alert. Fast tags can upload more fixes in a
day than fit in one message, so a day can be split further by
``max_arrivals``; every part but the last has no ``until`` and leaves the
clock at its last arrival.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.core.fixes import Arrival, Fix
from telemetry.core.stream import first_tick_after

DAY = timedelta(days=1)


@dataclass(frozen=True)
class Slice:
    """One deployment's arrivals over a stretch of the clock.

    Attributes:
        deployment_id: The deployment.
        arrivals: Its arrivals in the stretch, in arrival order; may be
            empty.
        until: Time to run its clock to after the arrivals, or None when a
            stretch is split and more arrivals follow at or after the last
            one.
    """

    deployment_id: str
    arrivals: tuple[Arrival, ...]
    until: datetime | None

    def to_dict(self) -> dict:
        """JSON-ready form, the body of one cloud message.

        Each arrival is written as its arrival time, the time the fix was
        taken and its position; the deployment ID is written once.

        Returns:
            dict: ``deployment_id``, ``until`` (ISO 8601 or None) and
            ``arrivals``.
        """
        return {
            "deployment_id": self.deployment_id,
            "until": self.until and self.until.isoformat(),
            "arrivals": [
                {
                    "arrived": arrival.time.isoformat(),
                    "taken": arrival.fix.timestamp.isoformat(),
                    "lat": arrival.fix.lat,
                    "lon": arrival.fix.lon,
                }
                for arrival in self.arrivals
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Slice":
        """Rebuild a slice written by ``to_dict``.

        Args:
            data: A dict produced by ``Slice.to_dict``.

        Returns:
            Slice: The equivalent slice.
        """
        deployment_id = data["deployment_id"]
        return cls(
            deployment_id,
            tuple(
                Arrival(
                    datetime.fromisoformat(item["arrived"]),
                    Fix(
                        deployment_id,
                        datetime.fromisoformat(item["taken"]),
                        item["lat"],
                        item["lon"],
                    ),
                )
                for item in data["arrivals"]
            ),
            datetime.fromisoformat(data["until"]) if data["until"] else None,
        )


def slice_timeline(
    deployment_id: str,
    arrivals: list[Arrival],
    until: datetime,
    every: timedelta = DAY,
    max_arrivals: int | None = None,
) -> list[Slice]:
    """Cut one deployment's timeline into slices.

    Slice boundaries fall on a grid of ``every`` fixed to the epoch,
    starting at the first boundary after the first arrival; the last slice
    ends at ``until``. An arrival exactly on a boundary belongs to the
    slice ending there, since ``advance`` runs a tick at the same instant
    after the arrival.

    Args:
        deployment_id: The deployment.
        arrivals: Its arrivals, in arrival order.
        until: End of watch; not before the last arrival.
        every: Slice length.
        max_arrivals: Most arrivals in one slice, or None for no limit.

    Returns:
        list[Slice]: Slices in order; none if there are no arrivals, since
        the clock does not start until the first arrival.

    Raises:
        ValueError: If an arrival falls after ``until``, or
            ``max_arrivals`` is below 1.
    """
    if max_arrivals is not None and max_arrivals < 1:
        raise ValueError(f"max_arrivals must be at least 1, not {max_arrivals}")
    if not arrivals:
        return []
    if arrivals[-1].time > until:
        raise ValueError(
            f"arrival at {arrivals[-1].time} is after the end of watch {until}"
        )
    slices = []
    start = 0
    boundary = first_tick_after(arrivals[0].time, every)
    while True:
        end = min(boundary, until)
        stop = start
        while stop < len(arrivals) and arrivals[stop].time <= end:
            stop += 1
        slices += _split(deployment_id, arrivals[start:stop], end, max_arrivals)
        start = stop
        if end == until:
            return slices
        boundary += every


def _split(
    deployment_id: str,
    arrivals: list[Arrival],
    until: datetime,
    max_arrivals: int | None,
) -> list[Slice]:
    """Split one stretch into slices of at most ``max_arrivals`` arrivals.

    Args:
        deployment_id: The deployment.
        arrivals: The stretch's arrivals, in arrival order; may be empty.
        until: End of the stretch.
        max_arrivals: Most arrivals in one slice, or None for no limit.

    Returns:
        list[Slice]: At least one slice; only the last carries ``until``.
    """
    size = max_arrivals or len(arrivals) or 1
    parts = [arrivals[i : i + size] for i in range(0, len(arrivals), size)] or [[]]
    return [
        Slice(deployment_id, tuple(part), until if i == len(parts) - 1 else None)
        for i, part in enumerate(parts)
    ]
