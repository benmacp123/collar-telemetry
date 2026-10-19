"""Size the cloud runner's messages and state, and prove slicing is exact.

Run with ``make cloud-sizing``. For each study under the scenarios the
cloud run uses, every deployment's timeline is cut into daily slices and
run slice by slice, with the slice and the deployment's state written to
JSON and read back between slices, as the Lambda handler will. The
incidents must equal the replay runner's; the script stops with an error
if they do not.

Writes ``results/cloud/sizing.json``: slice counts, the largest message
body and the largest saved state (the limits that matter are SQS's message
size and DynamoDB's 400 KB item size), and which part of the state is
largest. Byte counts are of compact JSON (no spaces), UTF-8.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from telemetry.arrival import SCENARIOS
from telemetry.replay import DEFAULT_SEED, replay, stream_for, timelines
from telemetry.slices import Slice, slice_timeline
from telemetry.stream import AnimalState
from telemetry.studies import STUDIES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "cloud" / "sizing.json"
CLOUD_SCENARIOS = ["satellite_daily", "gsm"]


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
    for timeline in timelines(deployments, fixes, scenario, DEFAULT_SEED):
        deployment_id = timeline.deployment.deployment_id
        saved = None
        for part in slice_timeline(deployment_id, timeline.arrivals, timeline.until):
            body = part.to_dict()
            message_sizes.append(compact(body))
            empty += not part.arrivals
            # A fresh stream per slice, as each Lambda invocation builds one.
            stream = stream_for(timeline.deployment.taxon, scenario, fence=fence)
            if saved is not None:
                stream.states[deployment_id] = AnimalState.from_dict(saved)
            message = Slice.from_dict(json.loads(json.dumps(body)))
            for incident in stream.advance(
                deployment_id, list(message.arrivals), message.until
            ):
                latest[incident.incident_id] = incident
            saved = json.loads(json.dumps(stream.states[deployment_id].to_dict()))
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
