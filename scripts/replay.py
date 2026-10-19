"""Replay every committed study under every arrival scenario.

Run with ``make replay``. Reads only files in data/raw/ and writes, for
each study and scenario, ``results/replay/<study>/<scenario>/summary.json``
(committed) and ``incidents.jsonl`` (regenerated, not committed).
Options narrow the run, e.g. ``--study jackals --scenario ideal``.
"""

import argparse
import json
import time
from pathlib import Path

from telemetry.sim.arrival import SCENARIOS
from telemetry.sim.replay import DEFAULT_SEED, replay
from telemetry.data.studies import STUDIES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``study``, ``scenario`` and ``seed``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--study",
        action="append",
        choices=[study.slug for study in STUDIES],
        help="study to replay (repeatable; default all)",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=list(SCENARIOS),
        help="arrival scenario (repeatable; default all)",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


def main():
    """Replay the chosen studies and scenarios and write their results."""
    args = parse_args()
    studies = [s for s in STUDIES if not args.study or s.slug in args.study]
    scenarios = [SCENARIOS[name] for name in args.scenario or SCENARIOS]
    for study in studies:
        deployments, fixes, _ = study.load(RAW)
        fence = study.fence(RAW)
        for scenario in scenarios:
            started = time.perf_counter()
            result = replay(deployments, fixes, scenario, args.seed, fence=fence)
            out = RESULTS / "replay" / study.slug / scenario.name
            out.mkdir(parents=True, exist_ok=True)
            summary = {"study": study.slug, **result.summary}
            (out / "summary.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
            with open(out / "incidents.jsonl", "w", encoding="utf-8") as handle:
                for incident in result.incidents:
                    handle.write(json.dumps(incident.to_dict()) + "\n")
            # Run time goes to the console only, so summaries stay identical
            # between runs.
            print(
                f"{study.slug}/{scenario.name}: {len(result.incidents)} incidents "
                f"in {time.perf_counter() - started:.0f} s"
            )


if __name__ == "__main__":
    main()
