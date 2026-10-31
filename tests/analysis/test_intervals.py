"""Tests for the precision intervals and the base-rate ceiling."""

import numpy as np
import pytest

from telemetry.analysis.intervals import ceiling, cluster_bootstrap, wilson


@pytest.mark.parametrize(
    "successes, trials, expected",
    [
        # Published values: 0 of 10 and 5 of 10 (Newcombe 1998, method 3).
        (0, 10, [0.0, 0.2775]),
        (5, 10, [0.2366, 0.7634]),
        # The held-out mortality figure the post-mortem quotes.
        (6, 192, [0.0144, 0.0665]),
    ],
)
def test_wilson_matches_known_intervals(successes, trials, expected):
    """Wilson bounds match published values to four places."""
    assert wilson(successes, trials) == pytest.approx(expected, abs=5e-5)


def test_wilson_bounds_are_not_rounded_twice():
    """6 of 192 has an upper bound of 6.649%, which must print as 6.6%,
    not 6.7% via a stored 0.0665."""
    assert f"{wilson(6, 192)[1]:.1%}" == "6.6%"


def test_wilson_without_trials_is_none():
    """No judged alerts gives no interval rather than a division error."""
    assert wilson(0, 0) is None


def _looped_bootstrap(counts, resamples, seed):
    """The post-mortem's one-resample-at-a-time bootstrap, as a reference.

    Args:
        counts: (true, false) alerts per cluster.
        resamples: Number of resamples.
        seed: Generator seed.

    Returns:
        list[float]: The 2.5th and 97.5th percentiles to six places.
    """
    rng = np.random.default_rng(seed)
    tally = np.array(counts)
    shares = []
    for _ in range(resamples):
        picks = rng.integers(0, len(tally), len(tally))
        true, false = tally[picks, 0].sum(), tally[picks, 1].sum()
        shares.append(true / (true + false) if true + false else np.nan)
    return [round(float(v), 6) for v in np.nanpercentile(shares, [2.5, 97.5])]


def test_cluster_bootstrap_matches_the_looped_reference():
    """The vectorised bootstrap draws the same resamples as a plain loop,
    so it reproduces the post-mortem's intervals exactly."""
    counts = [(1, 3), (0, 12), (0, 0), (2, 40), (0, 5), (1, 0), (0, 9)]
    assert cluster_bootstrap(counts, 2000, 0) == _looped_bootstrap(counts, 2000, 0)


def test_cluster_bootstrap_pinned_value():
    """Seed 0 and 5000 resamples give a fixed interval, so reruns are
    byte-identical."""
    counts = [(1, 3), (0, 12), (0, 0), (2, 40), (0, 5), (1, 0), (0, 9)]
    assert cluster_bootstrap(counts) == cluster_bootstrap(counts)
    assert cluster_bootstrap(counts) == pytest.approx([0.0175, 0.1667], abs=5e-5)


def test_cluster_bootstrap_identical_clusters_give_a_point():
    """Clusters with the same precision leave nothing to resample."""
    assert cluster_bootstrap([(1, 3)] * 5) == [0.25, 0.25]


def test_cluster_bootstrap_resamples_clusters_not_alerts():
    """One bird holding most false alerts widens the bootstrap well past
    the Wilson interval on the same pooled counts."""
    counts = [(1, 1)] * 10 + [(0, 90)]
    low, high = cluster_bootstrap(counts)
    wilson_low, wilson_high = wilson(10, 110)
    assert high - low > 2 * (wilson_high - wilson_low)


def test_cluster_bootstrap_without_alerts_is_none():
    """No alerts on any deployment gives no interval."""
    assert cluster_bootstrap([(0, 0), (0, 0)]) is None


def test_ceiling_is_one_alert_per_case_at_the_false_count():
    """5 carcasses against 186 false alerts cap precision near 2.6%."""
    assert ceiling(5, 186) == pytest.approx(0.0262, abs=5e-5)
    assert ceiling(0, 0) is None
