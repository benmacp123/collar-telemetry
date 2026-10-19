"""Score the replayed incidents of every study and scenario.

Run with ``make evaluate`` after ``make replay`` (``make results`` does
both). Reads ``data/raw/``, ``data/labels.csv`` and each
``results/<study>/<scenario>/incidents.jsonl``, and writes
``results/<study>/evaluation-<set>.json``, ``results/EVALUATION.md`` and
the figures in ``results/figures/``.

The vulture scoring set (deployments from 2013) is first scored only with
``--score``, once thresholds are frozen on the tuning set. After that its
results file exists and every run includes it, so the published tables
stay complete; any later re-score must be declared as such.
"""

import argparse
import json
from pathlib import Path

from telemetry.arrival import SCENARIOS
from telemetry.evaluation import (
    CARCASS_MIN,
    HOUR,
    SCORING,
    TUNING,
    build_truth,
    evaluate,
    geofence_summary,
    read_incidents,
    read_labels,
    reference_mark,
)
from telemetry.report import write_figures, write_geofence_map, write_markdown
from telemetry.studies import STUDIES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"
VULTURE_TAXON = "Cathartes aura"


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``score``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--score",
        action="store_true",
        help="also score the vulture scoring set (only once thresholds are frozen)",
    )
    return parser.parse_args()


def mammal_mark(vulture_mark: float, taxon: str) -> float:
    """Reference deadline for a species with no observed carcass periods.

    Carried from vultures: the species' carcass minimum plus the time the
    vulture mark leaves after the vulture carcass minimum.

    Args:
        vulture_mark: The vulture reference mark, in hours.
        taxon: The species.

    Returns:
        float: The mark, in hours.
    """
    vulture_min = CARCASS_MIN[VULTURE_TAXON] / HOUR
    return round(CARCASS_MIN[taxon] / HOUR + vulture_mark - vulture_min, 1)


def main():
    """Score every study and scenario and write the reports."""
    args = parse_args()
    overrides = read_labels(LABELS)
    reports = []
    vulture_mark = None
    for study in STUDIES:
        deployments, fixes, _ = study.load(RAW)
        fence = study.fence(RAW)
        truths = build_truth(study.slug, deployments, fixes, overrides)
        sets = sorted({t.split for t in truths})
        scored = (RESULTS / study.slug / f"evaluation-{SCORING}.json").exists()
        if not (args.score or scored):
            sets = [s for s in sets if s != SCORING]
        taxon = truths[0].taxon
        if study.slug == "vultures":
            # The mark is observed on the tuning set only, so scoring
            # deaths never shape it.
            vulture_mark = reference_mark([t for t in truths if t.split == TUNING])
            mark = vulture_mark
        else:
            mark = mammal_mark(vulture_mark, taxon)
        for name in sets:
            chosen = [t for t in truths if t.split == name]
            scenarios = {}
            for scenario in SCENARIOS:
                path = RESULTS / study.slug / scenario / "incidents.jsonl"
                incidents = read_incidents(path)
                scenarios[scenario] = evaluate(chosen, incidents, mark)
                if fence is not None:
                    scenarios[scenario]["geofence"] = geofence_summary(
                        chosen, incidents, fixes, fence
                    )
                    # Crossings do not depend on upload timing, so one map
                    # (ideal arrival) covers every scenario.
                    if (
                        scenario == "ideal"
                        and scenarios[scenario]["geofence"]["incidents"]
                    ):
                        write_geofence_map(
                            fence,
                            fixes,
                            incidents,
                            RESULTS / "figures" / f"{study.slug}-geofence-map.png",
                        )
            report = {
                "study": study.slug,
                "title": study.title,
                "set": name,
                "mark_hours": mark,
                "mark_basis": (
                    "median tuning-set carcass period"
                    if study.slug == "vultures"
                    else "own carcass minimum + vulture mark - vulture carcass minimum"
                ),
                "scenarios": scenarios,
            }
            out = RESULTS / study.slug / f"evaluation-{name}.json"
            out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            reports.append(report)
            print(f"{study.slug}/{name}: wrote {out.relative_to(ROOT)}")
    write_markdown(reports, RESULTS / "EVALUATION.md")
    write_figures(reports, RESULTS / "figures")


if __name__ == "__main__":
    main()
