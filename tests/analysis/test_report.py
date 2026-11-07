"""Tests for the evaluation tables and figures."""

from telemetry.analysis import report as report_module
from telemetry.analysis.report import (
    SCENARIO_ORDER,
    SYNTHETIC_GROUPS,
    detection_curve,
    look_markdown,
    markdown,
    write_death_timeline,
    write_figures,
    write_sweep,
)


def report():
    """A minimal evaluation report with one carcass and one other death."""
    result = {
        "deployments": 2,
        "labels": {"dead": 2},
        "animal_months": 4.0,
        "load": {
            "gap": {
                "incidents": 4,
                "late_fix": 2,
                "per_animal_month": 1.0,
                "late_fix_per_animal_month": 0.5,
            }
        },
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
            "potential_death": {
                "true": 1,
                "false": 1,
                "ambiguous": 0,
                "precision": 0.5,
            },
        },
        "potential_death": {"deaths": 1, "detected": 1, "rate_at_mark": 1.0},
        "first_alert": {
            "deaths": 1,
            "detected": 1,
            "rate_at_mark": 1.0,
            "median_delay_hours": 30.0,
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


def synthetic_report():
    """A minimal synthetic variant report: one death in each regime."""
    group = {
        "deaths": 1,
        "carcass": 1,
        "mortality": {
            "detected": 1,
            "detected_injected": 1,
            "early": 0,
            "rate_at_mark": 1.0,
            "rate_at_mark_injected": 1.0,
            "median_delay_hours": 20.0,
            "median_delay_hours_injected": 21.0,
        },
        "potential_death": {
            "detected": 0,
            "detected_injected": 0,
            "rate_at_mark": 0.0,
            "rate_at_mark_injected": 0.0,
            "median_delay_hours": None,
            "median_delay_hours_injected": None,
        },
        "first_alert": {
            "detected": 1,
            "detected_injected": 1,
            "rate_at_mark": 1.0,
            "rate_at_mark_injected": 0.5,
            "median_delay_hours": 20.0,
            "median_delay_hours_injected": 21.0,
        },
        "death_start_offset_hours": {
            "exact": 1,
            "earlier": 0,
            "later": 0,
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
        },
    }
    result = {
        "load": {"mortality": {"incidents": 2, "per_animal_month": 9.0}},
        "deaths": [
            {"carcass": True, "regime": regime, "mortality_delay_hours": 20.0}
            for regime in ("reporting", "sparse")
        ],
        "synthetic": {name: group for name in SYNTHETIC_GROUPS},
    }
    return {
        "study": "jackals-synthetic",
        "title": "Jackals, synthetic deaths",
        "set": "all",
        "synthetic": True,
        "seed": 2026,
        "mark_hours": 90.0,
        "mark_basis": "test",
        "scenarios": {name: result for name in SCENARIO_ORDER},
    }


def test_markdown_synthetic_section_shows_regimes_and_injected_delays():
    """A synthetic variant gets its deaths table by regime, not a load table."""
    text = markdown([report(), synthetic_report()])
    section = text.split("## Jackals, synthetic deaths")[1]
    assert "| Ideal | Sparse | 1 | 1 | 0 | 100% (100%) | 20.0 (21.0) | 0 |" in section
    assert "| 0% (0%) | 100% (50%) |" in section
    assert "Operator load" not in section
    assert "exact for 1" in section


def test_write_figures_keeps_synthetic_variants_off_the_load_figure(
    tmp_path, monkeypatch
):
    """A synthetic variant gets a delay figure but no load panel of its own."""
    panels = []
    real_load_figure = report_module._load_figure

    def spy(pyplot, reports):
        """Record which reports reach the load figure."""
        panels.extend(r["study"] for r in reports)
        return real_load_figure(pyplot, reports)

    monkeypatch.setattr(report_module, "_load_figure", spy)
    write_figures([report(), synthetic_report()], tmp_path)
    assert panels == ["jackals"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "jackals-all-delay.png",
        "jackals-synthetic-all-delay.png",
        "load.png",
    ]


def test_detection_curve_steps_up_per_detected_death():
    """Each detected death adds one step; missed deaths cap the curve."""
    xs, ys = detection_curve([10.0, None, 30.0, 500.0], horizon=100.0)
    assert xs == [0.0, 10.0, 30.0, 100.0]
    assert ys == [0.0, 0.25, 0.5, 0.5]


def test_markdown_has_load_deaths_and_ambiguous_sections():
    """The tables show every scenario, the late-upload gap rate and the
    possible unrecorded deaths."""
    text = markdown([report()])
    assert "## Jackals (all set)" in text
    assert "| Ideal | – | 0.00 | – | 1.00 | 0.50 | 50% | – |" in text
    assert "| B | 40.0 | – |" in text
    assert "| Ideal | – | 50% | 10% | 1 of 1 | 100% |" in text


def test_look_markdown_is_one_entry_with_a_row_per_scenario():
    """A look-log entry carries its date, commit and reason, then each
    scenario's headline figures, so looks compare line by line."""
    text = look_markdown(report(), "2026-10-30", "abc1234", "Tier field added.")
    lines = text.splitlines()
    assert lines[0] == "## 2026-10-30, abc1234"
    assert sum(line.startswith("## ") for line in lines) == 1
    assert "Tier field added." in lines
    assert "| Ideal | 1 + 0 / 9 | 10.0% | – | 0.000 | 1 of 1 | 1 / 1 | 50.0% |" in lines
    assert len([line for line in lines if line.startswith("| ")]) == 1 + len(
        SCENARIO_ORDER
    )


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
            "mortality_true": 1,
            "mortality_tag_event": 2,
            "mortality_death_precision": 0.1,
            "random_precision_tags": 0.02,
            "mortality_judged": 10,
            "mortality_precision": 0.1,
            "mortality_wilson": [0.0179, 0.4042],
            "mortality_bootstrap": [0.0, 0.25],
            "mortality_ceiling": 0.1818,
            "potential_death_precision": 0.5,
            "gap_precision": 0.04,
            "random_precision": 0.0015,
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
    assert "| Satellite, 2-day | 6 | 1.00 | 25% | 1 of 1 | 12.0 | 12.0 | 4.0% |" in text
    assert (
        "| 24 | 100 | 1 + 2 / 10 | 10.0% | 10.0% | 1.8-40.4% | 0.0-25.0% | 18.2% "
        "| 50.0% "
        "| 4.0% |" in text
    )
    assert "Random alerts score 0.15% for deaths, 2.00% also crediting" in text
    assert (tmp_path / "figures" / "sweep-vultures-tuning.png").exists()


def test_markdown_deaths_table_shows_any_alert_rate():
    """The deaths table carries the first-alert rate beside mortality's."""
    text = markdown([report()])
    assert "| Ideal | 1 | 1 | 100% | 100% | 100% | 1 (1 flagged) | 7.0 | 1 |" in text


def test_write_death_timeline_writes_png(tmp_path):
    """The death timeline draws a panel per scenario and saves the PNG."""
    timeline = {
        "deployment_id": "A",
        "still_hours": 60.0,
        "fixes": [[-10.0, 2000.0], [0.0, 0.0], [30.0, 15.0]],
        "scenarios": {
            name: {
                "arrivals": [-10.0, 0.0, 30.0],
                "incidents": [
                    {"detector": "mortality", "raised": 36.0, "resolved": None},
                    {"detector": "gap", "raised": -20.0, "resolved": 5.0},
                ],
            }
            for name in ("satellite_daily", "ideal")
        },
    }
    path = tmp_path / "timeline.png"
    write_death_timeline(timeline, 92.5, (-48.0, 168.0), path)
    assert path.stat().st_size > 0


def scored_report():
    """The minimal report with the precision fields ``evaluate`` now adds."""
    full = report()
    for result in full["scenarios"].values():
        for detector, cases in (("mortality", 1), ("potential_death", 1), ("gap", 2)):
            result["precision"].setdefault(
                detector, {"true": 1, "false": 1, "ambiguous": 0, "precision": 0.5}
            )
            result["precision"][detector].update(
                judged=result["precision"][detector]["true"]
                + result["precision"][detector]["false"],
                wilson=[0.014403, 0.066490],
                bootstrap=[0.0099, 0.0813],
                cases=cases,
                ceiling=0.0262,
            )
        result["random_precision"] = 0.0015
        result["false_mortality_by"] = {
            "by_taxon": [
                {
                    "name": "Canis mesomelas",
                    "animal_months": 4.0,
                    "true": 1,
                    "false": 9,
                    "false_per_animal_month": 2.25,
                }
            ],
            "by_deployment": [
                {
                    "name": "A",
                    "animal_months": 2.0,
                    "true": 1,
                    "false": 9,
                    "false_per_animal_month": 4.5,
                }
            ],
        }
    return full


def test_markdown_precision_section_shows_intervals_ceiling_and_baselines():
    """Each scenario lists mortality, potential death and the gap baseline
    with both intervals and the ceiling, then the random baseline."""
    text = markdown([scored_report()])
    assert "### Precision against the ceiling and baselines" in text
    assert (
        "| Ideal | Mortality | 1 + 0 / 10 (0) | 10.0% | 10.0% | 1.4-6.6% | 1.0-8.1% | 1 "
        "| 2.6% |" in text
    )
    assert "| Ideal | Gap only (baseline) | 1 + 0 / 2 (0) | 50.0% |" in text
    assert "Random baseline (any scenario): 0.15% for deaths" in text
    assert "| Canis mesomelas | 4.0 | 1 | 9 | 2.25 |" in text
    assert "| A | 2.0 | 1 | 9 | 4.50 |" in text


def test_markdown_skips_precision_sections_for_a_report_without_them():
    """A held-out report scored before intervals existed still renders,
    without the new sections, so a routine run needs no rescore."""
    text = markdown([report()])
    assert "### Precision against the ceiling" not in text
    assert "### False mortality alerts by species" not in text


def test_look_markdown_carries_intervals_and_ceiling():
    """A look-log row quotes the precision with both intervals and the
    ceiling, so a look cannot be read without its uncertainty."""
    text = look_markdown(scored_report(), "2026-10-31", "abc1234", "Intervals.")
    assert (
        "| Ideal | 1 + 0 / 9 | 10.0% [1.4-6.6%; by bird 1.0-8.1%] | 2.6% | 0.000 "
        "| 1 of 1 | 1 / 1 | 50.0% |" in text.splitlines()
    )


def test_markdown_lists_tag_events_and_their_credit():
    """A set with tag events shows each one's start and credited alerts."""
    report = scored_report()
    for result in report["scenarios"].values():
        result["tag_events"] = [
            {
                "deployment_id": "EAX",
                "event_from": "2015-05-31T21:00:00+00:00",
                "mortality_incidents": 4,
            }
        ]
    text = markdown([report])
    assert "### Tag events" in text
    assert "| EAX | 2015-05-31T21:00 | 4 |" in text


def test_look_shows_escalated_tag_events_as_wrong():
    """A tag event on the escalated tier is logged among its wrong alerts."""
    scored = scored_report()
    for result in scored["scenarios"].values():
        result["precision"]["potential_death"]["tag-event"] = 2
    text = look_markdown(scored, "2026-11-07", "abc1234", "Tag events.")
    assert "| 1 of 1 | 1 / 3 | 50.0% |" in text
