"""Tests for a deployment's settings: the gap allowance follows the upload
plan, and ``stream_for`` builds independent, correctly configured streams.
"""

from dataclasses import dataclass
from datetime import timedelta

from telemetry.core.detectors.gap import GapConfig
from telemetry.core.pipeline import UPLOAD_MARGIN, gap_config, stream_for

HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"


@dataclass(frozen=True)
class Plan:
    """A minimal upload plan, as the cloud handler would pass."""

    upload_every: timedelta | None
    max_lateness: timedelta = timedelta(0)


def test_gap_allowance_is_upload_interval_plus_margin():
    """The clock allowance is the upload interval plus the margin; the
    active-hours floor stays at the detector default."""
    assert gap_config(Plan(None)).allowance == UPLOAD_MARGIN
    assert gap_config(Plan(HOUR)).allowance == HOUR + UPLOAD_MARGIN
    assert gap_config(Plan(48 * HOUR)).allowance == 48 * HOUR + UPLOAD_MARGIN
    assert gap_config(Plan(None)).min_silence == GapConfig().min_silence


def test_gap_margin_can_be_overridden():
    """A swept margin replaces the default on top of the upload interval."""
    assert gap_config(Plan(None), 12 * HOUR).allowance == 12 * HOUR
    assert gap_config(Plan(24 * HOUR), 12 * HOUR).allowance == 36 * HOUR


def test_stream_for_builds_an_empty_independent_stream():
    """Each call gives a fresh stream; the cleaner hold follows the plan."""
    first = stream_for(JACKAL, Plan(HOUR, max_lateness=3 * HOUR))
    second = stream_for(JACKAL, Plan(HOUR, max_lateness=3 * HOUR))
    assert not first.states and first.states is not second.states
    assert first.cleaner.config.max_lateness == 3 * HOUR
    assert [d.name for d in first.detectors] == ["mortality", "movement", "gap"]
