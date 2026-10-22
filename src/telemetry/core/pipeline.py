"""How one deployment is configured: its detectors, cleaner and lifecycle.

``stream_for`` is the single place a deployment's settings are put
together, from its species profile, its upload plan and the study's
geofence. The replay runner and the cloud handler both call it, so they
run the same settings.

The gap detector's ``allowance`` (clock time, not active hours) is the
upload interval plus ``UPLOAD_MARGIN``: with daily uploads the newest fix
is up to a day old when it arrives, so a fixed threshold would raise a gap
alert every day. The 36 h margin was chosen on the tuning-set sweep
(``results/sweep/SWEEP.md``); it also absorbs whole GSM out-of-coverage
days. ``Overrides`` replaces the defaults for threshold sweeps.
"""

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Protocol

from telemetry.core.alerts import (
    POTENTIAL_DEATH,
    MORTALITY,
    AlertLifecycle,
    LifecycleConfig,
)
from telemetry.core.cleaning import Cleaner
from telemetry.core.detectors.gap import GapConfig, GapDetector
from telemetry.core.detectors.geofence import Fence, GeofenceDetector
from telemetry.core.detectors.mortality import MortalityDetector
from telemetry.core.detectors.movement import MovementDetector
from telemetry.core.species import SpeciesProfile, profile_for
from telemetry.core.stream import Detector, FixStream

UPLOAD_MARGIN = timedelta(hours=36)
MERGE_SLACK = timedelta(hours=12)


class UploadPlan(Protocol):
    """How a collar uploads, as far as the settings depend on it.

    The replay runner passes an ``ArrivalScenario``; the cloud handler
    passes the plan named in its message.

    Attributes:
        upload_every: Time between uploads; None if every fix is sent as
            it is taken.
        max_lateness: How long the cleaner holds fixes to put late ones
            back in order.
    """

    upload_every: timedelta | None
    max_lateness: timedelta


@dataclass(frozen=True)
class Overrides:
    """Settings that replace the defaults, for threshold sweeps.

    The defaults reproduce a plain replay exactly.

    Attributes:
        mortality_window: Replaces every species' mortality window; None
            keeps them. The mortality merge window follows it, at the
            window plus ``MERGE_SLACK``, since a reopen can never come
            sooner than the window.
        mortality_box_m: Replaces the mortality detector's stationary box
            (``max_extent_m``); None keeps it.
        upload_margin: Silence allowed beyond the upload interval before a
            gap alert.
        mortality_leave_fixes: Replaces the fixes outside the cluster that
            confirm a move; None keeps it.
        mortality_leave_radius_m: Replaces the mortality detector's
            radius from the alert's centre once alerted; None keeps it.
        mortality_merge: Replaces the mortality and ``potential_death`` merge
            window, whatever the window; None keeps the default (or the
            one following ``mortality_window``).
        mortality_box_only: Drops the leaving radius, so the box decides
            after the alert too, as before the radius was added.
    """

    mortality_window: timedelta | None = None
    mortality_box_m: float | None = None
    upload_margin: timedelta = UPLOAD_MARGIN
    mortality_leave_fixes: int | None = None
    mortality_leave_radius_m: float | None = None
    mortality_merge: timedelta | None = None
    mortality_box_only: bool = False

    def profile(self, profile: SpeciesProfile) -> SpeciesProfile:
        """A species profile with these overrides applied.

        Args:
            profile: The species' own settings.

        Returns:
            SpeciesProfile: The profile, with the mortality settings
            replaced where set.
        """
        mortality = profile.mortality
        if self.mortality_window is not None:
            mortality = replace(mortality, window=self.mortality_window)
        if self.mortality_box_m is not None:
            mortality = replace(mortality, max_extent_m=self.mortality_box_m)
        if self.mortality_leave_fixes is not None:
            mortality = replace(mortality, leave_fixes=self.mortality_leave_fixes)
        if self.mortality_leave_radius_m is not None:
            mortality = replace(mortality, leave_radius_m=self.mortality_leave_radius_m)
        if self.mortality_box_only:
            mortality = replace(mortality, leave_radius_m=None)
        return replace(profile, mortality=mortality)

    def lifecycle(self) -> AlertLifecycle:
        """The alert lifecycle for these overrides.

        Returns:
            AlertLifecycle: Default merge windows, or a mortality merge
            window that is overridden or follows an overridden window.
        """
        merge = self.mortality_merge
        if merge is None and self.mortality_window is not None:
            merge = self.mortality_window + MERGE_SLACK
        if merge is None:
            return AlertLifecycle()
        return AlertLifecycle(
            LifecycleConfig({MORTALITY: merge, POTENTIAL_DEATH: merge})
        )

    def to_dict(self) -> dict:
        """JSON-ready form, in hours and metres.

        Returns:
            dict: Every setting; None where a default is kept.
        """
        hours = timedelta(hours=1)
        return {
            "mortality_window_hours": (
                self.mortality_window / hours
                if self.mortality_window is not None
                else None
            ),
            "mortality_box_m": self.mortality_box_m,
            "upload_margin_hours": self.upload_margin / hours,
            "mortality_leave_fixes": self.mortality_leave_fixes,
            "mortality_leave_radius_m": self.mortality_leave_radius_m,
            "mortality_merge_hours": (
                self.mortality_merge / hours
                if self.mortality_merge is not None
                else None
            ),
            "mortality_box_only": self.mortality_box_only,
        }


def gap_config(uploads: UploadPlan, margin: timedelta = UPLOAD_MARGIN) -> GapConfig:
    """Gap settings for an upload plan.

    Args:
        uploads: The upload plan.
        margin: Silence allowed beyond the upload interval.

    Returns:
        GapConfig: The defaults, with ``allowance`` set to the upload
        interval (none for ideal arrival) plus ``margin``.
    """
    upload = uploads.upload_every or timedelta(0)
    return replace(GapConfig(), allowance=upload + margin)


def detectors_for(
    profile: SpeciesProfile,
    uploads: UploadPlan,
    margin: timedelta = UPLOAD_MARGIN,
    fence: Fence | None = None,
) -> list[Detector]:
    """The detectors a deployment is run through.

    Args:
        profile: The deployment's species settings.
        uploads: The upload plan, which sets the gap threshold.
        margin: Silence allowed beyond the upload interval.
        fence: The study's geofence, or None.

    Returns:
        list[Detector]: Mortality, unusual-movement and gap detectors, and
        a geofence detector when there is a fence.
    """
    detectors = [
        MortalityDetector(profile.mortality),
        MovementDetector(profile.movement),
        GapDetector(gap_config(uploads, margin)),
    ]
    if fence is not None:
        detectors.append(GeofenceDetector(fence))
    return detectors


def stream_for(
    taxon: str,
    uploads: UploadPlan,
    overrides: Overrides | None = None,
    fence: Fence | None = None,
    lifecycle: AlertLifecycle | None = None,
) -> FixStream:
    """An empty stream configured for one deployment.

    Each deployment gets its own stream, since detector and cleaner
    settings depend on the species; the detectors themselves hold no
    state. The cloud handler builds its stream here too, so both runners
    use the same settings.

    Args:
        taxon: The deployment's taxon, which picks the species profile.
        uploads: The upload plan, which sets the gap allowance and the
            cleaner's hold.
        overrides: Settings replacing the defaults, for sweeps; None keeps
            the defaults.
        fence: The study's geofence, or None.
        lifecycle: A lifecycle to share between streams; built from
            ``overrides`` if omitted.

    Returns:
        FixStream: A stream with no state yet.

    Raises:
        KeyError: If the taxon has no species profile.
    """
    overrides = overrides or Overrides()
    profile = overrides.profile(profile_for(taxon))
    return FixStream(
        detectors_for(profile, uploads, overrides.upload_margin, fence),
        Cleaner(profile.cleaning(uploads.max_lateness)),
        lifecycle or overrides.lifecycle(),
    )
