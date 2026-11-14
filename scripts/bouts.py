"""Sort the storks' long living still bouts into classes.

Run with ``make bouts``. Uses the stork tuning populations only, with
the class cut-offs from ``[descriptive.still_bouts]`` in the experiment
file, and writes ``results/bouts/bouts.json``,
``results/bouts/BOUTS.md`` and ``results/figures/bouts-classes.png``.
"""

import json
from pathlib import Path

from telemetry.analysis.bouts import Rules, markdown, measure
from telemetry.analysis.evaluation import build_truth, read_labels
from telemetry.analysis.experiment import experiment
from telemetry.analysis.report import write_bouts_figure
from telemetry.data.studies import tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"


def main():
    """Class each tuning population's long bouts and write the results."""
    settings = experiment()
    rules = Rules.from_table(settings.descriptive["still_bouts"])
    labels = read_labels(LABELS)
    sets = []
    # Held-out populations are not in this list, so their files are never
    # opened.
    for study in tuning_storks():
        deployments, fixes, _ = study.load(RAW)
        truths = build_truth(study.slug, deployments, fixes, labels)
        spread = study.load_acceleration(RAW, deployments)
        sets.append(
            {
                "study": study.slug,
                "title": study.title,
                **measure(truths, fixes, rules, settings.animal_month, spread),
            }
        )
    out = RESULTS / "bouts"
    out.mkdir(parents=True, exist_ok=True)
    (out / "bouts.json").write_text(
        json.dumps({"sets": sets}, indent=2) + "\n", encoding="utf-8"
    )
    (out / "BOUTS.md").write_text(markdown(sets, rules), encoding="utf-8")
    write_bouts_figure(sets, RESULTS / "figures")
    print(f"{len(sets)} populations written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
