"""Tests for reading Movebank reference-data and event CSVs."""

from datetime import datetime, timezone

import pytest

from telemetry.movebank import parse_timestamp, read_deployments, read_fixes

REFERENCE_HEADER = (
    "tag-id,animal-id,animal-taxon,deploy-on-date,deploy-off-date,"
    "deployment-end-type,deployment-id\n"
)
EVENT_HEADER = (
    "event-id,visible,timestamp,location-long,location-lat,"
    "tag-local-identifier,individual-local-identifier\n"
)


def write(path, header, rows):
    """Write a CSV with ``header`` and ``rows`` to ``path`` and return the path."""
    path.write_text(header + "".join(row + "\n" for row in rows), encoding="utf-8")
    return path


@pytest.fixture
def reused_collar(tmp_path):
    """Tag T1 recovered from dead animal A and refitted to animal B."""
    return write(
        tmp_path / "ref.csv",
        REFERENCE_HEADER,
        [
            "T1,A,Canis mesomelas,2009-02-06 00:00:00.000,"
            "2009-05-02 23:59:00.000,dead,T1-A",
            "T1,B,Canis mesomelas,2009-07-29 00:00:00.000,,,T1-B",
        ],
    )


def test_parse_timestamp_is_utc():
    """Movebank timestamps are parsed as timezone-aware UTC."""
    assert parse_timestamp("2009-02-07 00:01:20.000") == datetime(
        2009, 2, 7, 0, 1, 20, tzinfo=timezone.utc
    )


def test_read_deployments(reused_collar):
    """Deploy-off and end type are read, and blank ones become None."""
    first, second = read_deployments(reused_collar)
    assert first.deployment_id == "T1-A"
    assert first.end_type == "dead"
    assert first.deploy_off == datetime(2009, 5, 2, 23, 59, tzinfo=timezone.utc)
    assert second.deploy_off is None
    assert second.end_type is None


def test_duplicate_deployment_id_rejected(tmp_path):
    """A repeated deployment ID would merge two animals' state, so it is an error."""
    path = write(
        tmp_path / "ref.csv",
        REFERENCE_HEADER,
        ["T1,A,x,2009-01-01 00:00:00.000,,,D1"] * 2,
    )
    with pytest.raises(ValueError, match="duplicate"):
        read_deployments(path)


def test_missing_deploy_on_rejected(tmp_path):
    """A deployment without a start date cannot be matched to fixes."""
    path = write(tmp_path / "ref.csv", REFERENCE_HEADER, ["T1,A,x,,,,D1"])
    with pytest.raises(ValueError, match="deploy-on"):
        read_deployments(path)


def test_reused_collar_fixes_go_to_the_right_deployment(tmp_path, reused_collar):
    """Fixes from a reused tag are split by animal and date, not merged by tag."""
    events = write(
        tmp_path / "events.csv",
        EVENT_HEADER,
        [
            "1,true,2009-03-01 00:00:00.000,15.8,-19.0,T1,A",
            "2,true,2009-08-01 00:00:00.000,15.9,-19.1,T1,B",
        ],
    )
    fixes, report = read_fixes(events, read_deployments(reused_collar))
    assert [fix.deployment_id for fix in fixes] == ["T1-A", "T1-B"]
    assert report.rows == 2 and report.unmatched == 0


def test_fixes_outside_the_deployment_window_are_dropped(tmp_path, reused_collar):
    """Fixes outside deploy-on/off or from an unknown tag are dropped and counted."""
    events = write(
        tmp_path / "events.csv",
        EVENT_HEADER,
        [
            "1,true,2009-02-05 23:00:00.000,15.8,-19.0,T1,A",  # before deploy-on
            "2,true,2009-05-03 00:00:00.000,15.8,-19.0,T1,A",  # after deploy-off
            "3,true,2009-03-01 00:00:00.000,15.8,-19.0,T9,A",  # unknown tag
        ],
    )
    fixes, report = read_fixes(events, read_deployments(reused_collar))
    assert not fixes
    assert report.unmatched == 3


def test_invisible_and_empty_rows_are_counted(tmp_path, reused_collar):
    """Rows Movebank flags as outliers or without a location are dropped and counted."""
    events = write(
        tmp_path / "events.csv",
        EVENT_HEADER,
        [
            "1,false,2009-03-01 00:00:00.000,15.8,-19.0,T1,A",
            "2,true,2009-03-01 01:00:00.000,,,T1,A",
            "3,true,2009-03-01 02:00:00.000,15.8,-19.0,T1,A",
        ],
    )
    fixes, report = read_fixes(events, read_deployments(reused_collar))
    assert len(fixes) == 1
    assert (report.not_visible, report.no_location) == (1, 1)


def test_file_order_is_kept(tmp_path, reused_collar):
    """The reader does not sort; ordering is the cleaning stage's job."""
    events = write(
        tmp_path / "events.csv",
        EVENT_HEADER,
        [
            "1,true,2009-03-01 02:00:00.000,15.8,-19.0,T1,A",
            "2,true,2009-03-01 01:00:00.000,15.8,-19.0,T1,A",
        ],
    )
    fixes, _ = read_fixes(events, read_deployments(reused_collar))
    assert fixes[0].timestamp > fixes[1].timestamp


def test_split_event_files_are_read_in_order(tmp_path, reused_collar):
    """Parts of a split event file are read as one file, in the order given."""
    first = write(
        tmp_path / "events-1.csv",
        EVENT_HEADER,
        ["1,true,2009-03-01 00:00:00.000,15.8,-19.0,T1,A"],
    )
    second = write(
        tmp_path / "events-2.csv",
        EVENT_HEADER,
        [
            "2,true,2009-08-01 00:00:00.000,15.9,-19.1,T1,B",
            "3,false,2009-08-01 01:00:00.000,15.9,-19.1,T1,B",
        ],
    )
    fixes, report = read_fixes([first, second], read_deployments(reused_collar))
    assert [fix.deployment_id for fix in fixes] == ["T1-A", "T1-B"]
    assert (report.rows, report.not_visible) == (3, 1)
