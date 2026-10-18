"""Unusual-movement detector: travel far outside the animal's own normal.

In the field this catches a chase or poaching pursuit, a live animal or a
carcass being moved by vehicle, or an animal suddenly leaving its range.

**Metric.** At each fix the detector measures net displacement over the
trailing ``span``: the distance from the oldest fix within the span to the
newest. A fixed time span rather than single steps makes hourly and
1-minute tags comparable; net distance rather than path length stops GPS
jitter on fast tags adding up, and means one stray step cannot trigger an
alert. If a gap leaves the span less than ``min_coverage`` covered by
fixes there is no measurement, because distance across a gap is not speed.

**Baseline.** Each measurement goes into a histogram with log-spaced bins
(1 m to 1,000 km, about 26% wide), weighted down over time with
``half_life`` so the baseline follows seasonal changes. Quantiles are read
from the histogram, so state stays the same size however long the track.

**Alert.** After ``warmup`` and ``min_samples`` measurements, a
displacement above ``max(factor * quantile, min_displacement_m)`` raises
one alert. The floor stops an animal that barely moves alerting on a short
walk. The alert resolves, and the detector re-arms, once displacement
drops back to the quantile (reason ``normal``).

**Episodes do not teach the baseline.** Measurements taken while an alert
is open are left out of the histogram: a high quantile moves a lot with a
few extreme samples, so learning from one emergency would hide the next.
So that a lasting change of behaviour (a relocation, a range shift) cannot
keep the detector open and blind for good, an episode also closes after
``max_episode`` (reason ``expired``).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.fixes import Fix
from telemetry.geo import haversine_m
from telemetry.alerts import RESOLVED, Alert

# Histogram bins: edges at 10 ** (i / BINS_PER_DECADE) metres.
BINS_PER_DECADE = 10
DECADES = 6
N_BINS = BINS_PER_DECADE * DECADES


@dataclass(frozen=True)
class MovementConfig:
    """Unusual-movement settings. Defaults are provisional, not yet chosen
    on the tuning set, and ``min_displacement_m`` is species-specific.

    Attributes:
        span: Time over which net displacement is measured.
        min_coverage: Share of ``span`` the fixes must cover for a
            measurement to count.
        quantile: Quantile of the animal's own displacements taken as the
            top of normal.
        factor: How many times that quantile counts as unusual.
        min_displacement_m: Smallest displacement that can alert, in metres.
        warmup: Time from the first fix before the detector may alert.
        min_samples: Fewest measurements (by decayed weight) before alerting.
        half_life: Half-life of the baseline histogram's memory.
        max_episode: Longest an alert episode stays open, and so the
            longest the baseline stops learning, before re-arming anyway.
    """

    span: timedelta = timedelta(hours=3)
    min_coverage: float = 0.75
    quantile: float = 0.99
    factor: float = 2.0
    min_displacement_m: float = 2000.0
    warmup: timedelta = timedelta(days=7)
    min_samples: float = 50.0
    half_life: timedelta = timedelta(days=14)
    max_episode: timedelta = timedelta(hours=24)


def bin_index(metres: float) -> int:
    """Histogram bin for a displacement.

    Args:
        metres: Displacement in metres.

    Returns:
        int: Bin index, clamped to the histogram's range; anything under
        1 m goes in bin 0.
    """
    if metres < 1:
        return 0
    return min(int(math.log10(metres) * BINS_PER_DECADE), N_BINS - 1)


def bin_upper(index: int) -> float:
    """Upper edge of a histogram bin, in metres.

    Args:
        index: Bin index.

    Returns:
        float: The displacement at the top of the bin.
    """
    return 10 ** ((index + 1) / BINS_PER_DECADE)


def histogram_quantile(weights: list[float], quantile: float) -> float:
    """Displacement below which ``quantile`` of the weight lies.

    Uses each bin's upper edge, so the result errs high, towards fewer
    alerts.

    Args:
        weights: Decayed counts per bin.
        quantile: Between 0 and 1.

    Returns:
        float: Displacement in metres, or 0.0 for an empty histogram.
    """
    total = sum(weights)
    if total <= 0:
        return 0.0
    running = 0.0
    for index, weight in enumerate(weights):
        running += weight
        if running >= quantile * total:
            return bin_upper(index)
    return bin_upper(N_BINS - 1)


class MovementDetector:
    """Alerts when an animal travels far more than it usually does."""

    name = "movement"

    def __init__(self, config: MovementConfig | None = None):
        """Create an unusual-movement detector.

        Args:
            config: Detector settings; the provisional defaults if omitted.
        """
        self.config = config or MovementConfig()

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Measure displacement over the span, learn it, and alert if unusual.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment the fix belongs to, named in the alert.
            fix: The next clean fix, in time order.

        Returns:
            list[Alert]: An open when an episode starts, a resolve when it
            ends, otherwise empty.
        """
        if "window" not in state:
            state.update(
                first=fix.timestamp.isoformat(),
                window=[],
                weights=[0.0] * N_BINS,
                weighted_at=fix.timestamp.isoformat(),
                open=False,
                opened_at=None,
            )

        # Keep only the fixes inside the trailing span. Fixes arrive in time
        # order, so expired ones are always at the front.
        state["window"].append(fix.to_dict())
        cutoff = fix.timestamp - self.config.span
        while datetime.fromisoformat(state["window"][0]["timestamp"]) < cutoff:
            state["window"].pop(0)
        oldest = Fix.from_dict(state["window"][0])
        if (
            fix.timestamp - oldest.timestamp
            < self.config.min_coverage * self.config.span
        ):
            return []
        displacement = haversine_m(oldest.lat, oldest.lon, fix.lat, fix.lon)

        # Judge against the baseline before this measurement joins it, so an
        # unusual move cannot raise the bar it is measured against; and learn
        # nothing while an episode is open.
        alerts = self._judge(state, deployment_id, fix, oldest, displacement)
        if not state["open"]:
            self._learn(state, fix.timestamp, displacement)
        return alerts

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Do nothing: movement is only seen in fixes.

        Args:
            state: This detector's state for the deployment (unused).
            deployment_id: Deployment being checked (unused).
            now: Current time (unused).

        Returns:
            list[Alert]: Always empty.
        """
        # pylint: disable=unused-argument
        return []

    def _learn(self, state: dict, timestamp: datetime, displacement: float) -> None:
        """Fade the baseline by elapsed time and add one measurement.

        Args:
            state: This detector's state, updated in place.
            timestamp: Time of the measurement.
            displacement: Measured displacement in metres.
        """
        elapsed = timestamp - datetime.fromisoformat(state["weighted_at"])
        decay = 0.5 ** (max(elapsed, timedelta(0)) / self.config.half_life)
        state["weights"] = [weight * decay for weight in state["weights"]]
        state["weights"][bin_index(displacement)] += 1.0
        state["weighted_at"] = timestamp.isoformat()

    def _judge(
        self,
        state: dict,
        deployment_id: str,
        fix: Fix,
        oldest: Fix,
        displacement: float,
    ) -> list[Alert]:
        """Alert if this displacement starts an unusual episode.

        Args:
            state: This detector's state, updated in place.
            deployment_id: Deployment named in the alert.
            fix: The newest fix.
            oldest: The oldest fix in the span.
            displacement: Distance between them, in metres.

        Returns:
            list[Alert]: An open, a resolve, or none.
        """
        normal = histogram_quantile(state["weights"], self.config.quantile)
        if state["open"]:
            # Re-arm once movement is back within normal, or the episode has
            # lasted long enough that it may be the new normal.
            opened_at = datetime.fromisoformat(state["opened_at"])
            if displacement <= normal:
                reason = "normal"
                message = (
                    f"Movement back within normal: {displacement / 1000:.1f} km "
                    f"over the span, under this animal's "
                    f"{self.config.quantile:.0%} level ({normal / 1000:.1f} km)"
                )
            elif fix.timestamp - opened_at >= self.config.max_episode:
                reason = "expired"
                hours = self.config.max_episode / timedelta(hours=1)
                message = (
                    f"Unusual movement still under way after {hours:.0f} h; "
                    f"treating it as the new normal and learning from it"
                )
            else:
                return []
            state.update(open=False, opened_at=None)
            return [
                Alert(
                    deployment_id, self.name, fix.timestamp, message, RESOLVED, reason
                )
            ]
        if fix.timestamp - datetime.fromisoformat(state["first"]) < self.config.warmup:
            return []
        if sum(state["weights"]) < self.config.min_samples:
            return []
        threshold = max(self.config.factor * normal, self.config.min_displacement_m)
        if displacement <= threshold:
            return []
        state.update(open=True, opened_at=fix.timestamp.isoformat())
        hours = (fix.timestamp - oldest.timestamp) / timedelta(hours=1)
        message = (
            f"Unusual movement: {displacement / 1000:.1f} km in {hours:.1f} h, "
            f"{displacement / normal:.1f}x this animal's "
            f"{self.config.quantile:.0%} level ({normal / 1000:.1f} km); "
            f"from {oldest.lat:.5f}, {oldest.lon:.5f} "
            f"to {fix.lat:.5f}, {fix.lon:.5f}"
        )
        return [Alert(deployment_id, self.name, fix.timestamp, message)]
