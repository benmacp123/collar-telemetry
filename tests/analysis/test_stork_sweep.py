"""Tests for the white-stork window sweep and its decision rule."""

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telemetry.analysis.evaluation import ALIVE, TUNING, Truth
from telemetry.analysis.experiment import experiment
from telemetry.analysis.stork_sweep import (
    grid,
    markdown,
    meets,
    population_row,
    stork_choice,
)
from telemetry.core.alerts import MORTALITY, NATAL_NEST, Incident
from telemetry.core.species import profile_for

START = datetime(2014, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
STORK = "Ciconia ciconia"
STORKS_JSON = Path(__file__).resolve().parents[2] / "results/sweep/storks-tuning.json"


def truth(deployment_id, days=30.4375):
    """A living stork tracked for ``days`` days (one animal-month by default)."""
    end = START + timedelta(days=days)
    return Truth(
        deployment_id, STORK, ALIVE, TUNING, START, end, end, end, timedelta(hours=24)
    )


def watch(deployment_id, hour, open_hours, context=None):
    """A false watch alert opened at ``hour`` that clears ``open_hours`` later."""
    opened = START + hour * HOUR
    base = Incident(
        f"{deployment_id}:{hour}", deployment_id, MORTALITY, "open", opened, "message"
    )
    return replace(base, context=context, resolved_at=opened + open_hours * HOUR)


def point(window, *rows):
    """A sweep point with one population row per (load, clear) pair."""
    return {
        "window_hours": window,
        "populations": {
            f"pop{i}": {"load_chosen": load, "clear_median_hours": clear}
            for i, (load, clear) in enumerate(rows)
        },
    }


def test_grid_sweeps_only_the_stork_window():
    """Each setting changes the stork window alone, one per listed window."""
    settings = grid()
    assert [dict(o.species_windows)[STORK] for o in settings] == list(
        experiment().stork_windows
    )
    assert all(
        o.mortality_window is None and o.mortality_box_m is None for o in settings
    )


def test_load_leaves_out_natal_nest_alerts_but_clear_time_keeps_them():
    """Marked alerts drop out of the chosen load only; clear time counts all."""
    incidents = [
        watch("A", 10, 4, context=NATAL_NEST),
        watch("A", 100, 20, context=NATAL_NEST),
        watch("A", 300, 6),
    ]
    row = population_row([truth("A")], incidents, None)
    assert (row["watch"], row["chosen"]) == (3, 1)
    assert row["load_all"] == 3.0
    assert row["load_chosen"] == 1.0
    assert row["false"] == 3
    assert row["clear_median_hours"] == 6.0


def test_load_interval_resamples_birds():
    """Two birds with different loads give an interval spanning both."""
    incidents = [watch("A", h, 2) for h in (10, 50, 90, 130)]
    row = population_row([truth("A"), truth("B")], incidents, None)
    assert row["load_chosen"] == 2.0
    low, high = row["load_chosen_by_bird"]
    assert low == 0.0 and high == 4.0


def test_rule_takes_the_shortest_window_every_population_meets():
    """A window one population misses is passed over for a longer one."""
    points = [
        point(48.0, (0.30, 10.0), (0.20, 11.0)),
        # The second population misses load here.
        point(24.0, (0.41, 8.0), (0.50, 9.0)),
        point(36.0, (0.35, 9.0), (0.30, 10.0)),
    ]
    assert stork_choice(points) == 36.0


def test_rule_finds_no_window_when_a_population_never_meets_both():
    """No choice when each window misses on some population or target."""
    points = [
        point(24.0, (0.30, 13.0), (0.20, 8.0)),
        point(48.0, (0.30, 8.0), (0.50, 8.0)),
    ]
    assert stork_choice(points) is None


def test_rule_needs_a_measured_clear_time():
    """A population with no cleared false alerts cannot meet the clear target."""
    assert not meets({"load_chosen": 0.1, "clear_median_hours": None})
    assert stork_choice([point(24.0, (0.1, None))]) is None


def test_markdown_states_the_rule_and_a_missed_outcome():
    """With no choice the report says the window stays 24 h."""
    row = population_row([truth("A")], [watch("A", 10, 30)], None)
    text = markdown(
        {
            "scenario": "gsm",
            "mark_hours": 80.0,
            "populations": {"pop": "White stork, Somewhere"},
            "points": [{"window_hours": 24.0, "populations": {"pop": row}}],
            "choice": None,
        }
    )
    assert "`natal_nest` left out" in text
    assert "**stays 24 h**" in text
    assert "| 24 | 1.000 (1.000-1.000) | 1.000 | 1 | 30.0 | 0 |" in text


@pytest.mark.skipif(not STORKS_JSON.exists(), reason="stork sweep not run")
def test_core_runs_the_window_the_committed_stork_sweep_chose():
    """The stork window in core is the rule's choice on the committed sweep,
    or 24 h when no window meets the rule."""
    report = json.loads(STORKS_JSON.read_text(encoding="utf-8"))
    choice = stork_choice(report["points"])
    window = profile_for(experiment().stork_taxon).mortality.window
    assert window == HOUR * (24.0 if choice is None else choice)
