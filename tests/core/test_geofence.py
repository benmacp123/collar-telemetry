"""Tests for the geofence detector on a square park 10 km across."""

import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.detectors.geofence import (
    ENTRY,
    EXIT,
    Fence,
    GeofenceConfig,
    GeofenceDetector,
)
from telemetry.analysis.evaluation import (
    ALIVE,
    ALL,
    Truth,
    geofence_summary,
    nearest_edge,
)
from telemetry.core.fixes import Fix
from telemetry.core.geo import offset
from telemetry.core.stream import FixStream
from telemetry.data.studies import STUDIES

START = datetime(2008, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
CENTRE = (-24.5, 31.5)


def square(half_m=5_000.0):
    """A GeoJSON square centred on CENTRE, ``half_m`` from centre to edge."""
    north = offset(*CENTRE, 0.0, half_m)[0]
    south = offset(*CENTRE, 180.0, half_m)[0]
    east = offset(*CENTRE, 90.0, half_m)[1]
    west = offset(*CENTRE, 270.0, half_m)[1]
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


def east_of_centre(metres, hour):
    """A fix ``metres`` east of CENTRE (the east edge is at 5,000 m)."""
    return Fix("A", START + hour * HOUR, *offset(*CENTRE, 90.0, metres))


def run(detector, distances):
    """Feed fixes at the given distances east of centre, one an hour."""
    state, alerts = {}, []
    for hour, metres in enumerate(distances):
        alerts += detector.on_fix(state, "A", east_of_centre(metres, hour))
    return alerts


def park(mode=EXIT, **config):
    """A detector on the square park."""
    settings = GeofenceConfig(**config)
    return GeofenceDetector(
        Fence(square(), "Test Park", mode, settings.buffer_m), settings
    )


@pytest.mark.parametrize(
    "metres, expected",
    [
        (0, "inside"),
        (4_850, "inside"),
        (4_950, "edge"),
        (5_050, "edge"),
        (5_150, "outside"),
    ],
)
def test_side_uses_the_edge_band(metres, expected):
    """Fixes within 100 m of the boundary are in the band, either side."""
    fence = Fence(square(), "Test Park", EXIT, 100.0)
    fix = east_of_centre(metres, 0)
    assert fence.side(fix.lat, fix.lon) == expected


def test_leaving_opens_after_confirming_fixes_and_return_resolves():
    """Two fixes outside open one incident; two inside resolve it."""
    alerts = run(park(), [0, 2_000, 6_000, 7_000, 8_000, 3_000, 1_000])
    assert [(a.status, a.time.hour) for a in alerts] == [("open", 3), ("resolved", 6)]
    assert alerts[0].message.startswith("Left Test Park")
    assert alerts[1].reason == "returned"


def test_one_stray_fix_outside_does_not_alert():
    """A single fix outside, then back inside, is not a crossing."""
    assert run(park(), [0, 6_000, 1_000, 6_000, 1_000]) == []


def test_jitter_along_the_boundary_does_not_alert():
    """Fixes scattered within the band around the edge never alert."""
    jitter = [4_920, 5_080, 4_960, 5_040, 5_090, 4_910] * 5
    assert run(park(), jitter) == []


def test_edge_fixes_do_not_break_a_crossing():
    """Outside, edge, outside still confirms the exit."""
    alerts = run(park(), [0, 6_000, 5_020, 6_500])
    assert [a.status for a in alerts] == ["open"]


def test_entry_fence_alerts_on_entering():
    """A keep-out zone alerts when the animal goes in and out again."""
    alerts = run(park(ENTRY), [9_000, 8_000, 1_000, 0, 9_000, 9_500])
    assert [(a.status, a.message.split(":")[0]) for a in alerts] == [
        ("open", "Entered Test Park"),
        ("resolved", "Back out of Test Park"),
    ]


def test_wider_band_ignores_a_shallow_excursion():
    """A 300 m band ignores an animal 200 m outside that 100 m would flag."""
    shallow = [0, 5_200, 5_200, 0, 0]
    assert len(run(park(buffer_m=100.0), shallow)) == 2
    assert run(park(buffer_m=300.0), shallow) == []


def test_projection_keeps_distances_within_a_few_metres():
    """The local plane puts a point 5,150 m east just outside a 5 km box
    with a 100 m band, and 5,080 m within it."""
    fence = Fence(square(), "Test Park", EXIT, 100.0)
    assert fence.side(*offset(*CENTRE, 90.0, 5_110.0)) == "outside"
    assert fence.side(*offset(*CENTRE, 90.0, 5_090.0)) == "edge"


def test_from_file_reads_name_and_rejects_non_polygons(tmp_path):
    """Fences load from GeoJSON features; a line is not a fence."""
    path = tmp_path / "park.geojson"
    feature = {
        "type": "Feature",
        "properties": {"name": "File Park"},
        "geometry": square(),
    }
    path.write_text(json.dumps(feature), encoding="utf-8")
    assert Fence.from_file(path).name == "File Park"
    line = {"type": "LineString", "coordinates": [[31.0, -24.0], [31.1, -24.1]]}
    with pytest.raises(ValueError, match="not a polygon"):
        Fence(line, "Line", EXIT, 100.0)
    with pytest.raises(ValueError, match="mode"):
        Fence(square(), "Park", "sideways", 100.0)


def test_nearest_edge_by_east_west_crossing():
    """Points beyond a park are placed on the edge they crossed."""
    polygon = Fence(square(), "Test Park", EXIT, 100.0).polygon
    assert nearest_edge(polygon, *offset(*CENTRE, 270.0, 7_000)) == "west"
    assert nearest_edge(polygon, *offset(*CENTRE, 90.0, 7_000)) == "east"
    assert nearest_edge(polygon, *offset(*CENTRE, 0.0, 7_000)) == "north"


def test_geofence_summary_counts_durations_and_edges():
    """One short and one long excursion, both west, from one animal."""
    detector = park()
    fence = detector.fence
    distances = [0, -6_000, -6_500, 0, 0, 0, -6_000, -6_500] + [-7_000] * 10 + [0, 0]
    fixes = [
        Fix("A", START + h * HOUR, *offset(*CENTRE, 90.0, m))
        for h, m in enumerate(distances)
    ]
    stream = FixStream([detector])
    incidents = {}
    for fix in fixes:
        for incident in stream.ingest(fix, now=fix.timestamp):
            incidents[incident.incident_id] = incident
    truth = Truth(
        "A",
        "Loxodonta africana",
        ALIVE,
        ALL,
        START,
        fixes[-1].timestamp,
        START,
        START,
        HOUR,
    )
    summary = geofence_summary([truth], list(incidents.values()), fixes, fence)
    assert summary["incidents"] == 2
    assert summary["deployments"] == 1
    assert summary["exits_by_edge"] == {"west": 2}
    assert summary["short_share"] == 0.5
    # Out from h2 to h4 and from h7 to h19: 2 h and 12 h.
    assert summary["median_hours_outside"] == 7.0


def test_committed_boundaries_load_for_the_mammal_studies():
    """Jackals and elephants have their park fences; vultures have none."""
    raw = Path(__file__).resolve().parents[2] / "data" / "raw"
    fences = {s.slug: s.fence(raw) for s in STUDIES}
    assert fences["vultures"] is None
    assert fences["jackals"].name == "Etosha National Park"
    assert fences["elephants"].name == "Kruger National Park"
    # Okaukuejo camp is inside Etosha; Skukuza camp is inside Kruger.
    assert fences["jackals"].side(-19.18, 15.92) == "inside"
    assert fences["elephants"].side(-24.99, 31.59) == "inside"
