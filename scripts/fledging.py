"""Measure the alert load before and after storks first leave the nest.

Run with ``make fledging``, after ``make replay``. Uses the stork tuning
populations only, under the scenario the experiment file judges storks
on, and writes ``results/fledging/fledging.json`` and
``results/fledging/FLEDGING.md``.
"""

import json
from pathlib import Path

from telemetry.analysis.evaluation import build_truth, read_incidents, read_labels
from telemetry.analysis.experiment import experiment
from telemetry.analysis.fledging import RADII_M, context_split, markdown, measure
from telemetry.data.studies import STORK_GROUP, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"
LABELS = ROOT / "data" / "labels.csv"


def main():
    """Measure each tuning population and write the results."""
    settings = experiment()
    scenario = settings.scenario(STORK_GROUP)
    overrides = read_labels(LABELS)
    sets = []
    # Held-out populations are not in this list, so their files are never
    # opened.
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        incidents = read_incidents(
            RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
        )
        truths = build_truth(study.slug, deployments, fixes, overrides)
        sets.append(
            {
                "study": study.slug,
                "title": study.title,
                "radii": [
                    measure(fixes, incidents, radius, settings.animal_month)
                    for radius in RADII_M
                ],
                "context": context_split(truths, incidents, settings.animal_month),
            }
        )
    out = RESULTS / "fledging"
    out.mkdir(parents=True, exist_ok=True)
    (out / "fledging.json").write_text(
        json.dumps({"scenario": scenario, "sets": sets}, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "FLEDGING.md").write_text(markdown(sets, scenario), encoding="utf-8")
    print(f"{len(sets)} populations written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
