"""Compare how the mortality detector decides a still tag has moved again.

Run with ``make departure``. Replays the vulture tuning set and the
mammal variants rebuilt with ``TUNING_SEED`` (not the reported variants'
seed) under every setting in ``telemetry.analysis.departure`` and every
arrival scenario, and writes ``results/departure/departure.json`` and
``results/departure/DEPARTURE.md``. Settings run in parallel; results do
not depend on the order.
"""

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from telemetry.analysis.departure import (
    TUNING_SEED,
    grid,
    score_real,
    score_variant,
)
from telemetry.analysis.evaluation import (
    TUNING,
    build_truth,
    mammal_mark,
    read_labels,
    reference_mark,
    split_for,
)
from telemetry.analysis.report import write_departure
from telemetry.analysis.variants import VARIANTS
from telemetry.data.studies import STUDIES
from telemetry.sim.arrival import SCENARIOS

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"
VULTURES = "vultures"

# Loaded once per worker process by ``_load`` so each task only sends the
# setting, not hundreds of thousands of fixes.
_DATA = {}


def _load() -> None:
    """Load the vulture tuning set and the tuning-seed variants."""
    labels = read_labels(LABELS)
    study = next(s for s in STUDIES if s.slug == VULTURES)
    deployments, fixes, _ = study.load(RAW)
    tuning = {d.deployment_id for d in deployments if split_for(VULTURES, d) == TUNING}
    deployments = [d for d in deployments if d.deployment_id in tuning]
    fixes = [f for f in fixes if f.deployment_id in tuning]
    truths = build_truth(VULTURES, deployments, fixes, labels)
    mark = reference_mark(truths)
    _DATA[VULTURES] = (deployments, fixes, truths, None, mark)
    for variant in VARIANTS:
        built = variant.build(RAW, TUNING_SEED)
        truths = build_truth(variant.slug, built.deployments, built.fixes, labels)
        _DATA[variant.slug] = (
            built.deployments,
            built.fixes,
            truths,
            built.deaths,
            mammal_mark(mark, truths[0].taxon),
        )


def _run(task: tuple) -> dict:
    """Replay and score one setting on one set under one scenario.

    Args:
        task: (set name, scenario name, setting label, overrides).

    Returns:
        dict: The row, tagged with its set, scenario and setting.
    """
    name, scenario, label, overrides = task
    deployments, fixes, truths, deaths, mark = _DATA[name]
    if deaths is None:
        scores = score_real(
            deployments, fixes, truths, SCENARIOS[scenario], overrides, mark
        )
    else:
        scores = score_variant(
            deployments, fixes, truths, deaths, SCENARIOS[scenario], overrides, mark
        )
    return {
        "set": name,
        "scenario": scenario,
        "setting": label,
        **overrides.to_dict(),
        **scores,
    }


def main():
    """Run the comparison and write its results."""
    names = [VULTURES] + [v.slug for v in VARIANTS]
    tasks = [
        (name, scenario, label, overrides)
        for label, overrides in grid()
        for name in names
        for scenario in SCENARIOS
    ]
    with ProcessPoolExecutor(initializer=_load) as pool:
        rows = list(pool.map(_run, tasks))
    _load()
    report = {
        "tuning_seed": TUNING_SEED,
        "sets": {
            name: {"deployments": len(_DATA[name][0]), "mark_hours": _DATA[name][4]}
            for name in names
        },
        "rows": rows,
    }
    out = RESULTS / "departure"
    out.mkdir(parents=True, exist_ok=True)
    (out / "departure.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    write_departure(report, out / "DEPARTURE.md")
    print(f"{len(rows)} rows written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
