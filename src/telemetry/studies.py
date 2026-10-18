"""The committed Movebank studies and how to load each from ``data/raw``.

Shared by the profiling script and the replay runner, so both read the
same files the same way.
"""

from dataclasses import dataclass
from pathlib import Path

from telemetry.fixes import Deployment, Fix
from telemetry.movebank import LoadReport, read_deployments, read_fixes


@dataclass(frozen=True)
class Study:
    """One committed study.

    Attributes:
        slug: Short name used for result directories.
        title: Human-readable name for reports.
        stem: File name stem shared by the study's Movebank files.
        pattern: Glob for the event files, with ``{stem}`` filled in.
            Event files over GitHub's size limit are committed split into
            numbered parts by ``scripts/split_events.py``.
    """

    slug: str
    title: str
    stem: str
    pattern: str

    def reference_path(self, raw: Path) -> Path:
        """Path of the study's reference-data (deployments) file.

        Args:
            raw: The raw data directory.

        Returns:
            Path: The reference-data CSV.
        """
        return raw / f"{self.stem}-reference-data.csv"

    def event_paths(self, raw: Path) -> list[Path]:
        """Paths of the study's event files, parts in numeric order.

        Args:
            raw: The raw data directory.

        Returns:
            list[Path]: Event CSVs, ``...-2.csv`` before ``...-10.csv``.
        """
        return sorted(raw.glob(self.pattern.format(stem=self.stem)), key=part_number)

    def load(self, raw: Path) -> tuple[list[Deployment], list[Fix], LoadReport]:
        """Read the study's deployments and fixes.

        Args:
            raw: The raw data directory.

        Returns:
            The deployments, the fixes in file order, and a report of the
            rows that were dropped.
        """
        deployments = read_deployments(self.reference_path(raw))
        fixes, report = read_fixes(self.event_paths(raw), deployments)
        return deployments, fixes, report


def part_number(path: Path) -> int:
    """Sort key putting ``...-2.csv`` before ``...-10.csv``.

    Args:
        path: An event file path.

    Returns:
        int: The part number at the end of the file name, or 0 if none.
    """
    suffix = path.stem.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else 0


STUDIES: list[Study] = [
    Study(
        "vultures",
        "Vultures, southeastern United States",
        "Vultures tagged in the southeastern United States_part",
        "{stem}-gps-*.csv",
    ),
    Study(
        "jackals",
        "Black-backed jackal, Etosha",
        "Black-backed jackal, Etosha National Park, Namibia",
        "{stem}.csv",
    ),
    Study(
        "elephants",
        "African elephant, Kruger",
        "ThermochronTracking Elephants Kruger 2007",
        "{stem}.csv",
    ),
]
