"""Sweep mortality and gap thresholds on the vulture tuning set.

Run with ``make sweep``. Replays only vulture deployments that start
before 2013 (the tuning set) under every setting in ``telemetry.sweep``
and every arrival scenario, and writes ``results/sweep/vultures-tuning.json``,
``results/SWEEP.md`` and ``results/figures/sweep-vultures-tuning.png``.
Settings run in parallel; results do not depend on the order.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from telemetry.arrival import SCENARIOS
from telemetry.evaluation import TUNING, build_truth, read_labels, reference_mark
from telemetry.evaluation import split_for
from telemetry.report import write_sweep
from telemetry.studies import STUDIES
from telemetry.sweep import grid, sweep_point

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"
STUDY = "vultures"

# Loaded once per worker process by ``_load`` so each task only sends the
# setting, not 100,000 fixes.
_DATA = {}


def _load() -> None:
    """Load the vulture tuning set into this worker process."""
    study = next(s for s in STUDIES if s.slug == STUDY)
    deployments, fixes, _ = study.load(RAW)
    tuning = {d.deployment_id for d in deployments if split_for(STUDY, d) == TUNING}
    deployments = [d for d in deployments if d.deployment_id in tuning]
    fixes = [f for f in fixes if f.deployment_id in tuning]
    truths = build_truth(STUDY, deployments, fixes, read_labels(LABELS))
    _DATA.update(
        deployments=deployments,
        fixes=fixes,
        truths=truths,
        mark=reference_mark(truths),
    )


def _run(task: tuple) -> dict:
    """Replay and score one setting under one scenario, in a worker.

    Args:
        task: (scenario name, swept detector, overrides).

    Returns:
        dict: The sweep row.
    """
    scenario, swept, overrides = task
    return sweep_point(
        _DATA["deployments"],
        _DATA["fixes"],
        _DATA["truths"],
        SCENARIOS[scenario],
        swept,
        overrides,
        _DATA["mark"],
    )


def main():
    """Run the sweep and write its results."""
    tasks = [(name, swept, o) for swept, o in grid() for name in SCENARIOS]
    with ProcessPoolExecutor(initializer=_load) as pool:
        rows = list(pool.map(_run, tasks))
    _load()
    report = {
        "study": STUDY,
        "set": TUNING,
        "deployments": len(_DATA["truths"]),
        "mark_hours": _DATA["mark"],
        "rows": rows,
    }
    out = RESULTS / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    (out / "vultures-tuning.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write_sweep(report, RESULTS / "SWEEP.md", RESULTS / "figures")
    print(f"{len(rows)} sweep points written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
