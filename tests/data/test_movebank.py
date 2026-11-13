"""Tests for reading Movebank reference-data and event CSVs."""

import gzip
from datetime import datetime, timezone

import pytest

from telemetry.data.movebank import (
    parse_timestamp,
    read_deployments,
    read_extract_deployments,
    read_extract_fixes,
    read_extract_tag_models,
    read_fixes,
    read_tag_models,
)

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


def test_read_tag_models_falls_back_to_manufacturer(tmp_path):
    """Tag model is used if given, then the manufacturer, then "unknown"."""
    path = write(
        tmp_path / "ref.csv",
        "deployment-id,tag-model,tag-manufacturer-name\n",
        ["D1,Argos PTT,Microwave", "D2,,Microwave", "D3,,"],
    )
    assert read_tag_models(path) == {
        "D1": "Argos PTT",
        "D2": "Microwave",
        "D3": "unknown",
    }


DEPLOYMENT_HEADER = (
    "id,local_identifier,individual_id,tag_id,deploy_on_timestamp,"
    "deploy_off_timestamp,deployment_end_type\n"
)
INDIVIDUAL_HEADER = "id,local_identifier,taxon_canonical_name\n"
TAG_HEADER = "id,local_identifier,manufacturer_name,model\n"
GPS_HEADER = "individual_id,deployment_id,tag_id,timestamp,location_long,location_lat\n"


@pytest.fixture
def extract(tmp_path):
    """An extract's reference tables: animal 1 with two deployments of
    tags 7 and 8, and animal 2 with no deployment."""
    write(
        tmp_path / "individuals.csv",
        INDIVIDUAL_HEADER,
        ['1,"A + / DER X1",Ciconia ciconia', '2,"B",Ciconia ciconia'],
    )
    write(
        tmp_path / "deployments.csv",
        DEPLOYMENT_HEADER,
        [
            '100,"7 on X1",1,7,2014-06-01 00:00:00.000,' "2014-06-30 00:00:00.000,dead",
            '101,"8 on X1",1,8,2015-06-01 00:00:00.000,,',
        ],
    )
    write(
        tmp_path / "tags.csv",
        TAG_HEADER,
        ['7,"7",e-obs GmbH,Solar GSM', '8,"8",e-obs GmbH,'],
    )
    return tmp_path


def gps_part(path, rows):
    """Write a gzip GPS part with ``rows`` and return the path."""
    with gzip.open(path, "wt", newline="", encoding="utf-8") as handle:
        handle.write(GPS_HEADER + "".join(row + "\n" for row in rows))
    return path


def test_extract_deployments_take_the_taxon_from_the_individual_table(extract):
    """Deployments carry Movebank's numeric IDs and the animal's taxon."""
    first, second = read_extract_deployments(
        extract / "deployments.csv", extract / "individuals.csv"
    )
    assert (first.deployment_id, first.tag_id, first.animal_id) == ("100", "7", "1")
    assert first.taxon == "Ciconia ciconia"
    assert first.end_type == "dead"
    assert first.deploy_off == datetime(2014, 6, 30, tzinfo=timezone.utc)
    assert second.deploy_off is None and second.end_type is None


def test_extract_deployment_of_an_unknown_animal_is_refused(extract):
    """A deployment whose animal is missing stops the load, as its taxon
    would otherwise have to be guessed."""
    write(extract / "individuals.csv", INDIVIDUAL_HEADER, ['2,"B",Ciconia ciconia'])
    with pytest.raises(ValueError, match="unknown animal"):
        read_extract_deployments(
            extract / "deployments.csv", extract / "individuals.csv"
        )


def test_extract_fixes_join_on_the_deployment_id(extract):
    """A fix goes to the deployment its row names; a row naming none, or
    timed outside it, is counted as unmatched."""
    deployments = read_extract_deployments(
        extract / "deployments.csv", extract / "individuals.csv"
    )
    part = gps_part(
        extract / "x-gps-1.csv.gz",
        [
            "1,100,7,2014-06-02 08:40:47.000,8.93,47.75",
            "1,101,8,2015-06-02 09:00:10.000,8.94,47.76",
            "1,999,7,2014-06-02 10:00:00.000,8.93,47.75",
            "1,100,7,2014-07-02 10:00:00.000,8.93,47.75",
        ],
    )
    fixes, report = read_extract_fixes([part], deployments)
    assert [(f.deployment_id, f.lat, f.lon) for f in fixes] == [
        ("100", 47.75, 8.93),
        ("101", 47.76, 8.94),
    ]
    assert fixes[0].timestamp == datetime(2014, 6, 2, 8, 40, 47, tzinfo=timezone.utc)
    assert (report.rows, report.unmatched) == (4, 2)


def test_extract_sensors_are_read_only_when_asked(extract):
    """With ``sensors`` the tag readings reach the fix, blank cells stay
    None and a zero is kept; without it the fixes carry none."""
    deployments = read_extract_deployments(
        extract / "deployments.csv", extract / "individuals.csv"
    )
    part = extract / "x-gps-1.csv.gz"
    with gzip.open(part, "wt", newline="", encoding="utf-8") as handle:
        handle.write(
            "individual_id,deployment_id,tag_id,timestamp,location_long,"
            "location_lat,gps_dop,eobs_temperature,eobs_battery_voltage,"
            "eobs_activity\n"
            "1,100,7,2014-06-02 08:40:47.000,8.93,47.75,1.5,21,3923,0\n"
            "1,100,7,2014-06-02 09:40:47.000,8.93,47.75,,,,\n"
        )
    plain, _ = read_extract_fixes([part], deployments)
    assert all(
        (f.activity, f.temperature, f.hdop, f.voltage) == (None,) * 4 for f in plain
    )
    full, _ = read_extract_fixes([part], deployments, sensors=True)
    assert (full[0].activity, full[0].temperature) == (0.0, 21.0)
    assert (full[0].hdop, full[0].voltage) == (1.5, 3923.0)
    assert (full[1].activity, full[1].voltage) == (None, None)


def test_export_hdop_is_read_only_when_asked(reused_collar, tmp_path):
    """An export's ``gps:hdop`` column becomes the fix's hdop on request."""
    events = write(
        tmp_path / "events.csv",
        EVENT_HEADER.rstrip("\n") + ",gps:hdop\n",
        ["1,true,2009-03-01 00:00:00.000,16.0,-19.0,T1,A,0.8"],
    )
    deployments = read_deployments(reused_collar)
    assert read_fixes(events, deployments)[0][0].hdop is None
    assert read_fixes(events, deployments, sensors=True)[0][0].hdop == 0.8


def test_extract_tag_models_fall_back_to_the_manufacturer(extract):
    """Tag model by deployment, the manufacturer standing in when blank."""
    assert read_extract_tag_models(
        extract / "deployments.csv", extract / "tags.csv"
    ) == {"100": "Solar GSM", "101": "e-obs GmbH"}
