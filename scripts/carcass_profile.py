"""Measure how collars behave on carcasses, for the synthetic deaths.

Run with ``make carcass``. Profiles the vulture tuning set's carcass
deaths with ``telemetry.analysis.carcass`` (fix rate against the collar's
live rate, scatter without repeated positions), adds each study's share of
repeated positions and the mammals' still-window scatter as a check on
transferring the scatter, and writes ``results/carcass/carcass.json``.
The defaults in ``telemetry.sim.synthetic.CarcassConfig`` must match it
(a test checks).
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

from telemetry.analysis.carcass import (
    percentile,
    profile,
    repeat_share,
    still_window_scatter,
)
from telemetry.analysis.evaluation import build_truth, read_labels
from telemetry.data.studies import STUDIES

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LABELS = ROOT / "data" / "labels.csv"
OUT = ROOT / "results" / "carcass" / "carcass.json"


def main():
    """Profile the carcasses and every study's collars, and write the report."""
    report = {"studies": {}}
    for study in STUDIES:
        deployments, fixes, _ = study.load(RAW)
        by_deployment = defaultdict(list)
        for fix in fixes:
            by_deployment[fix.deployment_id].append(fix)
        for own in by_deployment.values():
            own.sort(key=lambda f: f.timestamp)
        shares = [repeat_share(own) for own in by_deployment.values()]
        summary = {
            "deployments": len(by_deployment),
            "repeat_share_median": round(statistics.median(shares), 3),
            "repeat_share_max": round(max(shares), 3),
        }
        if study.slug == "vultures":
            truths = build_truth(study.slug, deployments, fixes, read_labels(LABELS))
            report["vulture_carcasses"] = profile(truths, by_deployment)
        else:
            medians = [
                statistics.median(still)
                for own in by_deployment.values()
                if (still := still_window_scatter(own))
            ]
            summary["still_window_median_m"] = {
                "median": round(statistics.median(medians), 1),
                "p10": round(percentile(medians, 0.1), 1),
                "p90": round(percentile(medians, 0.9), 1),
            }
        report["studies"][study.slug] = summary
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    carcasses = report["vulture_carcasses"]
    print(
        f"{carcasses['carcasses']} carcasses, {carcasses['sparse_share']:.0%} sparse;"
        f" scatter median {carcasses['scatter_median_m']} m,"
        f" p95 {carcasses['scatter_p95_m']} m -> {OUT.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
