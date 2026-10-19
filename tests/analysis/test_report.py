"""Tests for the evaluation tables and figures."""

from telemetry.analysis.report import (
    SCENARIO_ORDER,
    detection_curve,
    markdown,
    write_figures,
    write_sweep,
)


def report():
    """A minimal evaluation report with one carcass and one other death."""
    result = {
        "deployments": 2,
        "labels": {"dead": 2},
        "animal_months": 4.0,
        "load": {"gap": {"incidents": 4, "late_fix": 2, "per_animal_month": 1.0}},
        "false_mortality": {"incidents": 0, "per_animal_month": 0.0},
        "mortality": {
            "deaths": 1,
            "detected": 1,
            "early": 0,
            "mark_hours": 90.0,
            "rate_at_mark": 1.0,
            "rate_at_mark_200m": 1.0,
        },
        "precision": {
            "mortality": {"true": 1, "false": 9, "ambiguous": 0, "precision": 0.1},
            "likely_death": {
                "true": 1,
                "false": 1,
                "ambiguous": 0,
                "precision": 0.5,
            },
        },
        "likely_death": {"deaths": 1, "detected": 1, "rate_at_mark": 1.0},
        "gap_on_deaths": {"deaths": 1, "detected": 1, "median_delay_hours": 7.0},
        "both_detectors": 1,
        "deaths": [
            {"carcass": True, "mortality_delay_hours": 30.0, "gap_delay_hours": 6.0},
            {"carcass": False, "mortality_delay_hours": None, "gap_delay_hours": 7.0},
        ],
        "ambiguous": [
            {"deployment_id": "B", "still_hours": 40.0, "mortality_delay_hours": None}
        ],
    }
    return {
        "study": "jackals",
        "title": "Jackals",
        "set": "all",
        "mark_hours": 90.0,
        "mark_basis": "test",
        "scenarios": {name: result for name in SCENARIO_ORDER},
    }


def test_detection_curve_steps_up_per_detected_death():
    """Each detected death adds one step; missed deaths cap the curve."""
    xs, ys = detection_curve([10.0, None, 30.0, 500.0], horizon=100.0)
    assert xs == [0.0, 10.0, 30.0, 100.0]
    assert ys == [0.0, 0.25, 0.5, 0.5]


def test_markdown_has_load_deaths_and_ambiguous_sections():
    """The tables show every scenario and the possible unrecorded deaths."""
    text = markdown([report()])
    assert "## Jackals (all set)" in text
    assert "| Ideal | – | 0.00 | – | 1.00 | 50% |" in text
    assert "| B | 40.0 | – |" in text
    assert "| Ideal | – | 50% | 10% | 1 of 1 | 100% |" in text


def test_write_figures_writes_delay_and_load_pngs(tmp_path):
    """Figures are written for a report with deaths, plus the load figure."""
    write_figures([report()], tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "jackals-all-delay.png",
        "load.png",
    ]


def sweep_report():
    """A minimal sweep report: one mortality and one gap row per scenario."""
    rows = []
    for name in SCENARIO_ORDER:
        base = {
            "scenario": name,
            "false_mortality_per_animal_month": 0.5,
            "carcass_deaths": 2,
            "carcass_detected": 1,
            "carcass_rate_at_mark": 0.5,
            "carcass_max_delay_hours": 30.0,
            "gap_per_animal_month": 1.0,
            "gap_late_fix_share": 0.25,
            "other_deaths": 1,
            "other_deaths_detected": 1,
            "other_deaths_median_gap_delay_hours": 12.0,
            "other_deaths_max_gap_delay_hours": 12.0,
        }
        rows.append(
            {
                **base,
                "swept": "mortality",
                "mortality_window_hours": 24.0,
                "mortality_box_m": 100.0,
                "upload_margin_hours": 6.0,
            }
        )
        rows.append(
            {
                **base,
                "swept": "gap",
                "mortality_window_hours": None,
                "mortality_box_m": None,
                "upload_margin_hours": 6.0,
            }
        )
    return {
        "study": "vultures",
        "set": "tuning",
        "deployments": 3,
        "mark_hours": 90.0,
        "rows": rows,
    }


def test_write_sweep_writes_tables_and_figure(tmp_path):
    """The sweep has a row per setting and its figure is written."""
    write_sweep(sweep_report(), tmp_path / "SWEEP.md", tmp_path / "figures")
    text = (tmp_path / "SWEEP.md").read_text(encoding="utf-8")
    assert "| 24 | 100 | 0.50 | 1 of 2 | 50% | 50% | 50% | 30.0 |" in text
    assert "| Satellite, 2-day | 6 | 1.00 | 25% | 1 of 1 | 12.0 | 12.0 |" in text
    assert (tmp_path / "figures" / "sweep-vultures-tuning.png").exists()
