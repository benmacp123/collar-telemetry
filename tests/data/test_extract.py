"""Tests for the hourly reduction of raw tag events."""

import gzip
import math

import pytest

from telemetry.data import extract


def _fix(timestamp: str, **changes) -> dict:
    """One raw GPS event row.

    Args:
        timestamp: The fix time.
        **changes: Attribute values that differ from the defaults.

    Returns:
        dict: The row, keyed by Movebank attribute name.
    """
    row = {
        "individual_id": "1",
        "deployment_id": "10",
        "tag_id": "100",
        "timestamp": timestamp,
        "location_long": "8.5",
        "location_lat": "47.5",
        "eobs_temperature": "20",
        "visible": "true",
    }
    return row | changes


def _burst(timestamp: str, raw: str, **changes) -> dict:
    """One raw acceleration event row.

    Args:
        timestamp: The burst's start time.
        raw: The burst's readings.
        **changes: Attribute values that differ from the defaults.

    Returns:
        dict: The row, keyed by Movebank attribute name.
    """
    row = {
        "individual_id": "1",
        "deployment_id": "10",
        "tag_id": "100",
        "timestamp": timestamp,
        "eobs_acceleration_axes": "XYZ",
        "eobs_acceleration_sampling_frequency_per_axis": "10.54",
        "eobs_accelerations_raw": raw,
        "visible": "true",
    }
    return row | changes


def test_hour_of_truncates_to_the_clock_hour():
    """A timestamp maps to the start of its UTC hour."""
    assert extract.hour_of("2014-08-01 02:59:59.999") == "2014-08-01 02:00:00"


def test_hour_of_rejects_other_text():
    """Text that is not a Movebank timestamp is an error, not a bucket."""
    with pytest.raises(ValueError):
        extract.hour_of("2014-08-01T02")


def test_gps_keeps_the_earliest_fix_of_each_hour_in_any_order():
    """The first fix of the hour is kept however the rows arrive."""
    reducer = extract.GpsReducer()
    for stamp in (
        "2014-08-01 02:30:00.000",
        "2014-08-01 02:03:53.000",
        "2014-08-01 03:00:00.000",
        "2014-08-01 02:03:54.000",
    ):
        reducer.add(_fix(stamp))
    rows = reducer.result()
    assert [row["timestamp"] for row in rows] == [
        "2014-08-01 02:03:53.000",
        "2014-08-01 03:00:00.000",
    ]
    assert [row["fixes_in_hour"] for row in rows] == ["3", "1"]
    assert list(rows[0]) == list(extract.GPS_COLUMNS)


def test_gps_never_keeps_an_outlier_or_a_fix_without_a_position():
    """A hidden or position-less fix is counted and cannot stand for its hour."""
    reducer = extract.GpsReducer()
    reducer.add(_fix("2014-08-01 02:00:01.000", visible="false"))
    reducer.add(_fix("2014-08-01 02:00:02.000", location_lat=""))
    reducer.add(_fix("2014-08-01 02:00:03.000"))
    rows = reducer.result()
    assert [row["timestamp"] for row in rows] == ["2014-08-01 02:00:03.000"]
    assert rows[0]["fixes_in_hour"] == "1"
    assert (reducer.rows, reducer.not_visible, reducer.no_location) == (3, 1, 1)


def test_gps_copies_sensor_readings_and_blanks_missing_ones():
    """Readings are copied as text; one the study lacks becomes empty."""
    reducer = extract.GpsReducer()
    reducer.add(_fix("2014-08-01 02:00:03.000"))
    row = reducer.result()[0]
    assert row["eobs_temperature"] == "20"
    assert row["eobs_battery_voltage"] == ""


def test_gps_buckets_deployments_apart():
    """Two deployments in the same hour each keep their own fix."""
    reducer = extract.GpsReducer()
    reducer.add(_fix("2014-08-01 02:00:03.000"))
    reducer.add(_fix("2014-08-01 02:00:04.000", deployment_id="11"))
    assert [row["deployment_id"] for row in reducer.result()] == ["10", "11"]


def test_summarise_burst_splits_axes_in_turn():
    """Readings are dealt to the axes in order; spread sums their variances."""
    burst = extract.summarise_burst("1 10 100 3 10 104 ", "XYZ")
    assert burst["samples"] == 2
    assert burst["mean"] == {"x": 2.0, "y": 10.0, "z": 102.0}
    assert burst["spread"] == pytest.approx(math.sqrt(1 + 0 + 4))


def test_summarise_burst_handles_fewer_axes():
    """A two-axis burst gives two means and no third."""
    burst = extract.summarise_burst("1 5 3 7", "XY")
    assert burst["mean"] == {"x": 2.0, "y": 6.0}


@pytest.mark.parametrize(
    "raw, axes",
    [("", "XYZ"), ("1 2 3 4", "XYZ"), ("1 2 x", "XYZ"), ("1 2 3", ""), ("1 2", "XQ")],
)
def test_summarise_burst_rejects_what_it_cannot_read(raw, axes):
    """An empty, ragged, non-numeric or unlabelled burst gives None."""
    assert extract.summarise_burst(raw, axes) is None


def test_acc_summarises_the_hours_bursts():
    """An hour's row holds posture, posture change and the spread range."""
    reducer = extract.AccReducer()
    # A still burst (spread 0) and a moving one (x varies by +-2).
    reducer.add(_burst("2014-08-01 02:00:00.000", "10 20 30 10 20 30"))
    reducer.add(_burst("2014-08-01 02:10:00.000", "12 20 30 16 20 30"))
    reducer.add(_burst("2014-08-01 03:00:00.000", "10 20 30 10 20 30"))
    rows = reducer.result()
    assert [row["hour"] for row in rows] == [
        "2014-08-01 02:00:00",
        "2014-08-01 03:00:00",
    ]
    first = rows[0]
    assert list(first) == list(extract.ACC_COLUMNS)
    assert (first["bursts"], first["burst_samples"]) == ("2", "2")
    assert (first["mean_x"], first["mean_y"], first["mean_z"]) == (
        "12.0",
        "20.0",
        "30.0",
    )
    assert (first["between_x"], first["between_y"]) == ("2.0", "0.0")
    assert (first["spread_min"], first["spread_median"], first["spread_max"]) == (
        "0.00",
        "1.00",
        "2.00",
    )


def test_acc_counts_hidden_and_malformed_bursts():
    """Hidden and unreadable bursts are counted and left out."""
    reducer = extract.AccReducer()
    reducer.add(_burst("2014-08-01 02:00:00.000", "10 20 30", visible="false"))
    reducer.add(_burst("2014-08-01 02:00:00.000", "10 20"))
    reducer.add(_burst("2014-08-01 02:00:00.000", "10 20 30"))
    assert reducer.result()[0]["bursts"] == "1"
    assert (reducer.rows, reducer.not_visible, reducer.malformed) == (3, 1, 1)


def test_acc_keeps_set_ups_apart_and_blanks_unrecorded_axes():
    """A different axis set-up in the same hour gets its own row."""
    reducer = extract.AccReducer()
    reducer.add(_burst("2014-08-01 02:00:00.000", "10 20 30"))
    reducer.add(_burst("2014-08-01 02:10:00.000", "10 20", eobs_acceleration_axes="XY"))
    rows = reducer.result()
    assert [row["axes"] for row in rows] == ["XY", "XYZ"]
    assert (rows[0]["mean_z"], rows[0]["between_z"]) == ("", "")


def test_gzip_members_join_into_one_readable_file():
    """Members joined end to end read back as the joined text, byte-stable."""
    joined = extract.gzip_member("a,b\n") + extract.gzip_member("1,2\n")
    assert gzip.decompress(joined) == b"a,b\n1,2\n"
    assert extract.gzip_member("a,b\n") == extract.gzip_member("a,b\n")


def test_plan_parts_fills_in_order_without_passing_the_limit():
    """Blocks keep their order and a part never exceeds the limit."""
    parts = extract.plan_parts([("a", 4), ("b", 4), ("c", 4), ("d", 10)], 10)
    assert parts == [["a", "b"], ["c"], ["d"]]
    assert not extract.plan_parts([], 10)


def test_plan_parts_refuses_a_block_over_the_limit():
    """One block larger than a part is an error rather than a silent split."""
    with pytest.raises(ValueError):
        extract.plan_parts([("a", 11)], 10)
