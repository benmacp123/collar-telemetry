"""Turn fixes in arrival order into clean fixes in time order.

Collar data arrives late, out of order, duplicated and occasionally wrong.
The cleaner sits between arrival and the detectors:

1. **Validation** drops fixes with impossible coordinates.
2. **Reordering** holds each fix in a buffer until it is ``max_lateness``
   older than the newest fix seen (the watermark), then releases buffered
   fixes in time order. A fix arriving after a later one has already been
   released is too late to slot in and is dropped.
3. **De-duplication** drops a second fix with the same timestamp, whether
   it is still buffered or is the last fix released. Only the last
   released fix is remembered, so a repeat of an older released fix is
   indistinguishable from a late fix and is counted as late.
4. **Speed filtering** drops a released fix whose implied speed from the
   last accepted fix is impossible for the animal, after allowing for GPS
   error on both fixes. After ``max_consecutive_rejects`` rejections in a
   row the next fix is accepted anyway, so one bad anchor cannot reject
   the rest of a track.

Detectors therefore see each deployment's fixes once, in time order, at
the cost of up to ``max_lateness`` of delay. A clock tick also releases
fixes the watermark has passed, so a collar's last fixes before it falls
silent still reach the detectors. State is plain JSON, kept in
``AnimalState.cleaning``.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.fixes import Fix
from telemetry.geo import haversine_m

DROP_REASONS = ("invalid", "duplicate", "late", "speed")


@dataclass(frozen=True)
class CleaningConfig:
    """Cleaning thresholds; species-specific values belong to the caller.

    Attributes:
        max_lateness: How long a fix is held for later-arriving, earlier
            fixes. Zero releases every fix at once and drops any fix older
            than one already released.
        max_speed_mps: Fastest plausible speed for the animal, in m/s.
        gps_error_m: Position error allowed per fix, in metres, when
            judging speed; protects short intervals from GPS jitter.
        max_consecutive_rejects: Speed rejections in a row before the next
            fix is accepted as a new anchor.
    """

    max_lateness: timedelta
    max_speed_mps: float
    gps_error_m: float = 30.0
    max_consecutive_rejects: int = 3


def is_valid(fix: Fix) -> bool:
    """Whether a fix's coordinates are possible.

    Rejects out-of-range values and (0, 0), the usual placeholder for a
    failed fix.
    """
    if not (-90 <= fix.lat <= 90 and -180 <= fix.lon <= 180):
        return False
    return (fix.lat, fix.lon) != (0.0, 0.0)


class Cleaner:
    """Validation, reordering, de-duplication and speed filtering."""

    def __init__(self, config: CleaningConfig):
        self.config = config

    def arrive(self, state: dict, fix: Fix) -> list[Fix]:
        """Take one arriving fix; return the fixes now released, in order.

        Args:
            state: This deployment's cleaning state, updated in place.
            fix: The arriving fix.

        Returns:
            Clean fixes the watermark has passed, oldest first.
        """
        _init(state)
        if not is_valid(fix):
            return self._drop(state, "invalid")
        last = state["last_released"]
        if last is not None:
            last_time = datetime.fromisoformat(last["timestamp"])
            if fix.timestamp == last_time:
                return self._drop(state, "duplicate")
            if fix.timestamp < last_time:
                return self._drop(state, "late")
        stamp = fix.timestamp.isoformat()
        if any(item["timestamp"] == stamp for item in state["buffer"]):
            return self._drop(state, "duplicate")
        state["buffer"].append(fix.to_dict())
        state["buffer"].sort(key=lambda item: datetime.fromisoformat(item["timestamp"]))
        newest = state["newest"]
        if newest is None or fix.timestamp > datetime.fromisoformat(newest):
            state["newest"] = stamp
        return self._release(
            state, datetime.fromisoformat(state["newest"]) - self.config.max_lateness
        )

    def tick(self, state: dict, now: datetime) -> list[Fix]:
        """Release fixes that have waited ``max_lateness`` by the clock.

        Args:
            state: This deployment's cleaning state, updated in place.
            now: Current time.

        Returns:
            Clean fixes now due, oldest first.
        """
        _init(state)
        return self._release(state, now - self.config.max_lateness)

    def _drop(self, state: dict, reason: str) -> list[Fix]:
        state["dropped"][reason] += 1
        return []

    def _release(self, state: dict, watermark: datetime) -> list[Fix]:
        released = []
        while state["buffer"]:
            fix = Fix.from_dict(state["buffer"][0])
            if fix.timestamp > watermark:
                break
            state["buffer"].pop(0)
            state["last_released"] = fix.to_dict()
            if self._too_fast(state, fix):
                state["rejected_run"] += 1
                state["dropped"]["speed"] += 1
                continue
            state["rejected_run"] = 0
            state["anchor"] = fix.to_dict()
            released.append(fix)
        return released

    def _too_fast(self, state: dict, fix: Fix) -> bool:
        if state["anchor"] is None:
            return False
        if state["rejected_run"] >= self.config.max_consecutive_rejects:
            return False
        anchor = Fix.from_dict(state["anchor"])
        seconds = (fix.timestamp - anchor.timestamp).total_seconds()
        distance = haversine_m(anchor.lat, anchor.lon, fix.lat, fix.lon)
        distance = max(0.0, distance - 2 * self.config.gps_error_m)
        return distance > self.config.max_speed_mps * seconds


def _init(state: dict) -> None:
    """Fill in an empty state dict with the cleaner's fields."""
    state.setdefault("buffer", [])
    state.setdefault("newest", None)
    state.setdefault("last_released", None)
    state.setdefault("anchor", None)
    state.setdefault("rejected_run", 0)
    state.setdefault("dropped", dict.fromkeys(DROP_REASONS, 0))
