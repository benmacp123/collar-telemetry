"""Measure how often living animals stay still, per species and tag type.

Run with ``make stillness``. Uses the vulture tuning set only (every
tuning bird wears an Argos PTT tag, so tag types cannot be told apart
without the held-out set), the stork tuning populations and every jackal
and elephant, and writes
``results/stillness/stillness.json``, ``results/stillness/STILLNESS.md``
and ``results/figures/stillness-tail.png``.
"""

import json
from pathlib import Path

from telemetry.analysis.evaluation import (
    ALL,
    TUNING,
    build_truth,
    read_labels,
    split_for,
)
from telemetry.analysis.report import write_stillness
from telemetry.analysis.stillness import measure
from telemetry.data.studies import STUDIES, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"


def main():
    """Measure every study's living still-bout tail and write the results."""
    labels = read_labels(LABELS)
    sets = []
    # Held-out stork populations are not in this list, so their files are
    # never opened.
    for study in STUDIES + tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        # Held-out vultures are never loaded past this point, so choosing
        # a window from this output does not look at them.
        kept = {
            d.deployment_id
            for d in deployments
            if split_for(study.slug, d) in (TUNING, ALL)
        }
        deployments = [d for d in deployments if d.deployment_id in kept]
        fixes = [f for f in fixes if f.deployment_id in kept]
        truths = build_truth(study.slug, deployments, fixes, labels)
        sets.append(
            {
                "study": study.slug,
                "title": study.title,
                "set": truths[0].split,
                **measure(truths, fixes, study.tag_models(RAW)),
            }
        )
    out = RESULTS / "stillness"
    out.mkdir(parents=True, exist_ok=True)
    (out / "stillness.json").write_text(
        json.dumps({"sets": sets}, indent=2) + "\n", encoding="utf-8"
    )
    write_stillness(sets, out / "STILLNESS.md", RESULTS / "figures")
    print(f"{len(sets)} sets written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
