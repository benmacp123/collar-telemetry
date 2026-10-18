"""Geodesic helpers shared by the detectors."""

import math

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean Earth radius


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 points.

    Args:
        lat1: Latitude of the first point in degrees.
        lon1: Longitude of the first point in degrees.
        lat2: Latitude of the second point in degrees.
        lon2: Longitude of the second point in degrees.

    Returns:
        The great-circle distance in metres between the two points.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def offset(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple:
    """The point ``distance_m`` from a start point on a given bearing.

    Uses a flat-Earth approximation, accurate to well under a metre at the
    few hundred metres it is used for (GPS scatter).

    Args:
        lat: Start latitude in degrees.
        lon: Start longitude in degrees.
        bearing_deg: Direction of travel, clockwise from north.
        distance_m: Distance to move, in metres.

    Returns:
        tuple: ``(lat, lon)`` of the new point, in degrees.
    """
    bearing = math.radians(bearing_deg)
    dlat = distance_m * math.cos(bearing) / EARTH_RADIUS_M
    dlon = (
        distance_m * math.sin(bearing) / (EARTH_RADIUS_M * math.cos(math.radians(lat)))
    )
    return lat + math.degrees(dlat), lon + math.degrees(dlon)
