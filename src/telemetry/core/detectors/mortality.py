"""Mortality detector: a tag that has stopped moving.

A dead animal, or a collar that has fallen off, keeps reporting the same
place give or take GPS error. The detector keeps one *stationary cluster*
per deployment: the bounding box of the fixes since the animal last moved.

- A fix **joins** the cluster if the box, stretched to include it, is
  still at most ``max_extent_m`` corner to corner. Using the box rather
  than distance from a running mean means a slow, steady walk eventually
  breaks the cluster instead of dragging its centre along.
- A fix outside the box is held as **pending**. One stray fix (a GPS
  outlier) is forgiven if the next fix is back inside; ``leave_fixes``
  pending fixes in a row mean the animal has moved, and a new cluster
  starts from them.
- The detector **alerts once** when the cluster has lasted ``window`` and
  holds at least ``min_fixes`` fixes, so two fixes a day apart are not
  enough evidence. When the animal moves, the alert resolves (reason
  ``moved``) at the fix that confirms the move, and the detector re-arms.

Roosting, resting and denning look the same as death for a while, so
``window`` must be longer than the species' longest normal rest (12-14 h
for roosting vultures). A tag that falls off also looks the same, so the
alert says "possible mortality or dropped tag".

Distances use the bounding box's corners, so the detector assumes tracks
do not cross the antimeridian.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from telemetry.core.fixes import Fix
from telemetry.core.geo import haversine_m
from telemetry.core.alerts import RESOLVED, Alert


@dataclass(frozen=True)
class MortalityConfig:
    """Mortality detector settings. Defaults are provisional, not yet
    chosen on the tuning set.

    Attributes:
        max_extent_m: Largest corner-to-corner size, in metres, of a
            cluster of fixes that still counts as not moving; must allow
            for GPS error.
        window: How long a cluster must last before alerting.
        min_fixes: Fewest fixes a cluster needs before it can alert.
        leave_fixes: Consecutive fixes outside the cluster that mean the
            animal has moved; fewer are treated as GPS outliers.
    """

    max_extent_m: float = 100.0
    window: timedelta = timedelta(hours=24)
    min_fixes: int = 6
    leave_fixes: int = 2


def new_cluster(fixes: list[Fix]) -> dict:
    """A cluster holding ``fixes``.

    Args:
        fixes: One or more fixes, oldest first.

    Returns:
        dict: JSON-ready cluster state: first and last fix times, fix
        count, bounding box and coordinate sums for the centre.
    """
    return {
        "start": fixes[0].timestamp.isoformat(),
        "last": fixes[-1].timestamp.isoformat(),
        "n": len(fixes),
        "min_lat": min(fix.lat for fix in fixes),
        "max_lat": max(fix.lat for fix in fixes),
        "min_lon": min(fix.lon for fix in fixes),
        "max_lon": max(fix.lon for fix in fixes),
        "sum_lat": sum(fix.lat for fix in fixes),
        "sum_lon": sum(fix.lon for fix in fixes),
    }


def extent(cluster: dict) -> float:
    """Corner-to-corner size of the cluster's bounding box.

    Args:
        cluster: Cluster state from ``new_cluster``.

    Returns:
        float: Diagonal of the bounding box, in metres.
    """
    return haversine_m(
        cluster["min_lat"], cluster["min_lon"], cluster["max_lat"], cluster["max_lon"]
    )


def extent_with(cluster: dict, fix: Fix) -> float:
    """Corner-to-corner size of the cluster's box if ``fix`` joined it.

    Args:
        cluster: Cluster state from ``new_cluster``.
        fix: The candidate fix.

    Returns:
        float: Diagonal of the stretched bounding box, in metres.
    """
    return haversine_m(
        min(cluster["min_lat"], fix.lat),
        min(cluster["min_lon"], fix.lon),
        max(cluster["max_lat"], fix.lat),
        max(cluster["max_lon"], fix.lon),
    )


def add_fix(cluster: dict, fix: Fix) -> None:
    """Add ``fix`` to the cluster in place.

    Args:
        cluster: Cluster state from ``new_cluster``, updated in place.
        fix: A fix that fits the cluster.
    """
    cluster["last"] = fix.timestamp.isoformat()
    cluster["n"] += 1
    cluster["min_lat"] = min(cluster["min_lat"], fix.lat)
    cluster["max_lat"] = max(cluster["max_lat"], fix.lat)
    cluster["min_lon"] = min(cluster["min_lon"], fix.lon)
    cluster["max_lon"] = max(cluster["max_lon"], fix.lon)
    cluster["sum_lat"] += fix.lat
    cluster["sum_lon"] += fix.lon


class MortalityDetector:
    """Alerts when a tag reports the same place for longer than ``window``."""

    name = "mortality"

    def __init__(self, config: MortalityConfig | None = None):
        """Create a mortality detector.

        Args:
            config: Detector settings; the provisional defaults if omitted.
        """
        self.config = config or MortalityConfig()

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Add a clean fix to the stationary cluster and alert if it is due.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment the fix belongs to, named in the alert.
            fix: The next clean fix, in time order.

        Returns:
            list[Alert]: An open when a cluster first qualifies, a resolve
            when the animal leaves an alerted cluster, otherwise empty.
        """
        if "cluster" not in state:
            state.update(cluster=new_cluster([fix]), pending=[], open=False)
            return []

        cluster = state["cluster"]
        resolved = []
        if extent_with(cluster, fix) <= self.config.max_extent_m:
            # Back inside: any pending fixes were outliers, not a departure.
            state["pending"] = []
            add_fix(cluster, fix)
        else:
            state["pending"].append(fix.to_dict())
            if len(state["pending"]) < self.config.leave_fixes:
                return []
            # The animal has moved: start again from the fixes that left.
            # If they are spread out (the animal is travelling), start
            # from the last of them alone.
            pending = [Fix.from_dict(item) for item in state["pending"]]
            if state["open"]:
                resolved.append(self._resolve(deployment_id, state["cluster"], fix))
            cluster = new_cluster(pending)
            if extent(cluster) > self.config.max_extent_m:
                cluster = new_cluster(pending[-1:])
            state.update(cluster=cluster, pending=[], open=False)

        return resolved + self._check(state, deployment_id, cluster)

    def on_tick(self, state: dict, deployment_id: str, now: datetime) -> list[Alert]:
        """Do nothing: only fixes show whether a tag is moving.

        A tag that stops reporting altogether is the gap detector's case.

        Args:
            state: This detector's state for the deployment (unused).
            deployment_id: Deployment being checked (unused).
            now: Current time (unused).

        Returns:
            list[Alert]: Always empty.
        """
        # pylint: disable=unused-argument
        return []

    def _resolve(self, deployment_id: str, cluster: dict, fix: Fix) -> Alert:
        """A resolve for an alerted cluster the animal has now left.

        Args:
            deployment_id: Deployment named in the alert.
            cluster: The alerted cluster, before it is replaced.
            fix: The fix that confirms the move.

        Returns:
            Alert: The resolve, at the confirming fix.
        """
        lat = cluster["sum_lat"] / cluster["n"]
        lon = cluster["sum_lon"] / cluster["n"]
        distance = haversine_m(lat, lon, fix.lat, fix.lon)
        message = (
            f"Moving again: {distance:.0f} m from the cluster near "
            f"{lat:.5f}, {lon:.5f} at {fix.timestamp:%Y-%m-%d %H:%M} UTC"
        )
        return Alert(
            deployment_id, self.name, fix.timestamp, message, RESOLVED, "moved"
        )

    def _check(self, state: dict, deployment_id: str, cluster: dict) -> list[Alert]:
        """Alert if the cluster qualifies and has not already been alerted.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment named in the alert.
            cluster: The current cluster.

        Returns:
            list[Alert]: One alert or none.
        """
        start = datetime.fromisoformat(cluster["start"])
        last = datetime.fromisoformat(cluster["last"])
        if state["open"] or cluster["n"] < self.config.min_fixes:
            return []
        if last - start < self.config.window:
            return []
        state["open"] = True
        lat = cluster["sum_lat"] / cluster["n"]
        lon = cluster["sum_lon"] / cluster["n"]
        message = (
            f"Possible mortality or dropped tag: no movement beyond "
            f"{self.config.max_extent_m:.0f} m for "
            f"{(last - start) / timedelta(hours=1):.0f} h ({cluster['n']} fixes) "
            f"near {lat:.5f}, {lon:.5f}; still since {start:%Y-%m-%d %H:%M} UTC"
        )
        return [Alert(deployment_id, self.name, last, message)]
