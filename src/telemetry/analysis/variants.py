"""Labelled synthetic variants of the mammal studies.

The jackal and elephant tracks hold no carcass periods, so the mortality
detector has nothing to be scored on there. Each variant is built from a
real study by ``telemetry.sim.synthetic.synthetic_study``: every
deployment dies twice, once per carcass regime. The variants are replayed
and scored like the real studies, but only their deaths are reported;
operator load stays with the real studies, since the variants repeat the
same pre-death tracks.

The variants are kept out of ``telemetry.data.studies.STUDIES``, so the
sweep and the cloud runs, which loop over that list, are unchanged.
"""

from dataclasses import dataclass
from pathlib import Path

from telemetry.core.detectors.geofence import Fence
from telemetry.data.studies import STUDIES, Study
from telemetry.sim.replay import DEFAULT_SEED
from telemetry.sim.synthetic import SyntheticStudy, synthetic_study


@dataclass(frozen=True)
class Variant:
    """A synthetic variant of one study.

    Attributes:
        slug: Short name used for result directories.
        title: Human-readable name for reports.
        base: The real study its tracks come from.
    """

    slug: str
    title: str
    base: Study

    def build(self, raw: Path, seed: int = DEFAULT_SEED) -> SyntheticStudy:
        """Load the base study and inject its deaths.

        Args:
            raw: The raw data directory.
            seed: Seed for death times and carcass fixes.

        Returns:
            SyntheticStudy: The variant's deployments, fixes and deaths.
        """
        deployments, fixes, _ = self.base.load(raw)
        return synthetic_study(deployments, fixes, seed)

    def fence(self, raw: Path) -> Fence | None:
        """The base study's geofence, so the pipeline runs as it does there.

        Args:
            raw: The raw data directory.

        Returns:
            Fence | None: The base study's fence, or None.
        """
        return self.base.fence(raw)


def _study(slug: str) -> Study:
    """A committed study by slug.

    Args:
        slug: The study's slug.

    Returns:
        Study: The study.
    """
    return next(study for study in STUDIES if study.slug == slug)


VARIANTS: list[Variant] = [
    Variant(
        "jackals-synthetic",
        "Black-backed jackal, Etosha, synthetic deaths",
        _study("jackals"),
    ),
    Variant(
        "elephants-synthetic",
        "African elephant, Kruger, synthetic deaths",
        _study("elephants"),
    ),
]
