"""Tests for the Fix record and its saved form."""

import json
from datetime import datetime, timezone

from telemetry.core.fixes import Fix

WHEN = datetime(2014, 6, 2, 8, 40, 47, tzinfo=timezone.utc)


def test_fix_without_sensors_serialises_as_before():
    """Unset sensor fields add no keys, so saved state is byte-identical
    to what it was before the fields existed."""
    assert list(Fix("100", WHEN, 47.75, 8.93).to_dict()) == [
        "deployment_id",
        "timestamp",
        "lat",
        "lon",
    ]


def test_fix_with_sensors_round_trips_through_json():
    """Every sensor reading survives to_dict, JSON and from_dict, and a
    reading of zero is kept rather than mistaken for missing."""
    fix = Fix("100", WHEN, 47.75, 8.93, 0.0, 21.5, 1.2, 3923.0)
    assert Fix.from_dict(json.loads(json.dumps(fix.to_dict()))) == fix


def test_partial_sensors_round_trip():
    """Only the readings present are saved and restored; the rest stay None."""
    fix = Fix("100", WHEN, 47.75, 8.93, voltage=3900.0)
    saved = fix.to_dict()
    assert saved["voltage"] == 3900.0 and "activity" not in saved
    assert Fix.from_dict(saved) == fix
