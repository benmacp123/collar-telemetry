"""The committed Movebank studies and how to load each from ``data/raw``.

Shared by the profiling script and the replay runner, so both read the
same files the same way.

``STUDIES`` holds the three studies committed as Movebank exports.
``STORKS`` holds the five white stork populations committed as an hourly
extract, each on one side of the split in ``data/splits.csv``. They are a
separate list so that nothing loads a held-out population by iterating
"every study": a caller has to ask for them, and ``tuning_storks`` is the
list an ordinary run should use.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

from telemetry.core.detectors.geofence import EXIT, Fence
from telemetry.core.fixes import Deployment, Fix
from telemetry.data.movebank import (
    LoadReport,
    read_deployments,
    read_extract_acceleration,
    read_extract_deployments,
    read_extract_fixes,
    read_extract_tag_models,
    read_fixes,
    read_tag_models,
)

SPLITS_PATH = Path(__file__).resolve().parents[3] / "data" / "splits.csv"
TUNING = "tuning"
SCORING = "scoring"
STORK_GROUP = "storks"


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
        boundary: Stem of the park boundary in ``boundaries/`` under the
            raw directory (an exit fence), or None for no geofence.
    """

    slug: str
    title: str
    stem: str
    pattern: str
    boundary: str | None = None

    @property
    def group(self) -> str:
        """The name the study's sets and targets are filed under in the
        experiment file.

        Returns:
            str: The slug; populations of one case study share a group.
        """
        return self.slug

    @property
    def split(self) -> str | None:
        """Which side of a whole-study split the study is on.

        Returns:
            str | None: None, since an export study is split by
            deployment date, if at all.
        """
        return None

    def fence(self, raw: Path) -> Fence | None:
        """The study's geofence, if it has one.

        Args:
            raw: The raw data directory.

        Returns:
            Fence | None: The park boundary as an exit fence, or None.
        """
        if self.boundary is None:
            return None
        return Fence.from_file(raw / "boundaries" / f"{self.boundary}.geojson", EXIT)

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

    def tag_models(self, raw: Path) -> dict[str, str]:
        """Each deployment's tag model.

        Args:
            raw: The raw data directory.

        Returns:
            dict[str, str]: Tag model by deployment ID.
        """
        return read_tag_models(self.reference_path(raw))


@cache
def read_splits(path: Path = SPLITS_PATH) -> dict[int, str]:
    """The committed whole-study split.

    Args:
        path: The split file.

    Returns:
        dict[int, str]: ``tuning``, ``scoring`` or ``excluded`` by
        Movebank study ID.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        return {
            int(row["movebank-study-id"]): row["split"].strip()
            for row in csv.DictReader(handle)
        }


@dataclass(frozen=True)
class ExtractStudy(Study):
    """One population committed as an hourly extract under ``storks/``.

    ``stem`` is the population's file-name stem. The side of the split is
    read from ``data/splits.csv`` rather than written here, so the file
    committed before any track was downloaded stays the only statement of
    it.

    Attributes:
        study_id: The population's Movebank study ID, its key in the
            split file.
    """

    study_id: int = 0

    @property
    def group(self) -> str:
        """The case study the population belongs to.

        Returns:
            str: ``storks`` for every population.
        """
        return STORK_GROUP

    @property
    def split(self) -> str:
        """Which side of the split the whole population is on.

        Returns:
            str: ``tuning`` or ``scoring``.

        Raises:
            KeyError: If the split file does not name the study.
        """
        return read_splits()[self.study_id]

    def reference_path(self, raw: Path) -> Path:
        """Path of the population's deployment table.

        Args:
            raw: The raw data directory.

        Returns:
            Path: The deployments CSV.
        """
        return raw / STORK_GROUP / f"{self.stem}-deployments.csv"

    def load(self, raw: Path) -> tuple[list[Deployment], list[Fix], LoadReport]:
        """Read the population's deployments and hourly fixes.

        Args:
            raw: The raw data directory.

        Returns:
            The deployments, the fixes in file order, and a report of the
            rows that were dropped.
        """
        deployments = read_extract_deployments(
            self.reference_path(raw),
            raw / STORK_GROUP / f"{self.stem}-individuals.csv",
        )
        fixes, report = read_extract_fixes(self.event_paths(raw), deployments)
        return deployments, fixes, report

    def load_acceleration(
        self, raw: Path, deployments: list[Deployment]
    ) -> dict[str, dict[datetime, float]]:
        """Read the population's hourly acceleration summaries.

        Kept apart from ``load`` so replays, which do not use them, never
        open the files.

        Args:
            raw: The raw data directory.
            deployments: The population's deployments, from ``load``.

        Returns:
            dict[str, dict[datetime, float]]: Median burst spread by hour
            start, for each deployment ID.
        """
        paths = sorted(
            raw.glob(f"{STORK_GROUP}/{self.stem}-acc-*.csv.gz"), key=part_number
        )
        return read_extract_acceleration(paths, deployments)

    def tag_models(self, raw: Path) -> dict[str, str]:
        """Each deployment's tag model, from the tag table.

        Args:
            raw: The raw data directory.

        Returns:
            dict[str, str]: Tag model by deployment ID.
        """
        return read_extract_tag_models(
            self.reference_path(raw), raw / STORK_GROUP / f"{self.stem}-tags.csv"
        )


def part_number(path: Path) -> int:
    """Sort key putting ``...-2.csv`` before ``...-10.csv``.

    Args:
        path: An event file path.

    Returns:
        int: The part number at the end of the file name, or 0 if none.
    """
    # Cut at the first dot, so ``-1.csv.gz`` reads the same as ``-1.csv``.
    suffix = path.name.split(".", 1)[0].rsplit("-", 1)[-1]
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
        boundary="etosha",
    ),
    Study(
        "elephants",
        "African elephant, Kruger",
        "ThermochronTracking Elephants Kruger 2007",
        "{stem}.csv",
        boundary="kruger",
    ),
]


def _stork(stem: str, place: str, study_id: int) -> ExtractStudy:
    """One LifeTrack white stork population.

    Args:
        stem: File-name stem under ``storks/``.
        place: The population's name, for titles.
        study_id: Its Movebank study ID.

    Returns:
        ExtractStudy: The population, with slug ``storks-<stem>``.
    """
    return ExtractStudy(
        slug=f"{STORK_GROUP}-{stem}",
        title=f"White stork, {place}",
        stem=stem,
        pattern=STORK_GROUP + "/{stem}-gps-*.csv.gz",
        study_id=study_id,
    )


STORKS: list[ExtractStudy] = [
    _stork("sw-germany", "SW Germany", 21231406),
    _stork("bavaria", "Bavaria", 24442409),
    _stork("rheinland-pfalz", "Rheinland-Pfalz", 76367850),
    _stork("vorarlberg", "Vorarlberg", 173641633),
    _stork("oberschwaben", "Oberschwaben", 212096177),
]


def tuning_storks() -> list[ExtractStudy]:
    """The stork populations thresholds may be chosen on.

    Returns:
        list[ExtractStudy]: Populations the split file marks ``tuning``.
    """
    return [study for study in STORKS if study.split == TUNING]
