"""Synthetic mortality events for tracks that contain no real deaths.

The jackal and elephant tracks stop at or before death, so the mortality
detector cannot be scored on them directly. ``inject_mortality`` cuts a
real track at a chosen time and replaces what follows with the fixes a
collar on a carcass would report. Measured values come from
``make carcass`` (``results/carcass/carcass.json``: dead vultures in the
tuning set, 6 carcasses), and ``CarcassConfig``'s defaults must match it:

- **Same schedule.** Synthetic fixes keep the original track's timestamps,
  so duty cycles and fix intervals stay as the real collar had them.
- **Two regimes of missed fixes.** Each carcass is drawn as *reporting*
  or *sparse*, then each scheduled fix succeeds with that regime's
  chance. A collar on a carcass is often tilted or lying under the body,
  and tilt cuts fix success sharply (D'Eon & Delparte 2005; Belant 2009),
  but not on every carcass: dead vultures either keep 0.43-0.73 of their
  live rate of new positions or fall to 0.08-0.15, with none between.
  Observed: half sparse, medians 0.54 and 0.14. A single per-fix rate
  would never produce the sparse tails that the mortality detector misses
  on real carcasses. The chance applies to fixes the real collar
  recorded, so it is a ratio to the live rate.
- **GPS scatter.** Each fix lands a lognormal distance in a uniform random
  direction from the carcass, with median ``scatter_median_m`` and 95th
  percentile ``scatter_p95_m``. Observed on the dead vultures, leaving
  out positions that exactly repeat the previous fix (the vulture tags
  resend positions, the mammal collars rarely do): median 15.9 m, 95th
  percentile 36.5 m, in line with stationary collar tests (median
  6-17 m; Belant 2009; Adams et al. 2013) and with the elephants' stillest
  windows (median 11 m, an upper bound).
- **Collar life.** The collar reports for ``duration`` after death, or
  until the real track ends. Provisional: 30 days. The vulture tags are
  solar powered and most (12 of 17 dead) stop within hours, plausibly
  with the panel under the body; the mammal collars are assumed to be
  battery powered and to keep going (not confirmed for these collars).

No separate dropped-collar case: a collar that falls off lies still like
a reporting carcass, and one cut off and destroyed goes silent, which is
the gap detector's case.

Every injected event is synthetic and must be reported as such. The death
time is meant to be the evaluation's "death start", the start of the final
stationary period; the evaluation computes that from the fixes, as for real
deaths, and reports how far it falls from the injected time.

``synthetic_study`` turns a whole study into a labelled synthetic variant:
each deployment dies once in each regime at the same time, so the two
regimes are compared on the same tracks.

References:
    Adams AL, Dickinson KJM, Robertson BC, van Heezik Y (2013) PLoS ONE
        8:e68496. https://doi.org/10.1371/journal.pone.0068496
    Belant JL (2009) Northeast. Nat. 16:577-584.
    D'Eon RG, Delparte D (2005) J. Appl. Ecol. 42:383-388.
        https://doi.org/10.1111/j.1365-2664.2005.01010.x
"""

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset

# z-score of the 95th percentile of a standard normal.
Z95 = 1.6448536269514722

REPORTING = "reporting"
SPARSE = "sparse"
REGIMES = (REPORTING, SPARSE)
SYNTHETIC_END = "dead"
# Joins a real deployment ID and a regime into a synthetic one. Movebank IDs
# in the committed studies never contain it.
SEPARATOR = "~"
WARMUP = timedelta(days=7)
COVER = timedelta(days=7)


@dataclass(frozen=True)
class CarcassConfig:
    """How a collar on a carcass behaves.

    Attributes:
        reporting_success: Chance each scheduled fix is recorded on a
            reporting carcass.
        sparse_success: The same on a sparse carcass.
        sparse_share: Chance a carcass is sparse.
        scatter_median_m: Median distance of a fix from the carcass.
        scatter_p95_m: 95th percentile of that distance.
        duration: How long after death the collar keeps reporting, if the
            real track lasts that long.
    """

    reporting_success: float = 0.538
    sparse_success: float = 0.141
    sparse_share: float = 0.5
    scatter_median_m: float = 15.9
    scatter_p95_m: float = 36.5
    duration: timedelta = timedelta(days=30)


@dataclass(frozen=True)
class SyntheticDeath:
    """A track with an injected mortality event.

    Attributes:
        fixes: The track: real fixes up to the death, synthetic after it.
        death_time: Time of the last real fix, where the animal stops.
        lat: Latitude of the carcass.
        lon: Longitude of the carcass.
        sparse: Whether the carcass is in the sparse regime.
    """

    fixes: list[Fix]
    death_time: datetime
    lat: float
    lon: float
    sparse: bool


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
    fixes: list[Fix],
    rng: random.Random,
    warmup: timedelta,
    cover: timedelta,
    max_gap: timedelta = timedelta(hours=24),
) -> datetime:
    """Pick a fix time at which to inject a death.

    The death falls after ``warmup`` from the first fix, so detectors have
    a baseline, and at least ``cover`` before the last. The real collar
    must also have recorded fixes through that ``cover``, with no gap over
    ``max_gap``: a death just before a long outage would otherwise get no
    carcass fixes at all, a silent collar rather than a carcass.

    Args:
        fixes: One deployment's fixes, in time order.
        rng: Seeded random source.
        warmup: Shortest time from the first fix to the death.
        cover: Time after the death the real schedule must cover.
        max_gap: Longest gap allowed between fixes in that time, counting
            from the death and to the end of ``cover``.

    Returns:
        datetime: Timestamp of the chosen fix.

    Raises:
        ValueError: If no fix meets both margins and the coverage rule.
    """
    first, last = fixes[0].timestamp, fixes[-1].timestamp
    times = [fix.timestamp for fix in fixes]
    candidates = []
    for i, time in enumerate(times):
        if not first + warmup <= time <= last - cover:
            continue
        # Fixes after the death within the cover, bracketed by the death
        # and the end of the cover so silence at either edge counts too.
        edges = [time]
        for later in times[i + 1 :]:
            if later > time + cover:
                break
            edges.append(later)
        edges.append(time + cover)
        if all(b - a <= max_gap for a, b in zip(edges, edges[1:])):
            candidates.append(time)
    if not candidates:
        raise ValueError(
            "track too short or too gappy for the warm-up and carcass period"
        )
    return rng.choice(candidates)


def inject_mortality(
    fixes: list[Fix],
    death_time: datetime,
    rng: random.Random,
    config: CarcassConfig | None = None,
    sparse: bool | None = None,
) -> SyntheticDeath:
    """Replace a track after ``death_time`` with a carcass's fixes.

    Args:
        fixes: One deployment's fixes, in time order.
        death_time: When the animal dies; the last fix at or before it
            marks the carcass.
        rng: Seeded random source.
        config: Carcass settings; the documented defaults if omitted.
        sparse: Force the regime; drawn from ``config.sparse_share`` if
            None.

    Returns:
        SyntheticDeath: The new track and where and when the death is.

    Raises:
        ValueError: If no fix falls at or before ``death_time``.
    """
    config = config or CarcassConfig()
    before = [fix for fix in fixes if fix.timestamp <= death_time]
    if not before:
        raise ValueError("death_time is before the track starts")
    if sparse is None:
        sparse = rng.random() < config.sparse_share
    success = config.sparse_success if sparse else config.reporting_success
    carcass = before[-1]
    end = carcass.timestamp + config.duration
    after = []
    for fix in fixes[len(before) :]:
        if fix.timestamp > end:
            break
        if rng.random() >= success:
            continue
        lat, lon = offset(
            carcass.lat,
            carcass.lon,
            rng.uniform(0.0, 360.0),
            scatter_distance(config, rng),
        )
        after.append(Fix(fix.deployment_id, fix.timestamp, lat, lon))
    return SyntheticDeath(
        before + after, carcass.timestamp, carcass.lat, carcass.lon, sparse
    )


@dataclass(frozen=True)
class InjectedDeath:
    """What was injected into one synthetic deployment.

    Attributes:
        deployment_id: The synthetic deployment.
        source_id: The real deployment its track came from.
        regime: ``REPORTING`` or ``SPARSE``.
        death_time: Time of the last real fix.
        lat: Latitude of the carcass.
        lon: Longitude of the carcass.
        carcass_fixes: Synthetic fixes after the death.
    """

    deployment_id: str
    source_id: str
    regime: str
    death_time: datetime
    lat: float
    lon: float
    carcass_fixes: int

    def to_dict(self) -> dict:
        """The record as JSON-ready values.

        Returns:
            dict: Fields, with the death time in ISO 8601.
        """
        return {
            "deployment_id": self.deployment_id,
            "source_id": self.source_id,
            "regime": self.regime,
            "death_time": self.death_time.isoformat(),
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "carcass_fixes": self.carcass_fixes,
        }


@dataclass(frozen=True)
class SyntheticStudy:
    """A study's labelled synthetic variant.

    Attributes:
        deployments: Synthetic deployments, two per usable real one.
        fixes: Their fixes.
        deaths: What was injected, one per synthetic deployment.
        skipped: Real deployments with no usable death time, with the
            reason.
    """

    deployments: list[Deployment]
    fixes: list[Fix]
    deaths: list[InjectedDeath]
    skipped: dict[str, str] = field(default_factory=dict)


def synthetic_id(deployment_id: str, regime: str) -> str:
    """The ID of a deployment's synthetic copy in one regime.

    Args:
        deployment_id: The real deployment.
        regime: ``REPORTING`` or ``SPARSE``.

    Returns:
        str: ``<deployment_id>~<regime>``.
    """
    return f"{deployment_id}{SEPARATOR}{regime}"


def synthetic_study(
    deployments: list[Deployment],
    fixes: list[Fix],
    seed: int,
    config: CarcassConfig | None = None,
) -> SyntheticStudy:
    """Give every deployment a death in each carcass regime.

    The death time is drawn once per deployment, from a random source
    seeded by ``seed`` and the deployment ID, so adding or dropping one
    deployment changes no other. Each regime then draws its own carcass
    fixes. The synthetic deployments end ``SYNTHETIC_END`` at their last
    fix, so the evaluation labels them dead without an override.

    Args:
        deployments: The real study's deployments.
        fixes: Their fixes, in any order.
        seed: Seed for death times and carcass fixes.
        config: Carcass settings; the documented defaults if omitted.

    Returns:
        SyntheticStudy: The variant, with the deployments that could not
        take a death listed with the reason.
    """
    by_deployment = defaultdict(list)
    for fix in fixes:
        by_deployment[fix.deployment_id].append(fix)
    variant = SyntheticStudy([], [], [], {})
    for deployment in sorted(deployments, key=lambda d: d.deployment_id):
        own = sorted(
            by_deployment.get(deployment.deployment_id, []), key=lambda f: f.timestamp
        )
        if not own:
            continue
        # String seeds hash the same way on every run and platform.
        rng = random.Random(f"{seed}:{deployment.deployment_id}")
        try:
            death_time = choose_death_time(own, rng, WARMUP, COVER)
        except ValueError as error:
            variant.skipped[deployment.deployment_id] = str(error)
            continue
        for regime in REGIMES:
            new_id = synthetic_id(deployment.deployment_id, regime)
            event = inject_mortality(
                own,
                death_time,
                random.Random(f"{seed}:{new_id}"),
                config,
                sparse=regime == SPARSE,
            )
            track = [Fix(new_id, f.timestamp, f.lat, f.lon) for f in event.fixes]
            variant.deployments.append(
                Deployment(
                    new_id,
                    deployment.tag_id,
                    deployment.animal_id,
                    deployment.taxon,
                    deployment.deploy_on,
                    track[-1].timestamp,
                    SYNTHETIC_END,
                )
            )
            variant.fixes.extend(track)
            variant.deaths.append(
                InjectedDeath(
                    new_id,
                    deployment.deployment_id,
                    regime,
                    event.death_time,
                    event.lat,
                    event.lon,
                    len(event.fixes)
                    - sum(1 for f in event.fixes if f.timestamp <= event.death_time),
                )
            )
    return variant
