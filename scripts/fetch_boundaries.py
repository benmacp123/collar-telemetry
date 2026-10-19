"""Fetch park boundaries from OpenStreetMap and save them as GeoJSON.

Optional: the committed files in ``data/raw/boundaries/`` are what the
analysis reads, so nothing else needs network access. Run this only to
refresh them, with ``PYTHONPATH=src python scripts/fetch_boundaries.py``.

Each boundary is an OSM relation fetched from the public Overpass API. Its
outer and inner member ways are joined into polygons (inner rings become
holes) and written as one GeoJSON feature with its source, retrieval date
and licence. OSM data is © OpenStreetMap contributors under the Open
Database Licence (ODbL 1.0), so these extracts stay under ODbL, apart from
the rest of the repository.
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from shapely.geometry import LineString, mapping
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "boundaries"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "collar-telemetry portfolio project (boundary fetch)"
ATTEMPTS = 4
BACKOFF_S = 30

# Relation IDs found by name and checked against their Wikidata IDs
# (Etosha Q675633, Kruger Q24451).
BOUNDARIES = {
    "etosha": 2982497,
    "kruger": 1752987,
}


def fetch_relation(relation_id: int) -> dict:
    """Download one relation with its member geometry.

    Args:
        relation_id: OSM relation ID.

    Returns:
        dict: The relation element from Overpass's JSON response.

    Raises:
        ValueError: If the response holds no such relation.
        urllib.error.HTTPError: If Overpass still fails after ``ATTEMPTS``
            tries.
    """
    query = f"[out:json][timeout:120];relation({relation_id});out geom;"
    request = urllib.request.Request(
        OVERPASS,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    # The public Overpass servers shed load with 429/502/504; wait and
    # retry a few times rather than failing or hammering them.
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == ATTEMPTS:
                raise
            print(
                f"Overpass returned {error.code}; retrying in {BACKOFF_S * attempt} s"
            )
            time.sleep(BACKOFF_S * attempt)
    for element in payload.get("elements", []):
        if element.get("type") == "relation" and element.get("id") == relation_id:
            return element
    raise ValueError(f"relation {relation_id} not found in Overpass response")


def relation_polygon(relation: dict):
    """Join a relation's member ways into a (multi)polygon.

    Args:
        relation: A relation element fetched with ``out geom``.

    Returns:
        shapely geometry: Outer rings as polygons, minus inner rings.

    Raises:
        ValueError: If the outer ways do not close into any polygon.
    """
    rings: dict[str, list[LineString]] = {"outer": [], "inner": []}
    for member in relation.get("members", []):
        role = member.get("role") or "outer"
        if member.get("type") != "way" or role not in rings:
            continue
        points = [(p["lon"], p["lat"]) for p in member.get("geometry", [])]
        if len(points) >= 2:
            rings[role].append(LineString(points))
    outer = unary_union(list(polygonize(rings["outer"])))
    if outer.is_empty:
        raise ValueError(f"relation {relation['id']} has no closed outer ring")
    inner = list(polygonize(rings["inner"]))
    return outer.difference(unary_union(inner)) if inner else outer


def round_coordinates(value, digits: int = 6):
    """Round every coordinate in a GeoJSON coordinate tree.

    Six decimal places is about 0.1 m, far below GPS error, and keeps the
    files small and diffs stable.

    Args:
        value: A coordinate, or nested lists of them.
        digits: Decimal places.

    Returns:
        The same structure with rounded numbers, as lists.
    """
    if isinstance(value, (int, float)):
        return round(value, digits)
    return [round_coordinates(v, digits) for v in value]


def feature(slug: str, relation: dict, retrieved: date) -> dict:
    """A GeoJSON feature for one boundary.

    Args:
        slug: Short name used for the file.
        relation: The fetched relation.
        retrieved: Retrieval date, recorded in the properties.

    Returns:
        dict: A GeoJSON Feature with source and licence properties.
    """
    geometry = mapping(relation_polygon(relation))
    tags = relation.get("tags", {})
    return {
        "type": "Feature",
        "properties": {
            "slug": slug,
            "name": tags.get("name"),
            "osm_relation": relation["id"],
            "wikidata": tags.get("wikidata"),
            "retrieved": retrieved.isoformat(),
            "licence": "ODbL-1.0",
            "attribution": "© OpenStreetMap contributors",
        },
        "geometry": {
            "type": geometry["type"],
            "coordinates": round_coordinates(geometry["coordinates"]),
        },
    }


def main():
    """Fetch every boundary and write it to ``data/raw/boundaries``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only", choices=sorted(BOUNDARIES), action="append", help="boundary"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for slug in args.only or sorted(BOUNDARIES):
        result = feature(slug, fetch_relation(BOUNDARIES[slug]), today)
        path = OUT / f"{slug}.geojson"
        path.write_text(json.dumps(result) + "\n", encoding="utf-8")
        print(f"{slug}: wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
