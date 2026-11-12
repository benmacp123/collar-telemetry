"""Readers for Movebank event and reference-data CSV exports, and for the
hourly extract ``telemetry.data.extract`` reduces API downloads to.

The two formats differ in column names and in how a fix finds its
deployment: an export row names a tag and an animal, matched to a
deployment by time; an extract row carries Movebank's own deployment ID.

Uses only the standard library so the core stays small enough to package
for Lambda.
"""

import csv
import gzip
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from telemetry.core.fixes import Deployment, Fix


def parse_timestamp(value: str) -> datetime:
    """Parse a Movebank timestamp (``yyyy-MM-dd HH:mm:ss.SSS``, UTC).

    Args:
        value: Timestamp text as it appears in a Movebank export.

    Returns:
        A timezone-aware datetime in UTC.
    """
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _optional(value: str | None) -> str | None:
    """Return a stripped string or None if empty.

    Args:
        value: A string or None.

    Returns:
        The stripped string, or None if the input was None or empty after stripping.
    """
    value = (value or "").strip()
    return value or None


def read_deployments(path: Path) -> list[Deployment]:
    """Read a Movebank reference-data CSV.

    Args:
        path: Path to the ``*-reference-data.csv`` file.

    Returns:
        One Deployment per row, in file order.

    Raises:
        ValueError: If a row has no deploy-on date or a deployment ID repeats.
    """
    deployments = []
    seen = set()
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            deployment_id = row["deployment-id"].strip()
            if deployment_id in seen:
                raise ValueError(f"duplicate deployment-id {deployment_id!r}")
            seen.add(deployment_id)
            deploy_on = _optional(row["deploy-on-date"])
            if deploy_on is None:
                raise ValueError(f"deployment {deployment_id!r} has no deploy-on-date")
            deploy_off = _optional(row["deploy-off-date"])
            deployments.append(
                Deployment(
                    deployment_id=deployment_id,
                    tag_id=row["tag-id"].strip(),
                    animal_id=row["animal-id"].strip(),
                    taxon=row["animal-taxon"].strip(),
                    deploy_on=parse_timestamp(deploy_on),
                    deploy_off=parse_timestamp(deploy_off) if deploy_off else None,
                    end_type=_optional(row["deployment-end-type"]),
                )
            )
    return deployments


def read_tag_models(path: Path) -> dict[str, str]:
    """Read each deployment's tag model from a Movebank reference-data CSV.

    Kept out of ``Deployment`` because only analysis uses it. Studies with
    one tag type often leave ``tag-model`` out; the manufacturer then
    stands in, and "unknown" if that is missing too.

    Args:
        path: Path to the ``*-reference-data.csv`` file.

    Returns:
        dict[str, str]: Tag model by deployment ID.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            row["deployment-id"].strip(): _optional(row.get("tag-model"))
            or _optional(row.get("tag-manufacturer-name"))
            or "unknown"
            for row in csv.DictReader(handle)
        }


@dataclass
class LoadReport:
    """Counts of event rows that did not become fixes.

    Attributes:
        rows: Event rows read.
        not_visible: Rows Movebank flags as outliers (``visible`` false).
        no_location: Rows with an empty latitude or longitude.
        unmatched: Rows whose tag, animal and time match no deployment.
    """

    rows: int = 0
    not_visible: int = 0
    no_location: int = 0
    unmatched: int = 0


def read_fixes(
    paths: Path | Iterable[Path], deployments: list[Deployment]
) -> tuple[list[Fix], LoadReport]:
    """Read Movebank event CSVs and attach each fix to its deployment.

    A row belongs to the deployment with the same tag and animal whose
    deploy-on/off window contains its timestamp, following Movebank's own
    rule. Fixes keep their file order, files in the order given; sorting
    is the cleaning step's job.

    Args:
        paths: The event CSV, or the parts of one split to fit GitHub's
            file size limit.
        deployments: Deployments from the matching reference-data file.

    Returns:
        The fixes, and a report of the rows that were dropped.
    """
    by_key = defaultdict(list)
    for deployment in deployments:
        by_key[(deployment.tag_id, deployment.animal_id)].append(deployment)

    fixes = []
    report = LoadReport()
    for path in [paths] if isinstance(paths, Path) else paths:
        _read_event_file(path, by_key, fixes, report)
    return fixes, report


def _read_event_file(path, by_key: defaultdict[list], fixes: list, report: LoadReport):
    """Append one event file's fixes to ``fixes``, counting drops in ``report``.

    Args:
        path: The path to the event CSV file.
        by_key: Deployments keyed by (tag, animal), for matching rows.
        fixes: A list to which the parsed fixes will be appended.
        report: A LoadReport instance to which drop counts will be added.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            report.rows += 1
            if row.get("visible", "true").strip().lower() == "false":
                report.not_visible += 1
                continue
            lat = _optional(row["location-lat"])
            lon = _optional(row["location-long"])
            if lat is None or lon is None:
                report.no_location += 1
                continue
            timestamp = parse_timestamp(row["timestamp"])
            key = (
                row["tag-local-identifier"].strip(),
                row["individual-local-identifier"].strip(),
            )
            match = next((d for d in by_key.get(key, []) if d.covers(timestamp)), None)
            if match is None:
                report.unmatched += 1
                continue
            fixes.append(Fix(match.deployment_id, timestamp, float(lat), float(lon)))


def read_extract_deployments(
    deployments_path: Path, individuals_path: Path
) -> list[Deployment]:
    """Read an extract's deployment table.

    The deployment table has no taxon, so it is taken from the animal's
    row of the individual table. IDs are Movebank's numeric ones, which
    the extract's event rows carry too.

    Args:
        deployments_path: Path to the ``*-deployments.csv`` file.
        individuals_path: Path to the matching ``*-individuals.csv`` file.

    Returns:
        One Deployment per row, in file order.

    Raises:
        ValueError: If a row has no deploy-on time, a deployment ID
            repeats, or a deployment's animal is not in the individual
            table.
    """
    with open(individuals_path, newline="", encoding="utf-8") as handle:
        taxa = {
            row["id"].strip(): row["taxon_canonical_name"].strip()
            for row in csv.DictReader(handle)
        }
    deployments = []
    seen = set()
    with open(deployments_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            deployment_id = row["id"].strip()
            if deployment_id in seen:
                raise ValueError(f"duplicate deployment id {deployment_id!r}")
            seen.add(deployment_id)
            deploy_on = _optional(row["deploy_on_timestamp"])
            if deploy_on is None:
                raise ValueError(f"deployment {deployment_id!r} has no deploy-on time")
            animal_id = row["individual_id"].strip()
            if animal_id not in taxa:
                raise ValueError(
                    f"deployment {deployment_id!r} names unknown animal {animal_id!r}"
                )
            deploy_off = _optional(row["deploy_off_timestamp"])
            deployments.append(
                Deployment(
                    deployment_id=deployment_id,
                    tag_id=row["tag_id"].strip(),
                    animal_id=animal_id,
                    taxon=taxa[animal_id],
                    deploy_on=parse_timestamp(deploy_on),
                    deploy_off=parse_timestamp(deploy_off) if deploy_off else None,
                    end_type=_optional(row["deployment_end_type"]),
                )
            )
    return deployments


def read_extract_tag_models(deployments_path: Path, tags_path: Path) -> dict[str, str]:
    """Read each deployment's tag model from an extract's reference tables.

    Mirrors ``read_tag_models``: the model, else the manufacturer, else
    "unknown".

    Args:
        deployments_path: Path to the ``*-deployments.csv`` file.
        tags_path: Path to the matching ``*-tags.csv`` file.

    Returns:
        dict[str, str]: Tag model by deployment ID.
    """
    with open(tags_path, newline="", encoding="utf-8") as handle:
        models = {
            row["id"].strip(): _optional(row.get("model"))
            or _optional(row.get("manufacturer_name"))
            or "unknown"
            for row in csv.DictReader(handle)
        }
    with open(deployments_path, newline="", encoding="utf-8") as handle:
        return {
            row["id"].strip(): models.get(row["tag_id"].strip(), "unknown")
            for row in csv.DictReader(handle)
        }


def read_extract_fixes(
    paths: Iterable[Path], deployments: list[Deployment]
) -> tuple[list[Fix], LoadReport]:
    """Read an extract's hourly GPS parts.

    The extract already left out Movebank's outliers and rows without a
    position, so only ``unmatched`` can count here: a row whose
    deployment ID is missing from the table, or whose time falls outside
    that deployment.

    Args:
        paths: The ``*-gps-N.csv.gz`` parts, in order.
        deployments: Deployments from the matching reference tables.

    Returns:
        The fixes in file order, and a report of the rows that were
        dropped.
    """
    by_id = {deployment.deployment_id: deployment for deployment in deployments}
    fixes = []
    report = LoadReport()
    for path in paths:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                report.rows += 1
                timestamp = parse_timestamp(row["timestamp"])
                match = by_id.get(row["deployment_id"].strip())
                if match is None or not match.covers(timestamp):
                    report.unmatched += 1
                    continue
                fixes.append(
                    Fix(
                        match.deployment_id,
                        timestamp,
                        float(row["location_lat"]),
                        float(row["location_long"]),
                    )
                )
    return fixes, report
