"""Per-species settings for the cleaner and detectors, with their sources.

Each value is labelled **observed** (measured on this project's tuning
data: vulture deployments starting before 2013), **literature** (from a
cited source) or **provisional** (a reasoned starting point, to be checked
on the tuning set). The full table with references is in
``docs/ASSUMPTIONS.md``.

Speed limits are for the cleaner, whose job is to drop only impossible
fixes, so each limit is a top speed rather than a typical one. Implied
speeds between fixes average over minutes or hours, so a sprint ceiling
leaves a wide margin for real movement.

References:
    Christiansen P (2002) Zool. J. Linn. Soc. 136:685-714.
    Garland T (1983) J. Zool. 199:157-170.
    Gravett N et al. (2017) PLoS ONE 12:e0171903.
        https://doi.org/10.1371/journal.pone.0171903
    Hirt MR, Jetz W, Rall BC, Brose U (2017) Nat. Ecol. Evol. 1:1116-1122,
        Supplementary Table 4 and maximum speed database.
        https://doi.org/10.1038/s41559-017-0241-4
    Hutchinson JR et al. (2003) Nature 422:493-494.
        https://doi.org/10.1038/422493a
    Iriarte-Diaz J (2002) J. Exp. Biol. 205:2897-2908.
    Kaunda SKK (2001) Afr. Zool. 36:143-152.
    Thaker M et al. (2019) Front. Ecol. Evol. 7:4.
        https://doi.org/10.3389/fevo.2019.00004

How far each source was checked (full text, abstract or a secondary
listing) is recorded in ``docs/ASSUMPTIONS.md``.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from telemetry.core.cleaning import CleaningConfig
from telemetry.core.detectors.mortality import MortalityConfig
from telemetry.core.detectors.movement import MovementConfig


@dataclass(frozen=True)
class SpeciesProfile:
    """Settings for one taxon, with the cleaner's arrival-dependent part
    left to the caller.

    Attributes:
        taxon: Scientific name as in Movebank's
            ``individual-taxon-canonical-name``.
        max_speed_mps: Top plausible speed, in m/s, for the speed filter.
        mortality: Mortality detector settings.
        movement: Unusual-movement detector settings.
        gps_error_m: Position error allowed per fix by the speed filter.
    """

    taxon: str
    max_speed_mps: float
    mortality: MortalityConfig = field(default_factory=MortalityConfig)
    movement: MovementConfig = field(default_factory=MovementConfig)
    gps_error_m: float = 30.0

    def cleaning(self, max_lateness: timedelta) -> CleaningConfig:
        """Cleaner settings for this taxon.

        Args:
            max_lateness: How long to hold fixes for late arrivals; depends
                on how fixes are uploaded, not on the species.

        Returns:
            CleaningConfig: Settings for ``Cleaner``.
        """
        return CleaningConfig(
            max_lateness=max_lateness,
            max_speed_mps=self.max_speed_mps,
            gps_error_m=self.gps_error_m,
        )


# Vultures (Cathartidae). Speed, observed: tag-recorded ground speed on the
# tuning set has a 99.9th percentile of 18-19 m/s and a maximum of 23 m/s
# (turkey vulture; one black vulture reading of 65 m/s is a GPS error).
# Supporting only: Hirt et al. (2017) list the California condor, a related
# New World vulture, at 90 km/h (25 m/s), sourced from a website; their
# flying model predicts 36 m/s for a 2 kg bird but includes raptor stoop
# speeds. 30 m/s sits above everything observed, and the speed filter's
# 2 x 30 m GPS allowance keeps jitter on 1-3 min tags far below it.
# Mortality window, observed: chosen on the tuning-set
# sweep (results/sweep/SWEEP.md). 36 h cuts false mortality alerts by 38% against
# 24 h with no loss of carcass deaths flagged by the reference mark; 48 h
# cuts more but flags one death after the mark under satellite uploads.
# Movement floor, provisional: vultures cover tens of kilometres a day on
# the wing, so 10 km in 3 h. On the tuning set each bird's own threshold
# is above it for 32 of 34 birds, so it is a backstop.
_VULTURE_MORTALITY = MortalityConfig(window=timedelta(hours=36))
_VULTURE_MOVEMENT = MovementConfig(min_displacement_m=10_000.0)

PROFILES: dict[str, SpeciesProfile] = {
    profile.taxon: profile
    for profile in (
        SpeciesProfile("Cathartes aura", 30.0, _VULTURE_MORTALITY, _VULTURE_MOVEMENT),
        SpeciesProfile("Coragyps atratus", 30.0, _VULTURE_MORTALITY, _VULTURE_MOVEMENT),
        # Black-backed jackal. Speed, literature: 58-60 km/h (16.2-16.7
        # m/s; Christiansen 2002, Iriarte-Diaz 2002, as listed by Hirt et
        # al. 2017), rounded up to 17 m/s. Mortality window, provisional:
        # jackals lie up through the day and no published lie-up durations
        # were found, so the default 24 h. Movement floor, provisional: a
        # mean of 14.6 km a day (Kaunda 2001, VHF in Botswana), so 3 km in
        # 3 h is about 1.7 times the mean rate.
        SpeciesProfile(
            "Canis mesomelas",
            17.0,
            MortalityConfig(window=timedelta(hours=24)),
            MovementConfig(min_displacement_m=3_000.0),
        ),
        # African savanna elephant. Speed, literature: 35 km/h (Garland
        # 1983, as listed by Hirt et al. 2017); the fastest gait measured,
        # on Asian elephants, is about 6.7 m/s (Hutchinson et al. 2003), so
        # 11 m/s is a safe ceiling. Mortality window, provisional with
        # literature support: wild elephants sleep about 2 h a day, mostly
        # 02:00-06:00 (Gravett et al. 2017), and this population's stays at
        # water average 2.6-3.5 h (Thaker et al. 2019), so 12 h. Movement
        # floor, provisional: 3 km in 3 h is about 2.5 times this
        # population's mean speed of 0.4 km/h (Thaker et al. 2019).
        SpeciesProfile(
            "Loxodonta africana",
            11.0,
            MortalityConfig(window=timedelta(hours=12)),
            MovementConfig(min_displacement_m=3_000.0),
        ),
    )
}


def profile_for(taxon: str) -> SpeciesProfile:
    """Settings for a taxon.

    Args:
        taxon: Scientific name, as in Movebank.

    Returns:
        SpeciesProfile: The taxon's settings.

    Raises:
        KeyError: If no profile exists, rather than silently using another
            species' limits.
    """
    try:
        return PROFILES[taxon]
    except KeyError:
        raise KeyError(
            f"no species profile for {taxon!r}; add one to telemetry.core.species"
        ) from None
