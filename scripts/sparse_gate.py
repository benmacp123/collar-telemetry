"""Work through the sparse-tag rule on the stork tuning populations.

Run with ``make sparse-gate``, after ``make replay``. Uses the stork tuning
populations only, under the scenario the experiment file judges storks on,
and writes ``results/sparse/sparse.json``, ``results/sparse/SPARSE.md`` and
``results/figures/sparse-tag.png``.
"""

import json
from pathlib import Path

from telemetry.analysis.acceleration import read_grades
from telemetry.analysis.evaluation import build_truth, read_incidents, read_labels
from telemetry.analysis.experiment import experiment
from telemetry.analysis.sparse import (
    build_cases,
    choose,
    figure,
    markdown,
    population_summary,
    threshold_row,
)
from telemetry.data.studies import STORK_GROUP, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
LABELS = ROOT / "data" / "labels.csv"


def main() -> None:
    """Measure each tuning population, apply the rule and write the results."""
    settings = experiment()
    gate = settings.gates["sparse_tag"]
    scenario = settings.scenario(STORK_GROUP)
    overrides = read_labels(LABELS)
    grades = read_grades(LABELS)
    populations = []
    # Held-out populations are not in this list, so their files are never
    # opened.
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        incidents = read_incidents(
            RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
        )
        truths = build_truth(study.slug, deployments, fixes, overrides)
        cases = build_cases(truths, incidents, fixes, grades, gate)
        populations.append(
            {
                "study": study.slug,
                "title": study.title,
                "summary": population_summary(cases),
                "rows": [
                    threshold_row(cases, truths, threshold, settings.animal_month)
                    for threshold in [None, *gate["thresholds_per_day"]]
                ],
            }
        )
    report = {
        "scenario": scenario,
        "gate": gate,
        "populations": populations,
        "choice": choose(populations, gate),
    }
    out = RESULTS / "sparse"
    out.mkdir(parents=True, exist_ok=True)
    (out / "sparse.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (out / "SPARSE.md").write_text(markdown(report), encoding="utf-8")
    figure(report, RESULTS / "figures" / "sparse-tag.png")
    print(f"choice: {report['choice']}; written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
