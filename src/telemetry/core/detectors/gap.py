"""Data-gap detector: a collar that has gone quiet for longer than usual.

Many collars are duty-cycled, for example off overnight, so a plain "no fix
for N hours" rule would alert every night. The detector instead learns two
things from each deployment's own fixes:

- **When the collar is normally on:** a histogram of clock hours with at
  least one fix, by hour of day (UTC), with older hours weighted down over
  time so it follows schedule changes. Each clock hour counts once however
  many fixes it holds, so a tag that fixes every minute in short bursts
  does not look active only in its busiest hours. An hour of day is active
  if it holds at least ``active_fraction`` of the busiest hour's weight.
- **How often it normally fixes:** the median of recent intervals.

On each clock tick it raises one alert when both hold:

- the silence since the last fix, counting only active hours, exceeds
  ``max(factor * expected interval, min_silence)``; and
- the silence on the clock exceeds ``allowance``, the time fixes may
  legitimately take to arrive (for example a daily upload). Upload delay
  runs on the clock whether or not the collar is on, so it is not counted
  in active hours; doing so made a tag that is on a few hours a day wait
  many days before alerting.

The next fix resolves it (reason ``fix_received``) and re-arms the detector.

Silence is measured from the last fix the detector has seen. Behind a
``Cleaner`` that lags arrival by up to the cleaner's ``max_lateness``, so
``min_silence`` should comfortably exceed it.
"""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.core.fixes import Fix
from telemetry.core.alerts import RESOLVED, Alert

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class GapConfig:
    """Gap detector settings. Defaults are provisional, not yet chosen on
    the tuning set.

    Attributes:
        factor: Silence, in expected intervals, before alerting.
        min_silence: Shortest silence, in active hours, that can alert,
            whatever the interval; keeps fast-fixing tags from alerting on
            short drops.
        allowance: Silence on the clock always allowed before alerting,
            for upload delay.
        warmup: Time from the first fix before the detector may alert, so
            the schedule has been seen.
        half_life: Half-life of the hour-of-day histogram's memory.
        active_fraction: Share of the busiest hour's weight an hour needs
            to count as one the collar is normally on.
        history: Number of recent intervals the median is taken over.
    """

    factor: float = 3.0
    min_silence: timedelta = timedelta(hours=6)
    allowance: timedelta = timedelta(0)
    warmup: timedelta = timedelta(days=3)
    half_life: timedelta = timedelta(days=14)
    active_fraction: float = 0.25
    history: int = 50


def active_hours(weights: list[float], active_fraction: float) -> set[int]:
    """Hours of day (UTC) whose weight marks them as normally active.

    Args:
        weights: 24 values, one per hour of day, holding the decayed count
            of clock hours with a fix seen in that hour.
        active_fraction: Share of the busiest hour's weight an hour needs
            to count as one the collar is normally on.

    Returns:
        set[int]: Active hours (0-23); empty if no fixes have been seen.
    """
    peak = max(weights, default=0.0)
    if peak <= 0:
        return set()
    return {
        hour for hour, weight in enumerate(weights) if weight >= active_fraction * peak
    }


def active_silence(
    start: datetime, end: datetime, hours: set[int], limit: timedelta
) -> timedelta:
    """Time between ``start`` and ``end`` that falls in active hours.

    Stops counting once ``limit`` is reached, so long silences stay cheap.

    Args:
        start: Start of the silence (the last fix).
        end: End of the silence (now).
        hours: Active hours of day (0-23, UTC).
        limit: Duration after which counting stops.

    Returns:
        timedelta: Active time in the silence, capped at about ``limit``.
    """
    total = timedelta(0)
    cursor = start
    # Walk the silence one clock hour at a time, counting the part of each
    # hour that falls in an active hour of day.
    while cursor < end and total < limit:
        slot_end = min(cursor.replace(minute=0, second=0, microsecond=0) + HOUR, end)
        if cursor.hour in hours:
            total += slot_end - cursor
        cursor = slot_end
    return total


class GapDetector:
    """Alerts when a collar is silent through hours it is normally on."""

    name = "gap"

    def __init__(self, config: GapConfig | None = None):
        """Create a gap detector.

        Args:
            config: Detector settings; the provisional defaults if omitted.
        """
        self.config = config or GapConfig()

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Learn from a clean fix and re-arm after a silence.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment the fix belongs to, named in any
                resolve.
            fix: The next clean fix, in time order.

        Returns:
            list[Alert]: A resolve if a gap alert was open, otherwise empty;
            gaps themselves are only found on clock ticks.
        """
        if "weights" not in state:
            state.update(
                first=fix.timestamp.isoformat(),
                last=None,
                weights=[0.0] * 24,
                weighted_at=fix.timestamp.isoformat(),
                intervals=[],
                open=False,
            )
        if state["last"] is not None:
            minutes = (
                fix.timestamp - datetime.fromisoformat(state["last"])
            ).total_seconds() / 60
            if minutes > 0:
                state["intervals"] = (state["intervals"] + [minutes])[
                    -self.config.history :
                ]
        # Fade the histogram by the time since it was last updated, then add
        # this fix, so a change of schedule shows within a few half-lives.
        elapsed = fix.timestamp - datetime.fromisoformat(state["weighted_at"])
        decay = 0.5 ** (max(elapsed, timedelta(0)) / self.config.half_life)
        state["weights"] = [weight * decay for weight in state["weights"]]
        slot = fix.timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        if state.get("slot") != slot:
            state["weights"][fix.timestamp.hour] += 1.0
            state["slot"] = slot
        state["weighted_at"] = fix.timestamp.isoformat()
        alerts = []
        if state["open"]:
            message = (
                f"Collar reporting again: fix at {fix.timestamp:%Y-%m-%d %H:%M} "
                f"UTC after silence since "
                f"{datetime.fromisoformat(state['last']):%Y-%m-%d %H:%M} UTC"
            )
            alerts.append(
                Alert(
                    deployment_id,
                    self.name,
                    fix.timestamp,
                    message,
                    RESOLVED,
                    "fix_received",
                )
            )
        state["last"] = fix.timestamp.isoformat()
        state["open"] = False
        return alerts

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Alert once if the collar has been silent too long.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment being checked, named in the alert.
            now: Current time (replay or wall-clock).

        Returns:
            list[Alert]: One alert when a silence first crosses the
            threshold, otherwise empty.
        """
        # Nothing to judge against yet, or this silence is already alerted.
        if not state.get("intervals") or state["open"]:
            return []
        if now - datetime.fromisoformat(state["first"]) < self.config.warmup:
            return []
        last = datetime.fromisoformat(state["last"])
        if now - last < self.config.allowance:
            return []
        expected = timedelta(minutes=statistics.median(state["intervals"]))
        threshold = max(self.config.factor * expected, self.config.min_silence)
        hours = active_hours(state["weights"], self.config.active_fraction)
        silence = active_silence(last, now, hours, threshold)
        if silence < threshold:
            return []
        state["open"] = True
        message = (
            f"No fix for {(now - last) / HOUR:.0f} h, including "
            f"{threshold / HOUR:.1f} h of the collar's normal hours "
            f"(usually every {expected / timedelta(minutes=1):.0f} min); "
            f"last fix {last:%Y-%m-%d %H:%M} UTC"
        )
        return [Alert(deployment_id, self.name, now, message)]
