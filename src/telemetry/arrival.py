"""Seeded arrival scenarios: when each fix would reach the pipeline.

A collar takes fixes on one schedule and transmits them on another. The
replay runner feeds fixes in *arrival* order, so results reflect upload
delay, backlogs, late fixes and duplicates, not an ideal feed. Each
scenario models one upload pattern:

- **Uploads** happen every ``upload_every`` from a per-deployment phase
  drawn at random, so collars do not all upload at the same instant. A fix
  goes out in the first upload at or after the time it was taken.
- **Coverage outages** (GSM): each UTC day is out of coverage with
  probability ``outage_day_share``. Uploads on such days do not happen and
  fixes wait for the next covered upload. A stored backlog is sent oldest
  first, so it arrives late but in order for that collar.
- **Failed sends** (``retry_share``): each attempt to send a fix fails
  independently and the fix is retried at the next covered upload. This
  is what puts a collar's fixes out of order, since newer fixes have
  already gone.
- **Duplicates** (``duplicate_share``): a fix that arrived is sent again at
  the next covered upload, as when the collar misses an acknowledgement.

Within one upload, fixes arrive in the order they were taken. Each
scenario also gives the cleaner's ``max_lateness``: long enough to put
retried fixes back in order, and no longer, since holding fixes delays
every alert.

Randomness comes from ``random.Random`` seeded with the scenario seed and
the deployment ID, so a deployment's arrivals do not change when other
deployments or studies are added. The upload phase and outage days use a
separate stream from the per-fix draws, so changing the retry or duplicate
rate leaves the coverage pattern as it was. All numbers are provisional, chosen to
resemble vendor upload plans (Telonics and Telemetry Solutions GPS/Iridium
specifications: daily or every-other-day uplinks, many fixes per message);
results are reported for every scenario rather than tuned to one.
"""

import heapq
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from telemetry.fixes import Fix


@dataclass(frozen=True)
class ArrivalScenario:
    """One upload pattern.

    Attributes:
        name: Short name used in results.
        upload_every: Time between uploads; None means every fix arrives
            the moment it is taken.
        outage_day_share: Share of UTC days with no coverage.
        retry_share: Chance that one attempt to send a fix fails.
        duplicate_share: Chance that an arrived fix is sent again.
        max_lateness: Cleaner hold time suited to this scenario.
    """

    name: str
    upload_every: timedelta | None
    outage_day_share: float = 0.0
    retry_share: float = 0.0
    duplicate_share: float = 0.0
    max_lateness: timedelta = timedelta(0)

    def __post_init__(self):
        """Reject shares that would never deliver a fix.

        Raises:
            ValueError: If a share is outside [0, 1).
        """
        for name in ("outage_day_share", "retry_share", "duplicate_share"):
            if not 0.0 <= getattr(self, name) < 1.0:
                raise ValueError(f"{name} must be in [0, 1)")


SCENARIOS: dict[str, ArrivalScenario] = {
    scenario.name: scenario
    for scenario in (
        # Baseline: no transmission effects at all.
        ArrivalScenario("ideal", None),
        # Iridium-style daily uplink. Satellite delivery is taken as
        # reliable and in order, so the cleaner need not hold fixes.
        ArrivalScenario("satellite_daily", timedelta(days=1)),
        # The cheaper every-other-day uplink tier.
        ArrivalScenario("satellite_2day", timedelta(days=2)),
        # GSM: hourly while in coverage. A fix retried k times arrives k
        # uploads late with probability 0.05 ** k, so a 3 h hold reorders
        # nearly all ordinary retries. A backlog fix from an outage day
        # whose send fails after coverage returns arrives behind the new
        # day's fixes, up to about a day late; the hold does not cover
        # that (it would delay every alert by a day), so the cleaner drops
        # such fixes as late, about 1% of fixes, and counts them.
        ArrivalScenario(
            "gsm",
            timedelta(hours=1),
            outage_day_share=0.10,
            retry_share=0.05,
            duplicate_share=0.01,
            max_lateness=timedelta(hours=3),
        ),
    )
}


@dataclass(frozen=True)
class Arrival:
    """One fix reaching the pipeline.

    Attributes:
        time: When the fix arrives.
        fix: The fix itself, unchanged.
    """

    time: datetime
    fix: Fix


class _Uploads:
    """The covered upload times of one deployment under one scenario."""

    def __init__(self, scenario: ArrivalScenario, start: datetime, rng: random.Random):
        """Fix the upload phase for a deployment.

        Args:
            scenario: The upload pattern; must have ``upload_every``.
            start: Time of the deployment's first fix.
            rng: Random source for the phase and outage days only.
        """
        self.every = scenario.upload_every
        self.outage_share = scenario.outage_day_share
        self.rng = rng
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0)
        # A whole-minute phase within one interval, so uploads look like a
        # schedule rather than arbitrary instants.
        minutes = int(self.every / timedelta(minutes=1))
        self.anchor = midnight + timedelta(minutes=rng.randrange(minutes))
        self.outage: dict[date, bool] = {}

    def _covered(self, when: datetime) -> bool:
        """Whether the collar has coverage on ``when``'s UTC day.

        Each day is drawn once, the first time it is asked about, from this
        schedule's own random source, so the pattern depends only on the
        seed and the track.

        Args:
            when: An upload time.

        Returns:
            bool: True if uploads happen that day.
        """
        day = when.date()
        if day not in self.outage:
            self.outage[day] = self.rng.random() < self.outage_share
        return not self.outage[day]

    def first_at_or_after(self, when: datetime) -> datetime:
        """The first covered upload at or after ``when``.

        Args:
            when: Earliest time the upload may happen.

        Returns:
            datetime: The upload time.
        """
        steps = max(0, -(-(when - self.anchor) // self.every))
        upload = self.anchor + steps * self.every
        while not self._covered(upload):
            upload += self.every
        return upload

    def next_after(self, upload: datetime) -> datetime:
        """The covered upload after ``upload``.

        Args:
            upload: An upload time.

        Returns:
            datetime: The next upload time.
        """
        return self.first_at_or_after(upload + self.every)


def simulate_arrival(
    fixes: list[Fix], scenario: ArrivalScenario, seed: int
) -> list[Arrival]:
    """Arrivals for one deployment's fixes under one scenario.

    Args:
        fixes: One deployment's fixes, in time order.
        scenario: The upload pattern.
        seed: Scenario seed; combined with the deployment ID.

    Returns:
        list[Arrival]: Every arrival, duplicates included, in arrival
        order; fixes in the same upload keep the order they were taken.

    Raises:
        ValueError: If the fixes span more than one deployment.
    """
    if not fixes:
        return []
    deployment_id = fixes[0].deployment_id
    if any(fix.deployment_id != deployment_id for fix in fixes):
        raise ValueError("simulate_arrival takes one deployment at a time")
    if scenario.upload_every is None:
        return [Arrival(fix.timestamp, fix) for fix in fixes]

    key = f"{seed}:{scenario.name}:{deployment_id}"
    uploads = _Uploads(scenario, fixes[0].timestamp, random.Random(f"{key}:uploads"))
    rng = random.Random(f"{key}:fixes")
    arrivals = []
    for index, fix in enumerate(fixes):
        upload = uploads.first_at_or_after(fix.timestamp)
        while rng.random() < scenario.retry_share:
            upload = uploads.next_after(upload)
        # The index breaks ties so one upload keeps the order fixes were
        # taken in.
        arrivals.append((upload, index, Arrival(upload, fix)))
        if rng.random() < scenario.duplicate_share:
            again = uploads.next_after(upload)
            arrivals.append((again, index, Arrival(again, fix)))
    arrivals.sort(key=lambda item: item[:2])
    return [arrival for _, _, arrival in arrivals]


def merge_arrivals(streams: list[list[Arrival]]) -> list[Arrival]:
    """Interleave several deployments' arrivals into one feed.

    Args:
        streams: Per-deployment arrivals, each in arrival order.

    Returns:
        list[Arrival]: All arrivals in arrival order; ties go to the
        deployment with the lower ID, so the feed is reproducible.
    """
    keyed = [
        [(a.time, a.fix.deployment_id, i, a) for i, a in enumerate(stream)]
        for stream in streams
    ]
    return [item[3] for item in heapq.merge(*keyed, key=lambda item: item[:3])]
