"""Tests for the evaluation tables and figures."""

from telemetry.report import SCENARIO_ORDER, detection_curve, markdown, write_figures


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


def test_write_figures_writes_delay_and_load_pngs(tmp_path):
    """Figures are written for a report with deaths, plus the load figure."""
    write_figures([report()], tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "jackals-all-delay.png",
        "load.png",
    ]
