"""Choose and freeze the fix-rate cue's definition on the tuning birds.

Run with ``make fixrate``, after ``make replay``. Pools the watch alerts of
the vulture tuning birds and the stork tuning populations, each group
weighted equally, and applies the rule in ``config/experiment.toml`` under
``[cues.fix_rate]``, fixed before the first run. Writes
``results/fixrate/fixrate.json`` and ``results/fixrate/FIXRATE.md``. Held-out
birds and populations are never read into a case.
"""

import json
from dataclasses import asdict
from pathlib import Path

from telemetry.analysis.acceleration import read_grades
from telemetry.analysis.evaluation import (
    TUNING,
    build_truth,
    read_incidents,
    read_labels,
)
from telemetry.analysis.experiment import experiment
from telemetry.analysis.fixrate import build_cases, fit, markdown
from telemetry.data.studies import STORK_GROUP, STUDIES, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
LABELS = ROOT / "data" / "labels.csv"


def main():
    """Build the tuning cases, apply the frozen rule and write the report."""
    settings = experiment()
    overrides = read_labels(LABELS)
    grades = read_grades(LABELS)
    cases = []
    vultures = next(study for study in STUDIES if study.slug == "vultures")
    deployments, fixes, _ = vultures.load(RAW)
    truths = [
        truth
        for truth in build_truth(vultures.slug, deployments, fixes, overrides)
        if truth.split == TUNING
    ]
    incidents = read_incidents(
        RESULTS
        / "replay"
        / "vultures"
        / settings.scenario("vultures")
        / "incidents.jsonl"
    )
    cases += build_cases("vultures", truths, incidents, fixes, grades, settings)
    scenario = settings.scenario(STORK_GROUP)
    # Held-out populations are not in this list, so their files stay unopened.
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        truths = build_truth(study.slug, deployments, fixes, overrides)
        incidents = read_incidents(
            RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
        )
        cases += build_cases("storks", truths, incidents, fixes, grades, settings)
    result = fit(cases, ["vultures", "storks"], settings)
    out = RESULTS / "fixrate"
    out.mkdir(parents=True, exist_ok=True)
    # Variants are dataclasses, which json cannot write, so turn them to dicts.
    (out / "fixrate.json").write_text(
        json.dumps(result, indent=2, default=asdict) + "\n", encoding="utf-8"
    )
    (out / "FIXRATE.md").write_text(markdown(result, settings), encoding="utf-8")
    print(f"{len(cases)} watch alerts written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
