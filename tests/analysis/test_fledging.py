"""Tests for the first-departure split on hand-built tracks."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from telemetry.analysis.evaluation import ALIVE, AMBIGUOUS, DEAD, TUNING, Truth
from telemetry.analysis.fledging import (
    context_split,
    first_departure,
    markdown,
    measure,
)
from telemetry.core.alerts import MORTALITY, NATAL_NEST, Incident
from telemetry.core.fixes import Fix
from telemetry.core.geo import offset

START = datetime(2014, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
MONTH = timedelta(days=30)
NEST = (47.75, 8.93)


def track(deployment_id, nest_hours, away_hours, stray_at=None):
    """Hourly fixes: in the nest, then 5 km away.

    Args:
        deployment_id: The deployment.
        nest_hours: Hours in the nest.
        away_hours: Hours 5 km east afterwards.
        stray_at: Hour of one early fix thrown 5 km off, if any.

    Returns:
        list[Fix]: The track, in time order.
    """
    away = offset(*NEST, 90.0, 5000.0)
    fixes = []
    for hour in range(nest_hours + away_hours):
        lat, lon = NEST if hour < nest_hours and hour != stray_at else away
        fixes.append(Fix(deployment_id, START + hour * HOUR, lat, lon))
    return fixes


def incident(deployment_id, detector, hour):
    """An incident whose evidence is ``hour`` hours after START."""
    opened = START + hour * HOUR
    return Incident(
        f"{deployment_id}:{detector}:{hour}",
        deployment_id,
        detector,
        "open",
        opened,
        "message",
    )


def test_first_departure_is_the_first_fix_beyond_the_radius():
    """The split falls on the first fix away, and a bird that stays has
    none."""
    assert first_departure(track("A", 48, 10), 500.0) == START + 48 * HOUR
    assert first_departure(track("A", 48, 0), 500.0) is None


def test_one_stray_early_fix_does_not_move_the_start():
    """The start is a median, so a stray fix is itself the departure
    rather than shifting the anchor."""
    fixes = track("A", 48, 10, stray_at=3)
    assert first_departure(fixes, 500.0) == START + 3 * HOUR


def test_measure_splits_alerts_and_time_at_departure():
    """Incidents and animal-months land on the side their time falls on;
    a bird that never leaves is all 'before'."""
    fixes = track("A", 240, 480) + track("B", 720, 0)
    incidents = [
        incident("A", "mortality", 30),
        incident("A", "mortality", 300),
        incident("B", "mortality", 700),
        incident("A", "gap", 400),
        incident("A", "movement", 10),
    ]
    result = measure(fixes, incidents, 500.0, MONTH)
    assert (result["birds"], result["never_left"]) == (2, 1)
    assert result["days_to_leave"]["median"] == 10.0
    assert result["detectors"]["mortality"]["before"] == 2
    assert result["detectors"]["mortality"]["after"] == 1
    assert result["detectors"]["mortality"]["share_before"] == 0.667
    assert result["detectors"]["gap"]["after"] == 1
    assert result["detectors"]["potential_death"]["share_before"] is None
    # A: 240 h before and 479 h after; B: 719 h, all before.
    assert result["animal_months_before"] == round((240 + 719) / 720, 1)
    assert result["animal_months_after"] == round(479 / 720, 1)


def test_markdown_has_a_row_per_population_radius_and_alert():
    """The report lists every measured radius and detector, and the
    natal-nest split."""
    result = measure(track("A", 240, 480), [incident("A", "gap", 5)], 500.0, MONTH)
    split = context_split([truth("A", ALIVE)], [], MONTH)
    text = markdown(
        [{"study": "s", "title": "Pop", "radii": [result], "context": split}], "gsm"
    )
    assert "| Pop | 500 | 1 | 0 |" in text
    assert "| Pop | 500 | gap | 1 | 0 |" in text
    assert "`gsm` replay" in text
    assert "| Pop | 0 | 0 | 0.0 | 0.0 | 0 / 0 | 0 / 0 | 0 (0) |" in text


def truth(deployment_id, label, died_at_hour=None):
    """A bird tracked for 30 days, dead from ``died_at_hour`` if given."""
    still = START + (died_at_hour if died_at_hour is not None else 720) * HOUR
    return Truth(
        deployment_id,
        "Ciconia ciconia",
        label,
        TUNING,
        START,
        START + 720 * HOUR,
        still,
        still,
        timedelta(hours=24),
    )


def watch(deployment_id, hour, context=None, resolved_hour=None):
    """A mortality incident opened at ``hour``, optionally resolved."""
    base = incident(deployment_id, MORTALITY, hour)
    return replace(
        base,
        context=context,
        resolved_at=None if resolved_hour is None else START + resolved_hour * HOUR,
    )


def test_context_split_counts_load_and_rightness_on_each_side():
    """Marked alerts are counted apart, true and false on each side, and a
    death alerted only at the nest is counted as the marking's cost."""
    truths = [
        truth("nestling-dead", DEAD, died_at_hour=100),
        truth("adult-dead", DEAD, died_at_hour=400),
        truth("alive", ALIVE),
        truth("unclear", AMBIGUOUS, died_at_hour=10),
    ]
    incidents = [
        watch("nestling-dead", 120, NATAL_NEST),
        watch("adult-dead", 50, NATAL_NEST, resolved_hour=60),
        watch("adult-dead", 420),
        watch("alive", 30, NATAL_NEST, resolved_hour=40),
        watch("alive", 300, resolved_hour=330),
        watch("unclear", 20, NATAL_NEST),
        incident("alive", "gap", 500),
    ]
    split = context_split(truths, incidents, MONTH)
    assert split["animal_months"] == 4.0
    assert split["watch"] == 6 and split["at_natal_nest"] == 4
    assert split["per_animal_month_all"] == 1.5
    assert split["per_animal_month_without_nest"] == 0.5
    assert split["labelled"] == {
        "natal_nest": {"true": 1, "false": 2},
        "other": {"true": 1, "false": 1},
    }
    assert split["deaths_alerted"] == 2 and split["deaths_only_at_nest"] == 1
