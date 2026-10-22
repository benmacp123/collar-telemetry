"""Synthetic mortality events for tracks that contain no real deaths.

The jackal and elephant tracks stop at or before death, so the mortality
detector cannot be scored on them directly. ``inject_mortality`` cuts a
real track at a chosen time and replaces what follows with the fixes a
collar on a carcass would report:

- **Same schedule.** Synthetic fixes keep the original track's timestamps,
  so duty cycles and fix intervals stay as the real collar had them.
- **Missed fixes.** Each scheduled fix succeeds with ``fix_success``. A
  collar on a carcass is often tilted or lying under the body, and tilt
  cuts fix success sharply (D'Eon & Delparte 2005; Belant 2009).
  Provisional: 0.7.
- **GPS scatter.** Each fix lands a lognormal distance in a uniform random
  direction from the carcass, with median ``scatter_median_m`` and 95th
  percentile ``scatter_p95_m``. Observed: dead vultures in the tuning set
  scatter around their final position with a median of 16 m and a 95th
  percentile of 59 m (5 deployments, 337 fixes), in line with stationary
  collar tests in the literature (median 6-17 m; Belant 2009; Adams et al.
  2013).
- **Collar life.** The collar reports for ``duration`` after death, then
  stops. Provisional: 7 days; observed stationary tails of dead vultures
  run 53-337 h when the collar keeps reporting at all. Most dead vulture
  tracks (12 of 17) instead stop within hours, which is the gap detector's
  case rather than this one.

Every injected event is synthetic and must be reported as such. The death
time is the evaluation's "death start": the start of the final stationary
period.

References:
    Adams AL, Dickinson KJM, Robertson BC, van Heezik Y (2013) PLoS ONE
        8:e68496. https://doi.org/10.1371/journal.pone.0068496
    Belant JL (2009) Northeast. Nat. 16:577-584.
    D'Eon RG, Delparte D (2005) J. Appl. Ecol. 42:383-388.
        https://doi.org/10.1111/j.1365-2664.2005.01010.x
"""

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.core.fixes import Fix
from telemetry.core.geo import offset

# z-score of the 95th percentile of a standard normal.
Z95 = 1.6448536269514722


@dataclass(frozen=True)
class CarcassConfig:
    """How a collar on a carcass behaves.

    Attributes:
        fix_success: Chance each scheduled fix is recorded.
        scatter_median_m: Median distance of a fix from the carcass.
        scatter_p95_m: 95th percentile of that distance.
        duration: How long after death the collar keeps reporting.
    """

    fix_success: float = 0.7
    scatter_median_m: float = 16.0
    scatter_p95_m: float = 59.0
    duration: timedelta = timedelta(days=7)


@dataclass(frozen=True)
class SyntheticDeath:
    """A track with an injected mortality event.

    Attributes:
        fixes: The track: real fixes up to the death, synthetic after it.
        death_time: Time of the last real fix, where the animal stops.
        lat: Latitude of the carcass.
        lon: Longitude of the carcass.
    """

    fixes: list[Fix]
    death_time: datetime
    lat: float
    lon: float


def scatter_distance(config: CarcassConfig, rng: random.Random) -> float:
    """Draw one fix's distance from the carcass.

    Args:
        config: Carcass settings giving the median and 95th percentile.
        rng: Seeded random source.

    Returns:
        float: Distance in metres.
    """
    sigma = math.log(config.scatter_p95_m / config.scatter_median_m) / Z95
    return rng.lognormvariate(math.log(config.scatter_median_m), sigma)


def choose_death_time(
    fixes: list[Fix], rng: random.Random, warmup: timedelta, duration: timedelta
) -> datetime:
    """Pick a fix time at which to inject a death.

    The death falls after ``warmup`` from the first fix, so detectors have
    a baseline, and at least ``duration`` before the last, so the collar's
    own schedule covers the whole carcass period.

    Args:
        fixes: One deployment's fixes, in time order.
        rng: Seeded random source.
        warmup: Shortest time from the first fix to the death.
        duration: Time the carcass period needs after the death.

    Returns:
        datetime: Timestamp of the chosen fix.

    Raises:
        ValueError: If the track is too short for both margins.
    """
    first, last = fixes[0].timestamp, fixes[-1].timestamp
    candidates = [
        fix.timestamp
        for fix in fixes
        if first + warmup <= fix.timestamp <= last - duration
    ]
    if not candidates:
        raise ValueError("track too short for the warm-up and carcass period")
    return rng.choice(candidates)


def inject_mortality(
    fixes: list[Fix],
    death_time: datetime,
    rng: random.Random,
    config: CarcassConfig | None = None,
) -> SyntheticDeath:
    """Replace a track after ``death_time`` with a carcass's fixes.

    Args:
        fixes: One deployment's fixes, in time order.
        death_time: When the animal dies; the last fix at or before it
            marks the carcass.
        rng: Seeded random source.
        config: Carcass settings; the documented defaults if omitted.

    Returns:
        SyntheticDeath: The new track and where and when the death is.

    Raises:
        ValueError: If no fix falls at or before ``death_time``.
    """
    config = config or CarcassConfig()
    before = [fix for fix in fixes if fix.timestamp <= death_time]
    if not before:
        raise ValueError("death_time is before the track starts")
    carcass = before[-1]
    end = carcass.timestamp + config.duration
    after = []
    for fix in fixes[len(before) :]:
        if fix.timestamp > end:
            break
        if rng.random() >= config.fix_success:
            continue
        lat, lon = offset(
            carcass.lat,
            carcass.lon,
            rng.uniform(0.0, 360.0),
            scatter_distance(config, rng),
        )
        after.append(Fix(fix.deployment_id, fix.timestamp, lat, lon))
    return SyntheticDeath(before + after, carcass.timestamp, carcass.lat, carcass.lon)
