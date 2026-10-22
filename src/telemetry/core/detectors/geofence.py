"""Geofence detector: an animal crossing a boundary polygon.

A fence is any GeoJSON polygon with a mode:

- ``exit``: the animal should stay inside (a park); leaving alerts.
- ``entry``: the animal should stay out (a village, farmland); entering
  alerts.

**GPS jitter.** A fix within ``buffer_m`` of the boundary is in the edge
band and changes nothing, so an animal walking along a fence line does not
raise an alert with every fix. A fix counts as on the alerting side only
beyond the band, and ``confirm_fixes`` such fixes in a row open an
incident; the same number on the safe side, beyond the band, resolve it
(reason ``returned``).

**Geometry.** The polygon is projected once to a local equirectangular
plane in metres centred on the fence, which is accurate to a few per cent
over a park-sized area, and the two band edges are prepared shapely
geometries, so each fix costs two point-in-polygon tests.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, shape
from shapely.prepared import prep

from telemetry.core.alerts import RESOLVED, Alert
from telemetry.core.fixes import Fix

M_PER_DEGREE = 111_320.0
EXIT = "exit"
ENTRY = "entry"


@dataclass(frozen=True)
class GeofenceConfig:
    """Geofence detector settings. Provisional, not chosen on data.

    Attributes:
        buffer_m: Half-width of the edge band, in metres; fixes this close
            to the boundary change nothing. Several times the typical GPS
            error of 6-30 m.
        confirm_fixes: Fixes in a row beyond the band needed to open or
            resolve an incident.
    """

    buffer_m: float = 100.0
    confirm_fixes: int = 2


class Fence:
    """A boundary polygon prepared for fast side tests.

    Attributes:
        name: Name used in alert messages.
        mode: ``EXIT`` or ``ENTRY``.
        polygon: The boundary in lon/lat (WGS84), for reports and maps.
    """

    def __init__(self, geometry: dict, name: str, mode: str, buffer_m: float):
        """Project and prepare a boundary.

        Args:
            geometry: A GeoJSON Polygon or MultiPolygon, lon/lat (WGS84).
            name: Name used in alert messages.
            mode: ``EXIT`` or ``ENTRY``.
            buffer_m: Half-width of the edge band, in metres.

        Raises:
            ValueError: If the mode is unknown or the geometry is not a
                polygon.
        """
        if mode not in (EXIT, ENTRY):
            raise ValueError(f"unknown fence mode {mode!r}")
        polygon = shape(geometry)
        if polygon.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError(f"fence {name!r} is a {polygon.geom_type}, not a polygon")
        self.name = name
        self.mode = mode
        self.polygon = polygon
        centre = polygon.centroid
        self._lon0, self._lat0 = centre.x, centre.y
        self._x_scale = M_PER_DEGREE * math.cos(math.radians(self._lat0))
        local = self._to_local(polygon)
        self._outer = prep(local.buffer(buffer_m))
        self._inner = prep(local.buffer(-buffer_m))

    @classmethod
    def from_file(cls, path: Path, mode: str = EXIT, buffer_m: float = 100.0):
        """Load a fence from a GeoJSON Feature file.

        Args:
            path: The file; its ``properties.name`` names the fence.
            mode: ``EXIT`` or ``ENTRY``.
            buffer_m: Half-width of the edge band, in metres.

        Returns:
            Fence: The prepared fence.
        """
        feature = json.loads(path.read_text(encoding="utf-8"))
        name = feature.get("properties", {}).get("name") or path.stem
        return cls(feature["geometry"], name, mode, buffer_m)

    def _to_local(self, geometry):
        """Project a lon/lat geometry to the fence's local metric plane.

        Args:
            geometry: A shapely geometry in lon/lat degrees.

        Returns:
            A shapely geometry in metres east and north of the centroid.
        """
        shifted = affinity.translate(geometry, -self._lon0, -self._lat0)
        return affinity.scale(shifted, self._x_scale, M_PER_DEGREE, origin=(0.0, 0.0))

    def side(self, lat: float, lon: float) -> str:
        """Which side of the fence a point is on, allowing for the band.

        Args:
            lat: Latitude in degrees.
            lon: Longitude in degrees.

        Returns:
            str: ``"inside"`` or ``"outside"`` beyond the band, or
            ``"edge"`` within ``buffer_m`` of the boundary.
        """
        point = Point(
            (lon - self._lon0) * self._x_scale, (lat - self._lat0) * M_PER_DEGREE
        )
        if self._inner.contains(point):
            return "inside"
        if not self._outer.contains(point):
            return "outside"
        return "edge"


class GeofenceDetector:
    """Alerts when an animal crosses to the wrong side of a fence."""

    name = "geofence"

    def __init__(self, fence: Fence, config: GeofenceConfig | None = None):
        """Create a geofence detector for one fence.

        Args:
            fence: The prepared fence; its buffer should match
                ``config.buffer_m``.
            config: Detector settings; the provisional defaults if omitted.
        """
        self.fence = fence
        self.config = config or GeofenceConfig()
        self._alerting_side = "outside" if fence.mode == EXIT else "inside"
        self._safe_side = "inside" if fence.mode == EXIT else "outside"

    def on_fix(self, state: dict, deployment_id: str, fix: Fix) -> list[Alert]:
        """Classify a fix and open or resolve an incident when confirmed.

        Args:
            state: This detector's state for the deployment, updated in
                place.
            deployment_id: Deployment the fix belongs to.
            fix: The next clean fix, in time order.

        Returns:
            list[Alert]: An open on a confirmed crossing to the alerting
            side, a resolve on a confirmed return, otherwise empty.
        """
        if "open" not in state:
            state.update(open=False, streak=0)
        side = self.fence.side(fix.lat, fix.lon)
        wanted = self._safe_side if state["open"] else self._alerting_side
        # Edge-band fixes neither confirm nor break a crossing; a fix on the
        # other side beyond the band starts the count again.
        if side == wanted:
            state["streak"] += 1
        elif side != "edge":
            state["streak"] = 0
        if state["streak"] < self.config.confirm_fixes:
            return []
        state["streak"] = 0
        state["open"] = not state["open"]
        where = f"{fix.lat:.5f}, {fix.lon:.5f} at {fix.timestamp:%Y-%m-%d %H:%M} UTC"
        if state["open"]:
            verb = "Left" if self.fence.mode == EXIT else "Entered"
            return [
                Alert(
                    deployment_id,
                    self.name,
                    fix.timestamp,
                    f"{verb} {self.fence.name}: {where}",
                )
            ]
        verb = "Back inside" if self.fence.mode == EXIT else "Back out of"
        return [
            Alert(
                deployment_id,
                self.name,
                fix.timestamp,
                f"{verb} {self.fence.name}: {where}",
                RESOLVED,
                "returned",
            )
        ]

    def on_tick(self, state: dict, deployment_id: str, now) -> list[Alert]:
        """Geofence alerts come only from fixes.

        Args:
            state: This detector's state for the deployment.
            deployment_id: Deployment being checked.
            now: Current time.

        Returns:
            list[Alert]: Always empty.
        """
        del state, deployment_id, now
        return []
