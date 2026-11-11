"""Fetch the white stork studies from Movebank and write the hourly extract.

Optional: the committed files in ``data/raw/storks/`` are what the analysis
reads, so nothing else needs network access or an account. Run this only to
rebuild them, with ``make fetch-storks``. It needs a free Movebank account
whose login is in ``~/.netrc`` (``machine www.movebank.org login ...
password ...``), and that account must already have accepted each study's
licence terms on movebank.org.

For every animal in the studies named in ``data/splits.csv`` the script
downloads the raw GPS and acceleration events one calendar year at a time,
reduces them with ``telemetry.data.extract`` (first fix and one
acceleration summary per UTC hour) and keeps the result in a cache under
``build/movebank/``, so an interrupted run carries on where it stopped.
It then writes, per study, gzipped CSV parts small enough for GitHub, the
study's reference tables, and one ``extract.json`` recording what was
fetched. Only counts are printed, never positions or alerts, so held-out
populations stay unseen.

Movebank allows one request at a time per address, so requests run one
after another; a full run takes hours.

Usage:
    PYTHONPATH=src python scripts/fetch_movebank.py [--study ID ...]
        [--max-mb 50]
"""

import argparse
import base64
import csv
import io
import json
import netrc
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

from telemetry.data import extract

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "raw" / "storks"
CACHE = ROOT / "build" / "movebank"
SPLITS = ROOT / "data" / "splits.csv"

HOST = "www.movebank.org"
API = f"https://{HOST}/movebank/service/direct-read"
USER_AGENT = "movebank-extract-script"
ATTEMPTS = 4
BACKOFF_S = 60
TIMEOUT_S = 600

# Movebank's sensor type IDs (entity_type=tag_type).
GPS_SENSOR = 653
ACC_SENSOR = 2365683

# Events at or after this UTC time are left out, so a rerun gives the same
# rows for birds that are still transmitting.
CUTOFF = datetime(2026, 11, 1)

# File-name stem for each study; the IDs must match data/splits.csv.
STUDIES = {
    21231406: "sw-germany",
    24442409: "bavaria",
    76367850: "rheinland-pfalz",
    173641633: "vorarlberg",
    212096177: "oberschwaben",
}

# Reference tables, with columns named because the default deployment
# table leaves out the animal and tag IDs. Names of people, tag owners and
# IMEI numbers are not requested.
REFERENCE = {
    "individuals": (
        "individual",
        "id,local_identifier,nick_name,ring_id,sex,taxon_canonical_name,"
        "exact_date_of_birth,earliest_date_born,latest_date_born,comments,"
        "death_comments,mortality_date,mortality_type,mortality_latitude,"
        "mortality_longitude,timestamp_start,timestamp_end,number_of_events,"
        "number_of_deployments,sensor_type_ids",
    ),
    "deployments": (
        "deployment",
        "id,local_identifier,individual_id,tag_id,deploy_on_timestamp,"
        "deploy_off_timestamp,deployment_end_type,deployment_end_comments,"
        "comments,animal_life_stage,attachment_type,duty_cycle,tag_readout_method,"
        "timestamp_start,timestamp_end,number_of_events,sensor_type_ids",
    ),
    "tags": (
        "tag",
        "id,local_identifier,manufacturer_name,model,weight,"
        "timestamp_start,timestamp_end,number_of_events,sensor_type_ids",
    ),
}

Reader = Callable[[dict], Iterator[dict]]

# Name, Movebank sensor ID, reducer and output columns of each table.
SENSORS = (
    ("gps", GPS_SENSOR, extract.GpsReducer, extract.GPS_COLUMNS),
    ("acc", ACC_SENSOR, extract.AccReducer, extract.ACC_COLUMNS),
)


def login() -> str:
    """Build the HTTP basic-auth header from ``~/.netrc``.

    Returns:
        str: The ``Authorization`` header value.

    Raises:
        RuntimeError: If ``~/.netrc`` has no entry for Movebank.
    """
    entry = netrc.netrc().authenticators(HOST)
    if entry is None:
        raise RuntimeError(f"~/.netrc has no entry for {HOST}")
    user, _, password = entry
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def read_csv(params: dict, auth: str) -> Iterator[dict]:
    """Stream one direct-read request as CSV rows.

    Args:
        params: Query parameters, such as ``entity_type`` and ``study_id``.
        auth: The ``Authorization`` header value from :func:`login`.

    Yields:
        dict: One row, keyed by the response's header.

    Raises:
        RuntimeError: If Movebank answers with licence terms rather than
            data, or the response lacks a requested column.
        urllib.error.URLError: If the request fails.
    """
    request = urllib.request.Request(
        f"{API}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": auth, "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        # Movebank sends the terms as the body, with this header, until
        # the account has accepted them; accepting is the owner's choice,
        # so stop rather than accept on their behalf.
        if response.headers.get("accept-license"):
            raise RuntimeError(
                f"study {params.get('study_id')} wants its licence terms accepted: "
                "download it once on movebank.org with this account, then rerun"
            )
        reader = csv.DictReader(
            io.TextIOWrapper(response, encoding="utf-8", newline="")
        )
        wanted = [name for name in params.get("attributes", "").split(",") if name]
        # The API documentation warns that naming attributes "may not
        # work" for some; a silently missing column would become a column
        # of blanks in the extract.
        if reader.fieldnames is not None:
            missing = sorted(set(wanted) - set(reader.fieldnames))
            if missing:
                raise RuntimeError(f"response lacks columns {missing} for {params}")
        yield from reader


def read_bytes(params: dict, auth: str) -> bytes:
    """Run one direct-read request and return its body unparsed.

    Args:
        params: Query parameters.
        auth: The ``Authorization`` header value from :func:`login`.

    Returns:
        bytes: The response body.
    """
    request = urllib.request.Request(
        f"{API}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": auth, "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return response.read()


def year_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    """Split a time span into calendar-year request windows.

    Movebank's bounds include both ends, so each window stops a
    millisecond before the next begins and no event is fetched twice.

    Args:
        start: First instant wanted.
        end: First instant not wanted.

    Returns:
        list[tuple[str, str]]: ``timestamp_start`` and ``timestamp_end``
        values in Movebank's ``yyyyMMddHHmmssSSS`` form; empty when the
        span is empty.
    """
    windows = []
    while start < end:
        stop = min(datetime(start.year + 1, 1, 1), end) - timedelta(milliseconds=1)
        windows.append(
            tuple(f"{t:%Y%m%d%H%M%S}{t.microsecond // 1000:03d}" for t in (start, stop))
        )
        start = datetime(start.year + 1, 1, 1)
    return windows


def with_retries(action: Callable[[], object], label: str) -> object:
    """Run a download step, waiting and retrying when the network fails.

    Args:
        action: The step; it must start from scratch each time it is called.
        label: What to call the step when reporting a retry.

    Returns:
        object: Whatever ``action`` returns.

    Raises:
        OSError: If the step still fails after ``ATTEMPTS`` tries.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return action()
        # URLError, timeouts and dropped connections are all OSError; a
        # RuntimeError (licence terms, missing column) is not retried.
        except OSError as error:
            if attempt == ATTEMPTS:
                raise
            wait = BACKOFF_S * attempt
            print(
                f"  {label}: {type(error).__name__}; retrying in {wait} s", flush=True
            )
            time.sleep(wait)
    raise AssertionError("unreachable")


def sensor_attributes(read: Reader, study_id: int, sensor: int, wanted: tuple) -> str:
    """The wanted event attributes that a study records for a sensor.

    Args:
        read: Runs one request and yields its rows.
        study_id: Movebank study ID.
        sensor: Movebank sensor type ID.
        wanted: Attribute names the reducer reads.

    Returns:
        str: Comma-separated names to request. The ID columns and
        ``visible`` are always asked for; a sensor reading the study never
        records is left out, and its column stays empty in the extract.
    """
    recorded = {
        row["short_name"]
        for row in read(
            {
                "entity_type": "study_attribute",
                "study_id": study_id,
                "sensor_type_id": sensor,
            }
        )
    }
    always = set(extract.KEY_COLUMNS) | {"visible", "timestamp"}
    return ",".join(name for name in wanted if name in always or name in recorded)


def reduce_events(read: Reader, base: dict, windows: list, reducer) -> None:
    """Feed every event of one animal and sensor to a reducer.

    Args:
        read: Runs one request and yields its rows.
        base: Query parameters shared by every window.
        windows: Request windows from :func:`year_windows`.
        reducer: A ``GpsReducer`` or ``AccReducer``.
    """
    for start, stop in windows:
        for row in read(base | {"timestamp_start": start, "timestamp_end": stop}):
            reducer.add(row)


def rows_to_text(rows: list[dict], columns: tuple) -> str:
    """Format reduced rows as CSV text without a header.

    Args:
        rows: Reduced rows.
        columns: Column order.

    Returns:
        str: One line per row, ``\\n`` line ends.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, columns, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def individual_windows(individual: dict) -> list[tuple[str, str]]:
    """The request windows covering one animal's track up to the cut-off.

    Args:
        individual: The animal's row from the study's individual table.

    Returns:
        list[tuple[str, str]]: Windows from :func:`year_windows`; empty for
        an animal with no events.
    """
    if not individual["timestamp_start"]:
        return []
    # timestamp_end is the last event, so step a millisecond past it to
    # make it the first instant not wanted.
    last = datetime.fromisoformat(individual["timestamp_end"])
    return year_windows(
        datetime.fromisoformat(individual["timestamp_start"]),
        min(last + timedelta(milliseconds=1), CUTOFF),
    )


def fetch_individual(
    read: Reader, study_id: int, individual: dict, attributes: dict
) -> dict:
    """Download and reduce one animal, unless the cache already holds it.

    Args:
        read: Runs one request and yields its rows.
        study_id: Movebank study ID.
        individual: The animal's row from the study's individual table.
        attributes: Attribute lists to request, by ``gps`` and ``acc``.

    Returns:
        dict: The animal's counts, as stored in its ``counts.json``.
    """
    folder = CACHE / str(study_id) / individual["id"]
    stamp = {"schema": extract.SCHEMA_VERSION, "cutoff": f"{CUTOFF:%Y-%m-%d %H:%M:%S}"}
    done = folder / "counts.json"
    if done.exists():
        counts = json.loads(done.read_text(encoding="utf-8"))
        if all(counts.get(key) == value for key, value in stamp.items()):
            return counts

    folder.mkdir(parents=True, exist_ok=True)
    windows = individual_windows(individual)
    base = {
        "entity_type": "event",
        "study_id": study_id,
        "individual_id": individual["id"],
    }
    counts = stamp | {"number_of_events": int(individual["number_of_events"] or 0)}
    for name, sensor, make, columns in SENSORS:

        def run(sensor=sensor, make=make, name=name):
            """Reduce this sensor's events from scratch.

            Returns:
                A filled reducer.
            """
            reducer = make()
            query = base | {"sensor_type_id": sensor, "attributes": attributes[name]}
            reduce_events(read, query, windows, reducer)
            return reducer

        reducer = with_retries(run, f"{individual['id']} {name}")
        rows = reducer.result()
        (folder / f"{name}.csv").write_text(
            rows_to_text(rows, columns), encoding="utf-8"
        )
        counts[name] = {
            key: value
            for key, value in vars(reducer).items()
            if not key.startswith("_")
        } | {"kept": len(rows)}
    # Written last, so a folder without it is an unfinished download.
    done.write_text(json.dumps(counts, indent=2), encoding="utf-8")
    return counts


def write_reference(
    read_raw: Callable[[dict], bytes], study_id: int, slug: str
) -> None:
    """Save a study's individual, deployment and tag tables as returned.

    Args:
        read_raw: Runs one request and returns the response body.
        study_id: Movebank study ID.
        slug: The study's file-name stem.
    """
    for name, (entity, attributes) in REFERENCE.items():
        body = read_raw(
            {"entity_type": entity, "study_id": study_id, "attributes": attributes}
        )
        (OUT / f"{slug}-{name}.csv").write_bytes(body)


def assemble(study_id: int, slug: str, individuals: list[str], max_bytes: int) -> dict:
    """Write one study's gzipped parts from the cache.

    Each part is a gzip file made of members joined end to end: the
    header, then one member per animal, in ascending animal ID.

    Args:
        study_id: Movebank study ID.
        slug: The study's file-name stem.
        individuals: IDs of the animals to include.
        max_bytes: The most a part may hold.

    Returns:
        dict: Part file names by ``gps`` and ``acc``.
    """
    files = {}
    for name, _, _, columns in SENSORS:
        for stale in OUT.glob(f"{slug}-{name}-*.csv.gz"):
            stale.unlink()
        header = extract.gzip_member(",".join(columns) + "\n")
        members = {}
        for individual in sorted(individuals, key=int):
            cached = CACHE / str(study_id) / individual / f"{name}.csv"
            text = cached.read_text(encoding="utf-8")
            if text:
                members[individual] = extract.gzip_member(text)
        sizes = ((key, len(member)) for key, member in members.items())
        files[name] = []
        for part in extract.plan_parts(sizes, max_bytes - len(header)):
            path = OUT / f"{slug}-{name}-{len(files[name]) + 1}.csv.gz"
            path.write_bytes(header + b"".join(members[key] for key in part))
            files[name].append(path.name)
    return files


def split_study_ids() -> set[int]:
    """The studies ``data/splits.csv`` puts on one side of the split.

    Returns:
        set[int]: Movebank IDs of the tuning and scoring studies.
    """
    with open(SPLITS, newline="", encoding="utf-8") as handle:
        return {
            int(row["movebank-study-id"])
            for row in csv.DictReader(handle)
            if row["split"] != "excluded"
        }


def incomplete_individuals(individuals: list[dict], counts: dict) -> list[str]:
    """Animals whose download does not match Movebank's own event count.

    Movebank's ``number_of_events`` counts an animal's visible fixes with a
    position, which is what the GPS reducer keeps before thinning, so the
    two agree when nothing was lost on the way. Animals still transmitting
    at the cut-off are skipped, as their count runs past it.

    Args:
        individuals: Rows of the study's individual table.
        counts: Each animal's counts from :func:`fetch_individual`, by ID.

    Returns:
        list[str]: IDs of the animals that disagree.
    """
    cutoff = f"{CUTOFF:%Y-%m-%d %H:%M:%S}"
    differing = []
    for individual in individuals:
        if not individual["timestamp_end"] or individual["timestamp_end"] >= cutoff:
            continue
        gps = counts[individual["id"]]["gps"]
        usable = gps["rows"] - gps["not_visible"] - gps["no_location"]
        if usable != int(individual["number_of_events"] or 0):
            differing.append(individual["id"])
    return differing


def fetch_study(read: Reader, study_id: int, slug: str, max_bytes: int) -> dict:
    """Fetch (or reuse from the cache) and assemble one study.

    Args:
        read: Runs one request and yields its rows.
        study_id: Movebank study ID.
        slug: The study's file-name stem.
        max_bytes: The most a part may hold.

    Returns:
        dict: The study's entry for ``extract.json``.
    """
    with open(OUT / f"{slug}-individuals.csv", newline="", encoding="utf-8") as handle:
        individuals = list(csv.DictReader(handle))
    attributes = {
        "gps": sensor_attributes(read, study_id, GPS_SENSOR, extract.GPS_ATTRIBUTES),
        "acc": sensor_attributes(read, study_id, ACC_SENSOR, extract.ACC_ATTRIBUTES),
    }
    counts = {}
    for position, individual in enumerate(individuals, start=1):
        result = fetch_individual(read, study_id, individual, attributes)
        counts[individual["id"]] = result
        print(
            f"  {slug} {position}/{len(individuals)}: "
            f"gps {result['gps']['rows']} -> {result['gps']['kept']}, "
            f"acc {result['acc']['rows']} -> {result['acc']['kept']}",
            flush=True,
        )
    files = assemble(study_id, slug, list(counts), max_bytes)
    incomplete = incomplete_individuals(individuals, counts)
    print(
        f"  {slug}: {len(incomplete)} animals differ from Movebank's own count",
        flush=True,
    )
    return {
        "study_id": study_id,
        "incomplete": incomplete,
        "requested": attributes,
        "files": files,
        "individuals": {
            key: {
                name: value for name, value in entry.items() if name in ("gps", "acc")
            }
            | {"number_of_events": entry["number_of_events"]}
            for key, entry in counts.items()
        },
    }


def main() -> None:
    """Fetch the studies and write the extract and its record."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--study", type=int, action="append", choices=sorted(STUDIES))
    parser.add_argument("--max-mb", type=float, default=50)
    args = parser.parse_args()
    if set(STUDIES) != split_study_ids():
        raise SystemExit("STUDIES does not match data/splits.csv")

    auth = login()

    def read(params: dict) -> Iterator[dict]:
        """Run one request with the login.

        Args:
            params: Query parameters.

        Returns:
            Iterator[dict]: The response's rows.
        """
        return read_csv(params, auth)

    OUT.mkdir(parents=True, exist_ok=True)
    record_path = OUT / "extract.json"
    record = (
        json.loads(record_path.read_text(encoding="utf-8"))
        if record_path.exists()
        else {"studies": {}}
    )
    record |= {
        "source": API,
        "cutoff": f"{CUTOFF:%Y-%m-%d %H:%M:%S}",
        "schema": extract.SCHEMA_VERSION,
    }
    for study_id in args.study or sorted(STUDIES):
        slug = STUDIES[study_id]
        print(f"{slug} ({study_id})", flush=True)
        with_retries(
            lambda study_id=study_id, slug=slug: write_reference(
                lambda params: read_bytes(params, auth), study_id, slug
            ),
            f"{slug} reference",
        )
        record["studies"][slug] = fetch_study(
            read, study_id, slug, int(args.max_mb * 1024 * 1024)
        ) | {"fetched": f"{datetime.now():%Y-%m-%d}"}
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
