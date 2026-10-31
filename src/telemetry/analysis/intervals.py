"""Confidence intervals and the base-rate ceiling for alert precision.

Precision here is true alerts over true plus false ones. Two intervals
are given because they answer different questions: the Wilson interval
treats every alert as an independent trial, while the bootstrap
resamples whole deployments, so a bird that raises dozens of false
alerts moves the estimate as one unit. False alerts cluster on a few
birds, so the bootstrap is the wider and more honest of the two.
"""

import math

import numpy as np

Z_95 = 1.96
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 0


def wilson(successes: int, trials: int, z: float = Z_95) -> list[float] | None:
    """Wilson score interval for a binomial proportion.

    Preferred to the normal approximation because it stays inside 0-1
    and behaves at the small counts these alerts give (6 true of 192).

    Args:
        successes: True alerts.
        trials: True plus false alerts.
        z: Normal quantile; 1.96 gives 95%.

    Returns:
        list[float] | None: Lower and upper bounds to 0.000001, or None
        with no trials.
    """
    if trials == 0:
        return None
    p = successes / trials
    scale = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / scale
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials**2)) / scale
    return [round(centre - half, 6), round(centre + half, 6)]


def cluster_bootstrap(
    counts: list[tuple[int, int]],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> list[float] | None:
    """95% percentile bootstrap of pooled precision, resampling clusters.

    Each resample draws as many clusters as there are, with replacement,
    and pools their true and false counts. Resamples with no alerts at
    all are dropped. The generator is seeded on every call, so the result
    does not depend on what ran before.

    Args:
        counts: (true, false) alerts per cluster (deployment), in a fixed
            order.
        resamples: Number of resamples.
        seed: Seed for ``numpy.random.default_rng``.

    Returns:
        list[float] | None: The 2.5th and 97.5th percentiles to 0.000001,
        or None if there are no alerts.
    """
    tally = np.array(counts, dtype=float).reshape(-1, 2)
    if tally.sum() == 0:
        return None
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(tally), (resamples, len(tally)))
    true = tally[picks, 0].sum(axis=1)
    judged = true + tally[picks, 1].sum(axis=1)
    share = np.divide(true, judged, out=np.full(resamples, np.nan), where=judged > 0)
    low, high = np.nanpercentile(share, [2.5, 97.5])
    return [round(float(low), 6), round(float(high), 6)]


def ceiling(cases: int, false: int) -> float | None:
    """Precision of a detector that fires once on every case.

    At a given false-alert count this is the best precision possible,
    since no detector can raise more than one useful alert per death. A
    measured precision near it means the false-alert rate, not missed
    deaths, is what holds precision down.

    Args:
        cases: Deaths the detector is meant to catch.
        false: Its false alerts.

    Returns:
        float | None: The ceiling to 0.000001, or None with neither.
    """
    if cases + false == 0:
        return None
    return round(cases / (cases + false), 6)
