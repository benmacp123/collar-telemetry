"""Tests for ``scripts/fetch_movebank.py``, with Movebank replaced by stand-ins.

No test touches the network or ``~/.netrc``: requests are answered by a
fake reader, and the cache and output folders point at a temporary one.
"""

import csv
import gzip
import importlib.util
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from telemetry.data import extract

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(name="script")
def _script(tmp_path, monkeypatch):
    """The fetch script as a module, writing under a temporary folder.

    Args:
        tmp_path: pytest's temporary folder.
        monkeypatch: pytest's patching helper.

    Returns:
        module: ``scripts/fetch_movebank.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "fetch_movebank", ROOT / "scripts" / "fetch_movebank.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(module, "OUT", tmp_path / "out")
    (tmp_path / "out").mkdir()
    return module


class FakeMovebank:
    """Answers event requests from a list of rows and remembers each request.

    Attributes:
        requests: The parameters of every request made, in order.
    """

    def __init__(self, events: list[dict]):
        """Hold the events to serve.

        Args:
            events: Event rows; each needs ``sensor_type_id`` and ``timestamp``.
        """
        self.events = events
        self.requests = []

    def __call__(self, params: dict):
        """Serve the events inside one request's sensor and time window.

        Args:
            params: The request's query parameters.

        Returns:
            list[dict]: The matching rows.
        """
        self.requests.append(params)
        return [
            row
            for row in self.events
            if row["sensor_type_id"] == params["sensor_type_id"]
            and params["timestamp_start"]
            <= _compact(row["timestamp"])
            <= params["timestamp_end"]
        ]


def _compact(timestamp: str) -> str:
    """A Movebank response timestamp in its request form.

    Args:
        timestamp: ``yyyy-MM-dd HH:mm:ss.SSS`` text.

    Returns:
        str: The same instant as ``yyyyMMddHHmmssSSS``.
    """
    return "".join(character for character in timestamp if character.isdigit())


def _event(sensor: int, timestamp: str, **values) -> dict:
    """One event row as the fake Movebank serves it.

    Args:
        sensor: Movebank sensor type ID.
        timestamp: The event time.
        **values: Further attribute values.

    Returns:
        dict: The row.
    """
    row = {
        "sensor_type_id": sensor,
        "individual_id": "7",
        "deployment_id": "70",
        "tag_id": "700",
        "timestamp": timestamp,
        "visible": "true",
    }
    return row | values


def _individual(script, **changes) -> dict:
    """An individual-table row for the fake animal.

    Args:
        script: The fetch script module.
        **changes: Values that differ from the defaults.

    Returns:
        dict: The row.
    """
    del script
    row = {
        "id": "7",
        "timestamp_start": "2014-12-31 23:00:00.000",
        "timestamp_end": "2015-01-01 01:00:00.000",
        "number_of_events": "2",
    }
    return row | changes


def _events(script) -> list[dict]:
    """Two fixes either side of a year boundary and one burst.

    Args:
        script: The fetch script module.

    Returns:
        list[dict]: Event rows for the fake Movebank.
    """
    place = {"location_long": "8.5", "location_lat": "47.5"}
    return [
        _event(script.GPS_SENSOR, "2014-12-31 23:00:00.000", **place),
        _event(script.GPS_SENSOR, "2015-01-01 00:00:00.000", **place),
        _event(
            script.ACC_SENSOR,
            "2015-01-01 01:00:00.000",
            eobs_acceleration_axes="XYZ",
            eobs_accelerations_raw="1 2 3 1 2 3",
        ),
    ]


ATTRIBUTES = {"gps": "timestamp", "acc": "timestamp"}


def test_studies_match_the_committed_split(script):
    """The script fetches exactly the studies the split file names."""
    assert set(script.STUDIES) == script.split_study_ids()


def test_year_windows_meet_without_overlapping(script):
    """Windows break at the new year, a millisecond apart, ends included."""
    windows = script.year_windows(
        datetime(2014, 6, 16, 9, 0, 7), datetime(2016, 3, 1, 12, 0, 0, 500000)
    )
    assert windows == [
        ("20140616090007000", "20141231235959999"),
        ("20150101000000000", "20151231235959999"),
        ("20160101000000000", "20160301120000499"),
    ]


def test_year_windows_of_an_empty_span_are_empty(script):
    """A span that ends where it starts asks for nothing."""
    assert script.year_windows(datetime(2014, 1, 1), datetime(2014, 1, 1)) == []


def test_individual_windows_include_the_last_event_and_stop_at_the_cutoff(script):
    """The last event is inside the final window; a live bird stops at the cut-off."""
    ended = script.individual_windows(_individual(script))
    assert ended[-1] == ("20150101000000000", "20150101010000000")
    live = script.individual_windows(
        _individual(
            script,
            timestamp_start="2026-10-31 00:00:00.000",
            timestamp_end="2026-11-11 18:00:29.000",
        )
    )
    assert live == [("20261031000000000", "20261031235959999")]
    assert script.individual_windows(_individual(script, timestamp_start="")) == []


def test_sensor_attributes_asks_only_for_what_the_study_records(script):
    """Unrecorded readings are not requested; IDs and the outlier flag always are."""

    def read(params):
        """Serve a study attribute list.

        Args:
            params: The request's query parameters.

        Returns:
            list[dict]: Two recorded attributes.
        """
        assert params["entity_type"] == "study_attribute"
        return [{"short_name": "location_lat"}, {"short_name": "eobs_temperature"}]

    names = script.sensor_attributes(read, 1, script.GPS_SENSOR, extract.GPS_ATTRIBUTES)
    assert names == (
        "individual_id,deployment_id,tag_id,timestamp,location_lat,"
        "eobs_temperature,visible"
    )


def test_fetch_individual_reduces_each_sensor_and_fetches_no_event_twice(script):
    """Events on a window boundary are counted once and the cache records them."""
    movebank = FakeMovebank(_events(script))
    counts = script.fetch_individual(movebank, 1, _individual(script), ATTRIBUTES)
    assert counts["gps"] == {"rows": 2, "not_visible": 0, "no_location": 0, "kept": 2}
    assert counts["acc"] == {"rows": 1, "not_visible": 0, "malformed": 0, "kept": 1}
    # Two calendar years for each of the two sensors.
    assert len(movebank.requests) == 4
    assert {request["individual_id"] for request in movebank.requests} == {"7"}
    folder = script.CACHE / "1" / "7"
    assert json.loads((folder / "counts.json").read_text("utf-8")) == counts
    assert len((folder / "gps.csv").read_text("utf-8").splitlines()) == 2


def test_fetch_individual_reuses_a_finished_download(script):
    """A second run makes no request for an animal already in the cache."""
    first = FakeMovebank(_events(script))
    counts = script.fetch_individual(first, 1, _individual(script), ATTRIBUTES)
    second = FakeMovebank([])
    assert script.fetch_individual(second, 1, _individual(script), ATTRIBUTES) == counts
    assert not second.requests


def test_fetch_individual_refetches_after_a_rule_change(script, monkeypatch):
    """A cache made under another schema version is not trusted."""
    script.fetch_individual(
        FakeMovebank(_events(script)), 1, _individual(script), ATTRIBUTES
    )
    monkeypatch.setattr(extract, "SCHEMA_VERSION", extract.SCHEMA_VERSION + 1)
    again = FakeMovebank(_events(script))
    script.fetch_individual(again, 1, _individual(script), ATTRIBUTES)
    assert len(again.requests) == 4


def test_with_retries_retries_network_errors_only(script, monkeypatch):
    """A dropped connection is retried; a refusal is raised at once."""
    monkeypatch.setattr(script.time, "sleep", lambda seconds: None)
    calls = []

    def flaky():
        """Fail once with a network error, then succeed.

        Returns:
            str: A marker value.
        """
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionResetError("dropped")
        return "done"

    assert script.with_retries(flaky, "step") == "done"
    assert len(calls) == 2

    def refused():
        """Fail as a licence refusal does.

        Raises:
            RuntimeError: Always.
        """
        calls.append(1)
        raise RuntimeError("terms")

    with pytest.raises(RuntimeError):
        script.with_retries(refused, "step")
    assert len(calls) == 3


def test_assemble_writes_readable_parts_in_animal_order(script):
    """Parts read back as a header plus each animal's rows, lowest ID first."""
    for individual, line in (("20", "b\n"), ("3", "a\n"), ("100", "")):
        folder = script.CACHE / "1" / individual
        folder.mkdir(parents=True)
        (folder / "gps.csv").write_text(line, encoding="utf-8")
        (folder / "acc.csv").write_text("", encoding="utf-8")
    stale = script.OUT / "demo-gps-9.csv.gz"
    stale.write_bytes(b"old")
    files = script.assemble(1, "demo", ["20", "3", "100"], 10_000)
    assert files == {"gps": ["demo-gps-1.csv.gz"], "acc": []}
    assert not stale.exists()
    with gzip.open(script.OUT / "demo-gps-1.csv.gz", "rt", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows == [list(extract.GPS_COLUMNS), ["a"], ["b"]]


def test_incomplete_individuals_compares_usable_fixes_with_movebanks_count(script):
    """An animal is flagged when its usable fixes differ from Movebank's count."""
    individuals = [
        _individual(script, id="1", number_of_events="8"),
        _individual(script, id="2", number_of_events="9"),
        # Still transmitting at the cut-off, so its count is not comparable.
        _individual(
            script,
            id="3",
            number_of_events="99",
            timestamp_end="2026-11-05 00:00:00.000",
        ),
    ]
    gps = {"rows": 10, "not_visible": 1, "no_location": 1}
    counts = {key: {"gps": gps} for key in ("1", "2", "3")}
    assert script.incomplete_individuals(individuals, counts) == ["2"]


class FakeResponse(io.BytesIO):
    """A stand-in for the object ``urlopen`` returns.

    Attributes:
        headers: The response headers.
    """

    def __init__(self, body: bytes, headers: dict):
        """Hold a body and headers.

        Args:
            body: The response body.
            headers: The response headers.
        """
        super().__init__(body)
        self.headers = headers


def test_read_csv_stops_at_licence_terms(script, monkeypatch):
    """Licence terms in place of data stop the run rather than being accepted."""
    monkeypatch.setattr(
        script.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(b"terms", {"accept-license": "true"}),
    )
    with pytest.raises(RuntimeError, match="licence"):
        list(script.read_csv({"study_id": 1}, "Basic x"))


def test_read_csv_refuses_a_response_missing_a_requested_column(script, monkeypatch):
    """A named attribute Movebank left out is an error, not a blank column."""
    monkeypatch.setattr(
        script.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(b"timestamp\n2014\n", {}),
    )
    with pytest.raises(RuntimeError, match="visible"):
        list(script.read_csv({"attributes": "timestamp,visible"}, "Basic x"))
    assert list(script.read_csv({"attributes": "timestamp"}, "Basic x")) == [
        {"timestamp": "2014"}
    ]
