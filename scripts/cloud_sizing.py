"""Size the cloud runner's messages and state, and prove slicing is exact.

Run with ``make cloud-sizing``. For each study under the scenarios the
cloud run uses, every deployment's timeline is cut into the publisher's
messages and run message by message, with the slice and the deployment's
state written to JSON and read back between messages, as the Lambda
handler will. The incidents must equal the replay runner's; the script
stops with an error if they do not.

Writes ``results/cloud/sizing.json``: message counts, the largest message
body and the largest saved state (the limits that matter are SQS's message
size and DynamoDB's 400 KB item size), and which part of the state is
largest. Byte counts are of compact JSON (no spaces), UTF-8.

It also models the state table's write request units, from the size of
each stored item as ``cloud.store`` builds it: ``stored`` for the layout
the processor writes (compressed state; a transaction only when incidents
changed), ``json_transaction`` for the first deployed layout (JSON state,
a transaction on every message), so the cut can be checked against a
metered run of each.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from datetime import datetime, timezone

from telemetry.sim.arrival import SCENARIOS
from telemetry.core.pipeline import stream_for
from telemetry.sim.replay import DEFAULT_SEED, replay
from telemetry.core.slices import Slice
from telemetry.core.stream import AnimalState
from telemetry.data.studies import STUDIES

from cloud.publisher import messages_for
from cloud.store import item_size, state_item, write_units

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "cloud" / "sizing.json"
CLOUD_SCENARIOS = ["satellite_daily", "gsm"]
# A stand-in write time, as long as the handler's (microseconds and offset).
STORED_AT = datetime(2026, 1, 1, 0, 0, 0, 1, tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``study`` and ``scenario``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--study", action="append", choices=[study.slug for study in STUDIES]
    )
    parser.add_argument(
        "--scenario", action="append", choices=list(SCENARIOS), default=None
    )
    return parser.parse_args()


def compact(data: dict) -> int:
    """Size of ``data`` as compact UTF-8 JSON.

    Args:
        data: Any JSON-ready dict.

    Returns:
        int: Bytes.
    """
    return len(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def percentile(values: list[int], share: float) -> int:
    """Nearest-rank percentile, enough for size reporting.

    Args:
        values: Non-empty list of numbers.
        share: Fraction in [0, 1].

    Returns:
        int: The value at that rank.
    """
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def size_one(study, deployments, fixes, fence, scenario) -> dict:
    """Run one study and scenario slice by slice and measure it.

    Args:
        study: The study, for its slug.
        deployments: The study's deployments.
        fixes: Their fixes.
        fence: The study's geofence, or None.
        scenario: The arrival scenario.

    Returns:
        dict: Counts and sizes for the run.

    Raises:
        AssertionError: If the sliced incidents differ from the replay's.
    """
    latest = {}
    message_sizes, state_sizes = [], []
    largest_state, largest_part = 0, Counter()
    empty = 0
    units = Counter()
    # Each layout's previous item size per deployment: a put bills the
    # larger of the old and new item.
    previous = {}
    for message in messages_for(study, deployments, fixes, scenario, DEFAULT_SEED):
        deployment_id = message.deployment_id
        saved = previous.get(deployment_id, {}).get("state")
        message_sizes.append(len(message.to_json().encode("utf-8")))
        empty += not message.slice.arrivals
        # A fresh stream per message, as each Lambda invocation builds one.
        stream = stream_for(message.taxon, scenario, fence=fence)
        if saved is not None:
            stream.states[deployment_id] = AnimalState.from_dict(saved)
        part = Slice.from_dict(json.loads(json.dumps(message.slice.to_dict())))
        changed = False
        for incident in stream.advance(deployment_id, list(part.arrivals), part.until):
            latest[incident.incident_id] = incident
            changed = True
        state = stream.states[deployment_id]
        saved = json.loads(json.dumps(state.to_dict()))
        sizes = layout_sizes(message, state, saved)
        before = previous.get(deployment_id, {})
        units["stored"] += write_units(
            max(sizes["stored"], before.get("stored", 0)), transaction=changed
        )
        units["json_transaction"] += write_units(
            max(sizes["json_transaction"], before.get("json_transaction", 0)),
            transaction=True,
        )
        previous[deployment_id] = sizes | {"state": saved}
        size = compact(saved)
        state_sizes.append(size)
        if size > largest_state:
            largest_state = size
            largest_part = Counter(
                {
                    key: compact({key: value})
                    for key, value in saved.items()
                    if key != "detectors"
                }
                | {
                    f"detectors.{name}": compact({name: value})
                    for name, value in saved["detectors"].items()
                }
            )

    expected = replay(deployments, fixes, scenario, DEFAULT_SEED, fence=fence)
    incidents = sorted(latest.values(), key=lambda i: (i.raised_at, i.incident_id))
    if incidents != expected.incidents:
        raise AssertionError(f"{study.slug}/{scenario.name}: sliced run differs")
    return {
        "study": study.slug,
        "scenario": scenario.name,
        "deployments": expected.summary["deployments"],
        "slices": len(message_sizes),
        "empty_slices": empty,
        "arrivals": expected.summary["arrivals"],
        "incidents": len(incidents),
        "matches_replay": True,
        "message_bytes": {
            "median": percentile(message_sizes, 0.5),
            "p99": percentile(message_sizes, 0.99),
            "max": max(message_sizes),
        },
        "state_bytes": {
            "median": percentile(state_sizes, 0.5),
            "p99": percentile(state_sizes, 0.99),
            "max": largest_state,
        },
        "largest_state_parts": dict(largest_part.most_common()),
        "state_write_units": dict(sorted(units.items())),
    }


def layout_sizes(message, state: AnimalState, saved: dict) -> dict:
    """The state item's size under each modelled layout.

    Args:
        message: The message applied.
        state: The deployment's state after it.
        saved: The same state as a JSON-ready dict.

    Returns:
        dict: Item bytes, ``stored`` (as the processor writes it) and
        ``json_transaction`` (the state as a compact JSON string).
    """
    item = state_item(message, state, STORED_AT)
    text = json.dumps(saved, separators=(",", ":"))
    return {
        "stored": item_size(item),
        "json_transaction": item_size(item | {"state": {"S": text}}),
    }


def main():
    """Size every chosen study and scenario and write the results."""
    args = parse_args()
    studies = [s for s in STUDIES if not args.study or s.slug in args.study]
    scenarios = [SCENARIOS[name] for name in args.scenario or CLOUD_SCENARIOS]
    runs = []
    for study in studies:
        deployments, fixes, _ = study.load(RAW)
        fence = study.fence(RAW)
        for scenario in scenarios:
            run = size_one(study, deployments, fixes, fence, scenario)
            print(
                f"{run['study']}/{run['scenario']}: {run['slices']} slices, "
                f"message max {run['message_bytes']['max']:,} B, "
                f"state max {run['state_bytes']['max']:,} B, matches replay"
            )
            runs.append(run)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
