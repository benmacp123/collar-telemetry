"""Sweep the white-stork mortality window on the stork tuning populations.

Run with ``make sweep-storks``. Replays only the populations
``tuning_storks()`` lists, so held-out storks are never opened, under the
scenario the experiment file judges storks on, once per window in
``[sweep.storks]``, and writes ``results/sweep/storks-tuning.json``,
``results/sweep/STORKS.md`` and ``results/figures/sweep-storks-tuning.png``.
Windows run in parallel; results do not depend on the order.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from telemetry.analysis.evaluation import build_truth, read_labels
from telemetry.analysis.experiment import experiment
from telemetry.analysis.stork_sweep import (
    Population,
    grid,
    reference_mark,
    stork_choice,
    sweep_point,
    write,
)
from telemetry.data.studies import STORK_GROUP, tuning_storks
from telemetry.sim.arrival import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"

# Loaded once per worker process by ``_load`` so each task only sends the
# setting, not every fix.
_DATA = {}


def _load() -> None:
    """Load the stork tuning populations into this worker process."""
    labels = read_labels(LABELS)
    populations = []
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        populations.append(
            Population(
                slug=study.slug,
                title=study.title,
                deployments=deployments,
                fixes=fixes,
                truths=build_truth(study.slug, deployments, fixes, labels),
            )
        )
    _DATA.update(
        populations=populations,
        mark=reference_mark([t for p in populations for t in p.truths]),
    )


def _run(overrides) -> dict:
    """Replay and score every population at one setting, in a worker.

    Args:
        overrides: The setting.

    Returns:
        dict: The sweep point.
    """
    scenario = SCENARIOS[experiment().scenario(STORK_GROUP)]
    return sweep_point(_DATA["populations"], scenario, overrides, _DATA["mark"])


def main():
    """Run the sweep and write its results."""
    settings = grid()
    # One worker per window at most: each holds both populations in memory.
    with ProcessPoolExecutor(
        max_workers=min(len(settings), 4), initializer=_load
    ) as pool:
        points = list(pool.map(_run, settings))
    _load()
    report = {
        "study": STORK_GROUP,
        "set": "tuning",
        "scenario": experiment().scenario(STORK_GROUP),
        "mark_hours": _DATA["mark"],
        "populations": {p.slug: p.title for p in _DATA["populations"]},
        "points": points,
        "choice": stork_choice(points),
    }
    out = RESULTS / "sweep"
    out.mkdir(parents=True, exist_ok=True)
    (out / "storks-tuning.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write(report, out / "STORKS.md", RESULTS / "figures" / "sweep-storks-tuning.png")
    print(
        f"{len(points)} windows written to {out.relative_to(ROOT)}; choice {report['choice']}"
    )


if __name__ == "__main__":
    main()
