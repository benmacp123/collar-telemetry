"""Geodesic helpers shared by the detectors."""

import math

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean Earth radius


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))
