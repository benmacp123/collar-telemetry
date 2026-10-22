"""Tests for the departure comparison on hand-built incidents and tracks."""

from datetime import datetime, timedelta, timezone

from telemetry.analysis.departure import (
    _quantile,
    death_outcome,
    false_alarm_hours,
    grid,
    score_real,
    summarise_outcomes,
)
from telemetry.analysis.evaluation import ALIVE, Truth, build_truth
from telemetry.core.alerts import MORTALITY, OPEN, RESOLVED, Incident
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset
from telemetry.core.pipeline import Overrides
from telemetry.sim.arrival import SCENARIOS

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"


def at(hours):
    """The time ``hours`` after START."""
    return START + hours * HOUR


def incident(opened, resolved=None, flaps=0, deployment_id="A"):
    """A mortality incident opened and resolved at the given hours."""
    return Incident(
        f"{deployment_id}:{MORTALITY}:{opened}",
        deployment_id,
        MORTALITY,
        RESOLVED if resolved is not None else OPEN,
        at(opened),
        "",
        at(resolved) if resolved is not None else None,
        flaps=flaps,
    )


def scattered_carcass():
    """A jackal that walks for 5 days, then lies dead for 60 h.

    The carcass fixes sit within a few metres of one point, except one
    55 m north and then two 55 m south: the box grows past 100 m though no
    fix is more than 55 m from the carcass.
    """
    deployment = Deployment("A", "tag", "A", JACKAL, START, None, "dead")
    lat, lon = -19.0, 15.5
    fixes = []
    for i in range(120):
        lat, lon = offset(lat, lon, 0.0, 300.0)
        fixes.append(Fix("A", at(i), lat, lon))
    strays = {30: (0.0, 55.0), 31: (180.0, 55.0), 32: (180.0, 55.0)}
    for i in range(60):
        bearing, distance = strays.get(i, (90.0 if i % 2 else 270.0, 3.0))
        fixes.append(Fix("A", at(120 + i), *offset(lat, lon, bearing, distance)))
    return [deployment], fixes


def test_grid_compares_against_the_box_only_detector():
    """Every non-radius row drops the radius; the default row is the default."""
    points = dict(grid())
    assert len(points) == 9
    assert points["radius 75 m (default)"] == Overrides()
    for label, overrides in points.items():
        assert overrides.mortality_box_only == (not label.startswith("radius"))


def test_death_outcome_counts_only_incidents_open_after_the_death():
    """An alert resolved before the death is not part of the death."""
    incidents = [incident(0, 10), incident(20, 40, flaps=2), incident(50)]
    assert death_outcome(at(15), incidents) == {
        "incidents": 2,
        "flaps": 2,
        "ends_resolved": False,
    }


def test_death_outcome_ends_resolved_when_the_last_incident_closed():
    """A death whose last incident resolved reads as a carcass that moved."""
    outcome = death_outcome(at(5), [incident(10, 30)])
    assert outcome["ends_resolved"] and outcome["incidents"] == 1


def test_summarise_outcomes_counts_each_kind():
    """Missed, split, flapped and ended-resolved deaths are counted apart."""
    outcomes = [
        {"incidents": 0, "flaps": 0, "ends_resolved": False},
        {"incidents": 2, "flaps": 1, "ends_resolved": False},
        {"incidents": 1, "flaps": 3, "ends_resolved": True},
    ]
    assert summarise_outcomes(outcomes) == {
        "deaths": 3,
        "missed": 1,
        "split": 1,
        "flapped": 2,
        "flaps": 4,
        "ends_resolved": 1,
    }


def test_false_alarm_hours_measures_alerts_on_living_animals():
    """Durations come from resolved false alerts; open ones are counted."""
    truth = Truth(
        "A", JACKAL, ALIVE, "all", at(0), at(500), at(500), at(500), 24 * HOUR
    )
    incidents = [incident(0, 10), incident(20, 50, flaps=1), incident(100)]
    assert false_alarm_hours([truth], incidents) == {
        "incidents": 3,
        "never_resolved": 1,
        "flaps": 1,
        "median_hours_open": 10.0,
        "p90_hours_open": 30.0,
    }


def test_quantile_is_nearest_rank():
    """The median of four values is the second; an empty list has none."""
    assert _quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.0
    assert _quantile([1.0, 2.0, 3.0, 4.0], 0.9) == 4.0
    assert _quantile([], 0.5) is None


def test_radius_removes_the_flap_the_box_raises_on_a_carcass():
    """The box-only detector flaps on the scattered carcass; the default does not."""
    deployments, fixes = scattered_carcass()
    truths = build_truth("jackals", deployments, fixes, {})
    rows = {
        label: score_real(
            deployments, fixes, truths, SCENARIOS["ideal"], overrides, 90.0
        )
        for label, overrides in (
            ("box", Overrides(mortality_box_only=True)),
            ("default", Overrides()),
        )
    }
    assert rows["box"]["mortality"]["carcass"]["flapped"] == 1
    assert rows["default"]["mortality"]["carcass"]["flapped"] == 0
    for row in rows.values():
        assert row["carcass"]["detected"] == 1
        assert row["mortality"]["carcass"]["split"] == 0
