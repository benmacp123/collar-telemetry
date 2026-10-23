"""Score the replayed incidents of every study and scenario.

Run with ``make evaluate`` after ``make replay`` (``make results`` does
both). Reads ``data/raw/``, ``data/labels.csv`` and each
``results/replay/<study>/<scenario>/incidents.jsonl``, and writes
``results/evaluation/<study>-<set>.json``,
``results/evaluation/EVALUATION.md`` and the figures in
``results/figures/``.

The mammals' synthetic-death variants are rebuilt from the same seed as
``make replay`` and scored the same way, with their deaths broken down by
carcass regime; only their deaths are reported, as their load repeats the
real studies'.

The vulture scoring set (deployments from 2013) is first scored only with
``--score``, once thresholds are frozen on the tuning set. After that its
results file exists and every run includes it, so the published tables
stay complete; any later re-score must be declared as such.
"""

import argparse
import json
from pathlib import Path

from telemetry.sim.arrival import SCENARIOS, simulate_arrival
from telemetry.analysis.evaluation import (
    SCORING,
    TUNING,
    build_truth,
    death_timeline,
    evaluate,
    geofence_summary,
    mammal_mark,
    read_incidents,
    read_labels,
    reference_mark,
    score_synthetic,
)
from telemetry.analysis.variants import VARIANTS
from telemetry.analysis.report import (
    write_death_timeline,
    write_figures,
    write_geofence_map,
    write_markdown,
)
from telemetry.data.studies import STUDIES
from telemetry.sim.replay import DEFAULT_SEED

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
RESULTS = ROOT / "results"
EVALUATION = RESULTS / "evaluation"
# The README's worked example: a tuning-set vulture whose carcass kept
# reporting, so it shows the mortality, gap and potential-death alerts and
# how daily uploads delay each one.
TIMELINE_DEATH = "LET_TUVU_68355"
TIMELINE_SCENARIOS = ("ideal", "satellite_daily")
TIMELINE_WINDOW = (-48.0, 168.0)


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


def score_variant(variant, overrides: dict[str, str], vulture_mark: float) -> dict:
    """Score one synthetic variant under every scenario and write its file.

    Args:
        variant: A ``Variant``.
        overrides: Label overrides; none match a synthetic ID, so every
            synthetic deployment is labelled by its ``dead`` end.
        vulture_mark: The vulture reference mark, in hours.

    Returns:
        dict: The variant's report, marked ``synthetic``.
    """
    built = variant.build(RAW, DEFAULT_SEED)
    truths = build_truth(variant.slug, built.deployments, built.fixes, overrides)
    mark = mammal_mark(vulture_mark, truths[0].taxon)
    scenarios = {}
    for scenario in SCENARIOS:
        path = RESULTS / "replay" / variant.slug / scenario / "incidents.jsonl"
        scenarios[scenario] = score_synthetic(
            truths, read_incidents(path), mark, built.deaths
        )
    report = {
        "study": variant.slug,
        "title": variant.title,
        "set": truths[0].split,
        "synthetic": True,
        "seed": DEFAULT_SEED,
        "mark_hours": mark,
        "mark_basis": "own carcass minimum + vulture mark - vulture carcass minimum",
        "scenarios": scenarios,
    }
    out = EVALUATION / f"{variant.slug}-{report['set']}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{variant.slug}: wrote {out.relative_to(ROOT)}")
    return report


def write_timeline(fixes: list, mark: float) -> None:
    """Draw the worked-example death from its replayed incidents.

    Args:
        fixes: The vulture study's fixes.
        mark: The reference mark, in hours.
    """
    own = sorted(
        (f for f in fixes if f.deployment_id == TIMELINE_DEATH),
        key=lambda f: f.timestamp,
    )
    arrivals = {
        name: simulate_arrival(own, SCENARIOS[name], DEFAULT_SEED)
        for name in TIMELINE_SCENARIOS
    }
    incidents = {
        name: read_incidents(RESULTS / "replay" / "vultures" / name / "incidents.jsonl")
        for name in TIMELINE_SCENARIOS
    }
    timeline = death_timeline(own, arrivals, incidents, TIMELINE_WINDOW)
    write_death_timeline(
        timeline,
        mark,
        TIMELINE_WINDOW,
        RESULTS / "figures" / "vultures-death-timeline.png",
    )


def main():
    """Score every study and scenario and write the reports."""
    args = parse_args()
    EVALUATION.mkdir(parents=True, exist_ok=True)
    overrides = read_labels(LABELS)
    reports = []
    vulture_mark = None
    for study in STUDIES:
        deployments, fixes, _ = study.load(RAW)
        fence = study.fence(RAW)
        truths = build_truth(study.slug, deployments, fixes, overrides)
        sets = sorted({t.split for t in truths})
        scored = (EVALUATION / f"{study.slug}-{SCORING}.json").exists()
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
                path = RESULTS / "replay" / study.slug / scenario / "incidents.jsonl"
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
            if TIMELINE_DEATH in {t.deployment_id for t in chosen}:
                write_timeline(fixes, mark)
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
            out = EVALUATION / f"{study.slug}-{name}.json"
            out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            reports.append(report)
            print(f"{study.slug}/{name}: wrote {out.relative_to(ROOT)}")
    for variant in VARIANTS:
        reports.append(score_variant(variant, overrides, vulture_mark))
    write_markdown(reports, EVALUATION / "EVALUATION.md")
    write_figures(reports, RESULTS / "figures")


if __name__ == "__main__":
    main()
