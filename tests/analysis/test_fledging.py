"""Tests for the first-departure split on hand-built tracks."""

from datetime import datetime, timedelta, timezone

from telemetry.analysis.fledging import first_departure, markdown, measure
from telemetry.core.alerts import Incident
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
    """The report lists every measured radius and detector."""
    result = measure(track("A", 240, 480), [incident("A", "gap", 5)], 500.0, MONTH)
    text = markdown([{"study": "s", "title": "Pop", "radii": [result]}], "gsm")
    assert "| Pop | 500 | 1 | 0 |" in text
    assert "| Pop | 500 | gap | 1 | 0 |" in text
    assert "`gsm` replay" in text
