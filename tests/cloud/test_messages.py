"""Tests for the cloud message: it survives JSON and names its deployment's
key and deduplication ID."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace

from cloud.messages import Message, UploadSettings, state_key
from cloud_helpers import RUN, messages


def test_message_round_trips_through_json():
    """The processor reads back exactly what the publisher wrote."""
    for message in messages("gsm"):
        sent = replace(message, sent_at=datetime(2026, 10, 20, tzinfo=timezone.utc))
        assert Message.from_json(sent.to_json()) == sent


def test_upload_settings_round_trip_without_an_interval():
    """``ideal`` uploads have no interval; None survives the trip."""
    settings = UploadSettings(None, timedelta(hours=3))
    assert UploadSettings.from_dict(settings.to_dict()) == settings


def test_keys_name_run_deployment_and_sequence():
    """Runs share tables, so keys carry the run."""
    message = messages()[3]
    assert message.key == state_key(RUN, "A") == f"{RUN}#A"
    assert message.dedup_id == f"{RUN}#A#3"
