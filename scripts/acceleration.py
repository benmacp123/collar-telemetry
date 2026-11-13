"""Fit the stork acceleration cue and write its likelihood-ratio table.

Run with ``make acceleration``, after ``make replay``. Uses the stork tuning
populations only, under the scenario the experiment file judges storks on,
and writes ``results/acceleration/acceleration.json`` and
``results/acceleration/ACCELERATION.md``. The cue's definition and the rule
that picks its threshold are in ``config/experiment.toml``, fixed before the
first fit.
"""

import json
from pathlib import Path

from telemetry.analysis.acceleration import build_cases, fit, markdown, read_grades
from telemetry.analysis.evaluation import build_truth, read_incidents, read_labels
from telemetry.analysis.experiment import experiment
from telemetry.data.studies import STORK_GROUP, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
LABELS = ROOT / "data" / "labels.csv"


def main():
    """Pool the tuning populations' watch alerts, fit the cue and write it."""
    settings = experiment()
    scenario = settings.scenario(STORK_GROUP)
    overrides = read_labels(LABELS)
    grades = read_grades(LABELS)
    cases = []
    animal_months = 0.0
    # Held-out populations are not in this list, so their files are never
    # opened.
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        truths = build_truth(study.slug, deployments, fixes, overrides)
        incidents = read_incidents(
            RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
        )
        readings = study.load_acceleration(RAW, deployments)
        cases += build_cases(truths, incidents, readings, grades, settings)
        animal_months += sum(
            (truth.last_fix - truth.first_fix) / settings.animal_month
            for truth in truths
        )
    result = fit(cases, settings, animal_months)
    out = RESULTS / "acceleration"
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceleration.json").write_text(
        json.dumps({"scenario": scenario, **result}, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "ACCELERATION.md").write_text(markdown(result, settings), encoding="utf-8")
    print(f"{len(cases)} watch alerts written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
