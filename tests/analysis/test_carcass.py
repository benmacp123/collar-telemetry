"""Tests for measuring collar behaviour on carcasses.

Tracks are hand-built, so no test looks at the vulture scoring set.
"""

from datetime import datetime, timedelta, timezone

import pytest

from telemetry.analysis.carcass import (
    carcass_tail,
    per_day,
    profile,
    repeat_share,
    repeats,
    still_window_scatter,
)
from telemetry.analysis.evaluation import ALIVE, DEAD, SCORING, TUNING, Truth
from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m, offset

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
LAT, LON = -19.0, 15.5


def dying(still_every=1, repeat_every=0, deployment_id="A"):
    """20 days walking with hourly fixes, then 4 days still at one spot.

    Still fixes come every ``still_every`` hours and lie 20 m from the
    spot, cycling north, east, south and west so the median position is
    the spot; every ``repeat_every``-th of them (if set) repeats the
    previous position exactly instead.
    """
    fixes = [
        Fix(deployment_id, START + h * HOUR, LAT + h * 0.005, LON)
        for h in range(20 * 24)
    ]
    death = fixes[-1].timestamp + HOUR
    spot = (fixes[-1].lat + 0.005, LON)
    fresh = 0
    for k, h in enumerate(range(0, 4 * 24 + 1, still_every)):
        if repeat_every and k % repeat_every == repeat_every - 1:
            lat, lon = fixes[-1].lat, fixes[-1].lon
        else:
            lat, lon = offset(*spot, 90.0 * (fresh % 4), 20.0)
            fresh += 1
        fixes.append(Fix(deployment_id, death + h * HOUR, lat, lon))
    return fixes, death


def truth(fixes, still_start, label=DEAD, split=TUNING):
    """A truth record for a hand-built track."""
    return Truth(
        deployment_id=fixes[0].deployment_id,
        taxon="Cathartes aura",
        label=label,
        split=split,
        first_fix=fixes[0].timestamp,
        last_fix=fixes[-1].timestamp,
        still_start=still_start,
        still_start_wide=still_start,
        carcass_min=timedelta(hours=24),
    )


def test_rate_counts_intervals_not_fixes():
    """Three fixes over two days are one a day, not one and a half."""
    fixes = [Fix("A", START + i * DAY, LAT, LON + i) for i in range(3)]
    assert per_day(fixes) == pytest.approx(1.0)
    assert per_day(fixes[:1]) == 0.0


def test_repeats_flag_exact_coordinate_copies_only():
    """Only a fix at exactly the previous position counts as a repeat."""
    fixes = [
        Fix("A", START, LAT, LON),
        Fix("A", START + HOUR, LAT, LON),
        Fix("A", START + 2 * HOUR, LAT, LON + 1e-6),
    ]
    assert repeats(fixes) == [False, True, False]
    assert repeat_share(fixes) == pytest.approx(0.5)


def test_full_rate_carcass_has_ratio_one_and_true_scatter():
    """A carcass collar on its live schedule has ratio 1 and 20 m scatter."""
    fixes, death = dying()
    tail, distances = carcass_tail(truth(fixes, death), fixes)
    assert tail.ratio == pytest.approx(1.0, abs=0.02)
    assert not tail.sparse
    assert all(d == pytest.approx(20.0, abs=0.5) for d in distances)


def test_repeats_count_as_missed_fixes_and_leave_the_scatter():
    """Repeated positions lower the ratio and are not scored as 0 m scatter."""
    fixes, death = dying(repeat_every=2)
    tail, distances = carcass_tail(truth(fixes, death), fixes)
    assert tail.ratio == pytest.approx(0.5, abs=0.03)
    assert tail.ratio_with_repeats == pytest.approx(1.0, abs=0.02)
    assert tail.repeats == len(distances) - 1
    assert min(distances) > 15.0


def test_rare_fixes_make_a_sparse_carcass():
    """A collar sending one fix in eight hours on the carcass is sparse."""
    fixes, death = dying(still_every=8)
    tail, _ = carcass_tail(truth(fixes, death), fixes)
    assert tail.ratio == pytest.approx(0.125, abs=0.02)
    assert tail.sparse


def test_profile_reads_only_tuning_set_carcasses():
    """Scoring-set and living deployments never enter the profile."""
    reporting, death = dying(deployment_id="R")
    sparse, _ = dying(still_every=8, deployment_id="S")
    held_out, _ = dying(deployment_id="H")
    alive, _ = dying(deployment_id="L")
    truths = [
        truth(reporting, death),
        truth(sparse, death),
        truth(held_out, death, split=SCORING),
        truth(alive, death, label=ALIVE),
    ]
    by_deployment = {f[0].deployment_id: f for f in (reporting, sparse, held_out)}
    result = profile(truths, by_deployment)
    assert [t["deployment_id"] for t in result["tails"]] == ["R", "S"]
    assert result["sparse_share"] == 0.5
    assert result["scatter_median_m"] == pytest.approx(20.0, abs=0.5)


def test_still_windows_pick_the_quietest_stretch():
    """The stillest windows of a mostly moving track show only the jitter."""
    moving = [Fix("A", START + h * HOUR, LAT + h * 0.01, LON) for h in range(54)]
    resting = [
        Fix("A", START + (54 + k) * HOUR, *offset(LAT + 0.6, LON, 0.0, 5.0 * (k % 2)))
        for k in range(6)
    ]
    distances = still_window_scatter(moving + resting)
    assert len(distances) == 6
    assert max(distances) <= 5.0
    centre = (LAT + 0.6, LON)
    assert haversine_m(*centre, resting[1].lat, resting[1].lon) == pytest.approx(5.0)
