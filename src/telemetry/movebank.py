"""Readers for Movebank event and reference-data CSV exports.

Uses only the standard library so the core stays small enough to package
for Lambda.
"""

import csv
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from telemetry.fixes import Deployment, Fix


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
        by_key: A dictionary mapping (tag, animal) keys to their corresponding deployments.
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
