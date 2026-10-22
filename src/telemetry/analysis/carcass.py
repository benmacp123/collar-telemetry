"""How collars behave on carcasses, measured on dead vultures.

The synthetic mortality events (``telemetry.sim.synthetic``) need three
numbers for a collar on a carcass: how often it still gets a fix, how far
its fixes scatter, and whether that differs between carcasses. This
module measures them on the vulture tuning set's carcass deaths (dead
deployments whose final stationary period is at least ``CARCASS_MIN``),
so each value the synthetic model uses can be regenerated from committed
data. The scoring set is never read.

- **Fix rate ratio.** A carcass collar's fixes per day over its final
  stationary period, divided by its own rate over the 14 days before.
  Each fix rate counts intervals, not fixes, so a 3-fix tail is not
  credited with the fix that ends it. A ratio, not an absolute rate,
  because the synthetic model thins the real collar's own schedule.
  Fixes repeating the previous fix's exact coordinates are left out on
  both sides, as for the scatter: they carry no new position, and the
  mammal collars the model is applied to rarely send them.
  ``ratio_with_repeats`` keeps them, for comparison.
- **Regimes.** Carcasses fall into two groups rather than spreading round
  one rate: collars that keep reporting at about half their live rate or
  more, and sparse ones far below it (a tag under the body). A ratio
  below ``SPARSE_BELOW`` is sparse; 0.3 sits in the gap between the
  groups on the tuning set (0.08-0.15 against 0.43-0.73), so the split
  does not hang on its exact value.
- **Scatter.** Each tail fix's distance from the tail's median position,
  leaving out fixes whose coordinates exactly repeat the previous fix's.
  The vulture tags resend a position often enough (about half of some
  carcass tails) that counting the repeats would halve the median, and the
  mammal collars rarely do it (``repeat_share``).
- **Mammal check.** ``still_window_scatter`` gives a proxy for a mammal
  collar's GPS error: scatter in the stillest of its 6-fix windows. It is
  an upper bound, since a resting animal still shifts a little.
"""

import math
import statistics
from dataclasses import asdict, dataclass
from datetime import timedelta

from telemetry.analysis.evaluation import DEAD, TUNING, Truth
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m

DAY = timedelta(days=1)
LIVE_BEFORE = timedelta(days=14)
SPARSE_BELOW = 0.3
WINDOW_FIXES = 6
STILLEST_SHARE = 0.1


@dataclass(frozen=True)
class CarcassTail:
    """One carcass death's final stationary period.

    Attributes:
        deployment_id: The deployment.
        hours: Length of the stationary period.
        fixes: Fixes in it, the first included.
        repeats: Fixes repeating the previous fix's exact coordinates.
        live_per_day: Rate of new positions over the 14 days before it.
        tail_per_day: Rate of new positions within it.
        ratio: ``tail_per_day`` over ``live_per_day``.
        ratio_with_repeats: The same ratio counting repeated positions.
        sparse: Whether ``ratio`` is below ``SPARSE_BELOW``.
    """

    deployment_id: str
    hours: float
    fixes: int
    repeats: int
    live_per_day: float
    tail_per_day: float
    ratio: float
    ratio_with_repeats: float
    sparse: bool


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile, as the other reports use.

    Args:
        values: Values in any order; not empty.
        q: Quantile between 0 and 1.

    Returns:
        float: The value at rank ``q`` of the sorted values.
    """
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def per_day(fixes: list[Fix], skip_repeats: bool = False) -> float:
    """Fix rate over a run of fixes, counting intervals.

    Args:
        fixes: Fixes in time order.
        skip_repeats: Leave out fixes that repeat the previous fix's
            exact coordinates (the first fix still opens the span).

    Returns:
        float: Intervals per day between the first and last fix, or 0 if
        they span no time.
    """
    span = fixes[-1].timestamp - fixes[0].timestamp if fixes else timedelta(0)
    if not span:
        return 0.0
    counted = len(fixes) - (sum(repeats(fixes)) if skip_repeats else 0)
    return (counted - 1) / (span / DAY)


def repeats(fixes: list[Fix]) -> list[bool]:
    """Which fixes repeat the previous fix's exact coordinates.

    Args:
        fixes: Fixes in time order.

    Returns:
        list[bool]: One flag per fix; the first is never a repeat.
    """
    return [False] + [
        (a.lat, a.lon) == (b.lat, b.lon) for a, b in zip(fixes, fixes[1:])
    ]


def repeat_share(fixes: list[Fix]) -> float:
    """Share of a deployment's fixes that repeat the previous one exactly.

    Args:
        fixes: One deployment's fixes in time order.

    Returns:
        float: Repeats over fixes after the first, or 0 for one fix.
    """
    return sum(repeats(fixes)) / (len(fixes) - 1) if len(fixes) > 1 else 0.0


def is_carcass(truth: Truth) -> bool:
    """Whether a deployment is a tuning-set carcass death.

    Args:
        truth: The deployment's truth record.

    Returns:
        bool: True for a dead tuning-set deployment with a stationary end
        at least its ``CARCASS_MIN`` long.
    """
    return truth.split == TUNING and truth.label == DEAD and truth.carcass


def carcass_tail(truth: Truth, fixes: list[Fix]) -> tuple[CarcassTail, list[float]]:
    """Measure one carcass death's stationary period.

    Args:
        truth: The deployment's truth record, a carcass death.
        fixes: Its fixes in time order.

    Returns:
        The tail's measurements, and the scatter distances (metres from
        the tail's median position) of its non-repeated fixes.
    """
    tail = [f for f in fixes if f.timestamp >= truth.still_start]
    live = [
        f
        for f in fixes
        if truth.still_start - LIVE_BEFORE <= f.timestamp < truth.still_start
    ]
    lat = statistics.median(f.lat for f in tail)
    lon = statistics.median(f.lon for f in tail)
    flags = repeats(tail)
    distances = [
        haversine_m(lat, lon, f.lat, f.lon)
        for f, repeated in zip(tail, flags)
        if not repeated
    ]
    live_rate, tail_rate = per_day(live, True), per_day(tail, True)
    ratio = tail_rate / live_rate
    measured = CarcassTail(
        deployment_id=truth.deployment_id,
        hours=round(truth.still_hours, 1),
        fixes=len(tail),
        repeats=sum(flags),
        live_per_day=round(live_rate, 2),
        tail_per_day=round(tail_rate, 2),
        ratio=round(ratio, 3),
        ratio_with_repeats=round(per_day(tail) / per_day(live), 3),
        sparse=ratio < SPARSE_BELOW,
    )
    return measured, distances


def still_window_scatter(fixes: list[Fix]) -> list[float]:
    """Scatter in a deployment's stillest 6-fix windows.

    The track is cut into consecutive windows of ``WINDOW_FIXES`` fixes;
    each is scored by its fixes' median distance from the window's median
    position, and the stillest ``STILLEST_SHARE`` of windows are kept.

    Args:
        fixes: One deployment's fixes in time order.

    Returns:
        list[float]: Distances (metres) of every fix in the kept windows,
        or an empty list if the track is shorter than one window.
    """
    windows = []
    for i in range(0, len(fixes) - WINDOW_FIXES + 1, WINDOW_FIXES):
        window = fixes[i : i + WINDOW_FIXES]
        lat = statistics.median(f.lat for f in window)
        lon = statistics.median(f.lon for f in window)
        distances = [haversine_m(lat, lon, f.lat, f.lon) for f in window]
        windows.append((statistics.median(distances), distances))
    windows.sort(key=lambda w: w[0])
    kept = windows[: math.ceil(STILLEST_SHARE * len(windows))]
    return [d for _, distances in kept for d in distances]


def profile(
    truths: list[Truth], by_deployment: dict[str, list[Fix]]
) -> dict[str, object]:
    """Profile every tuning-set carcass death.

    Args:
        truths: Vulture truth records; only tuning-set carcass deaths are
            read.
        by_deployment: Each deployment's fixes in time order.

    Returns:
        dict: Per-carcass tails, and the pooled values the synthetic model
        uses: the share of sparse carcasses, each regime's median ratio
        (reporting capped at 1, since a carcass cannot outdo its own
        schedule) and the scatter median and 95th percentile.
    """
    tails, scatter = [], []
    for truth in truths:
        if not is_carcass(truth):
            continue
        tail, distances = carcass_tail(truth, by_deployment[truth.deployment_id])
        tails.append(tail)
        scatter += distances
    sparse = [t.ratio for t in tails if t.sparse]
    reporting = [min(1.0, t.ratio) for t in tails if not t.sparse]
    return {
        "carcasses": len(tails),
        "sparse_share": round(len(sparse) / len(tails), 3),
        "reporting_ratio": round(statistics.median(reporting), 3),
        "sparse_ratio": round(statistics.median(sparse), 3),
        "scatter_fixes": len(scatter),
        "scatter_median_m": round(statistics.median(scatter), 1),
        "scatter_p95_m": round(percentile(scatter, 0.95), 1),
        "tails": [asdict(t) for t in tails],
    }
