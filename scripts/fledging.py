"""Measure the alert load before and after storks first leave the nest.

Run with ``make fledging``, after ``make replay``. Uses the stork tuning
populations only, under the scenario the experiment file judges storks
on, and writes ``results/fledging/fledging.json`` and
``results/fledging/FLEDGING.md``.
"""

import json
from pathlib import Path

from telemetry.analysis.evaluation import read_incidents
from telemetry.analysis.experiment import experiment
from telemetry.analysis.fledging import RADII_M, markdown, measure
from telemetry.data.studies import STORK_GROUP, tuning_storks

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
RESULTS = ROOT / "results"


def main():
    """Measure each tuning population and write the results."""
    settings = experiment()
    scenario = settings.scenario(STORK_GROUP)
    sets = []
    # Held-out populations are not in this list, so their files are never
    # opened.
    for study in tuning_storks():
        _, fixes, _ = study.load(RAW)
        incidents = read_incidents(
            RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
        )
        sets.append(
            {
                "study": study.slug,
                "title": study.title,
                "radii": [
                    measure(fixes, incidents, radius, settings.animal_month)
                    for radius in RADII_M
                ],
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
