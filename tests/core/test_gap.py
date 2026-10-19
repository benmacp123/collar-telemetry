"""Tests for the data-gap detector.

Includes the overnight duty cycle of the older vulture tags.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.core.detectors.gap import (
    GapConfig,
    GapDetector,
    active_hours,
    active_silence,
)
from telemetry.core.fixes import Fix
from telemetry.core.stream import FixStream

START = datetime(2007, 4, 5, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def at(hours):
    """The time ``hours`` after START."""
    return START + hours * HOUR


def fixes(hours):
    """Fixes for deployment A at each of ``hours`` after START."""
    return [Fix("A", at(h), 30.5, -86.5) for h in hours]


def duty_cycled(days):
    """Hourly fixes, off 03:00-08:00 UTC like the older vulture tags."""
    return [h for h in range(days * 24) if not 3 <= h % 24 < 8]


def feed(detector, state, items):
    """Give each fix to the detector; return any alerts."""
    alerts = []
    for f in items:
        alerts += detector.on_fix(state, "A", f)
    return alerts


def ticks(detector, state, start_hour, end_hour, step=1.0):
    """Tick the detector from ``start_hour`` to ``end_hour``; return any alerts."""
    alerts = []
    hour = start_hour
    while hour <= end_hour:
        alerts += detector.on_tick(state, "A", at(hour))
        hour += step
    return alerts


def test_active_hours():
    """Hours with at least the given share of the peak are active."""
    weights = [0.0] * 24
    weights[10], weights[11], weights[12] = 10.0, 3.0, 2.0
    assert active_hours(weights, 0.25) == {10, 11}
    assert active_hours([0.0] * 24, 0.25) == set()


def test_active_silence_skips_off_hours():
    """Silence is counted only in active hours, including part hours."""
    hours = set(range(24)) - set(range(3, 8))
    # 02:30 to 09:15 is 6 h 45 min, of which 03:00-08:00 is off.
    silence = active_silence(
        START + timedelta(hours=2, minutes=30),
        START + timedelta(hours=9, minutes=15),
        hours,
        limit=timedelta(days=1),
    )
    assert silence == timedelta(hours=1, minutes=45)


def test_active_silence_stops_at_the_limit():
    """Counting stops at the limit, so month-long silences stay cheap."""
    silence = active_silence(at(0), at(1000), set(range(24)), limit=6 * HOUR)
    assert silence == 6 * HOUR


def test_nightly_switch_off_is_not_a_gap():
    """Ten days of an overnight switch-off raise no alerts."""
    detector, state = GapDetector(GapConfig(min_silence=3 * HOUR)), {}
    alerts = []
    for f in fixes(duty_cycled(10)):
        alerts += detector.on_fix(state, "A", f)
        alerts += detector.on_tick(state, "A", f.timestamp + 0.5 * HOUR)
    alerts += ticks(detector, state, 9 * 24 + 3, 9 * 24 + 8)  # through the night
    assert not alerts


def test_silence_in_active_hours_alerts_once():
    """A real silence raises one alert, not one per tick."""
    detector, state = GapDetector(GapConfig(min_silence=3 * HOUR)), {}
    feed(detector, state, fixes(duty_cycled(5)))
    last = duty_cycled(5)[-1]
    alerts = ticks(detector, state, last, last + 48)
    assert len(alerts) == 1
    # 3 h of active time after the last fix at 23:00 runs into the off
    # period at 03:00, so the alert waits until the collar should be on.
    assert alerts[0].time == at(last + 3)
    assert "usually every 60 min" in alerts[0].message


def test_silence_through_off_hours_alerts_after_they_end():
    """Off hours do not count, so the alert comes later in wall-clock time."""
    detector, state = GapDetector(GapConfig(min_silence=3 * HOUR)), {}
    days = duty_cycled(5)
    feed(detector, state, fixes(h for h in days if h <= 4 * 24 + 2))  # last 02:00
    alerts = ticks(detector, state, 4 * 24 + 2, 4 * 24 + 24)
    # One active hour (02:00-03:00), off until 08:00, then two more.
    assert [alert.time for alert in alerts] == [at(4 * 24 + 10)]


def test_a_new_fix_rearms_the_detector():
    """After a fix arrives, the next silence can alert again."""
    detector, state = GapDetector(GapConfig(min_silence=3 * HOUR)), {}
    feed(detector, state, fixes(range(96)))
    assert len(ticks(detector, state, 96, 110)) == 1
    feed(detector, state, fixes([111]))
    assert len(ticks(detector, state, 111, 130)) == 1


def test_the_next_fix_resolves_an_open_gap():
    """A fix after an alerted silence resolves it, at the fix's time."""
    detector, state = GapDetector(GapConfig(min_silence=3 * HOUR)), {}
    feed(detector, state, fixes(range(96)))
    ticks(detector, state, 97, 110)
    resolved = feed(detector, state, fixes([111]))
    assert [(a.status, a.reason, a.time) for a in resolved] == [
        ("resolved", "fix_received", at(111))
    ]


def test_fixes_without_an_open_gap_resolve_nothing():
    """Ordinary fixes produce no transitions."""
    detector, state = GapDetector(), {}
    assert not feed(detector, state, fixes(range(96)))


def test_min_silence_holds_back_fast_tags():
    """A 1-minute tag silent for 30 min is not worth an alert."""
    detector, state = GapDetector(GapConfig(min_silence=6 * HOUR)), {}
    minutes = [
        Fix("A", START + timedelta(minutes=m), 30.5, -86.5) for m in range(0, 5 * 1440)
    ]
    feed(detector, state, minutes)
    last = minutes[-1].timestamp
    assert not detector.on_tick(state, "A", last + timedelta(minutes=30))
    assert detector.on_tick(state, "A", last + 6 * HOUR)


def test_no_alert_during_warmup():
    """No alert until the schedule has been watched for the warm-up period."""
    detector, state = (
        GapDetector(GapConfig(min_silence=HOUR, warmup=timedelta(days=3))),
        {},
    )
    feed(detector, state, fixes(range(24)))
    assert not ticks(detector, state, 24, 70)
    assert ticks(detector, state, 72, 72)


def test_no_alert_before_any_interval_is_known():
    """With fewer than two fixes there is no expected interval, so no alert."""
    detector, state = GapDetector(), {}
    assert not detector.on_tick(state, "A", at(1000))
    feed(detector, state, fixes([0]))
    assert not detector.on_tick(state, "A", at(1000))


def test_expected_interval_follows_a_schedule_change():
    """Like jackal CM40: hourly, then every 10 minutes."""
    detector, state = GapDetector(GapConfig(factor=3, min_silence=timedelta(0))), {}
    feed(detector, state, fixes(range(96)))
    ten_minutes = [
        Fix("A", at(96) + timedelta(minutes=10 * i), 30.5, -86.5) for i in range(1, 60)
    ]
    feed(detector, state, ten_minutes)
    last = ten_minutes[-1].timestamp
    assert not detector.on_tick(state, "A", last + timedelta(minutes=29))
    assert detector.on_tick(state, "A", last + timedelta(minutes=31))


def test_out_of_order_fix_does_not_count_as_an_interval():
    """Zero or negative intervals are not learned."""
    detector, state = GapDetector(), {}
    feed(detector, state, fixes([0, 1, 2, 2]))
    assert state["intervals"] == [60.0, 60.0]


@pytest.mark.parametrize("split", [10, 50, 100])
def test_state_round_trips_through_json_in_a_stream(split):
    """Saving and resuming at any point gives the same alerts as an unbroken run."""
    items = fixes(duty_cycled(6))
    tick_hours = range(6 * 24, 6 * 24 + 30)

    def run(stream, part):
        return [alert for f in part for alert in stream.ingest(f)]

    whole = FixStream([GapDetector(GapConfig(min_silence=3 * HOUR))])
    run(whole, items)
    expected = [a for h in tick_hours for a in whole.tick(at(h))]

    first = FixStream([GapDetector(GapConfig(min_silence=3 * HOUR))])
    run(first, items[:split])
    resumed = FixStream.from_dict(
        json.loads(json.dumps(first.to_dict())),
        [GapDetector(GapConfig(min_silence=3 * HOUR))],
    )
    run(resumed, items[split:])
    assert [a for h in tick_hours for a in resumed.tick(at(h))] == expected
    assert len(expected) == 1


def burst(days, start_hour=14, length=5):
    """One fix a minute for ``length`` hours a day from ``start_hour``."""
    return [
        Fix("A", at(d * 24 + start_hour) + timedelta(minutes=m), 30.5, -86.5)
        for d in range(days)
        for m in range(length * 60)
    ]


def test_each_clock_hour_counts_once_for_active_hours():
    """Sixty fixes in one hour weigh the same as one fix in another."""
    detector = GapDetector()
    state = {}
    feed(detector, state, fixes([0]))
    feed(
        detector,
        state,
        [Fix("A", at(1) + timedelta(minutes=m), 30.5, -86.5) for m in range(60)],
    )
    assert state["weights"][0] == pytest.approx(state["weights"][1], rel=0.01)


def test_burst_tag_active_through_its_whole_burst():
    """A 1-min burst tag counts every hour of its daily burst as active."""
    detector = GapDetector()
    state = {}
    feed(detector, state, burst(5))
    assert active_hours(state["weights"], 0.25) == set(range(14, 19))


def test_allowance_runs_on_the_clock_not_active_hours():
    """A burst tag alerts once the clock allowance has passed and its
    normal hours have been silent for min_silence, not after the
    allowance counted in active hours (days later)."""
    config = GapConfig(allowance=timedelta(hours=48))
    detector = GapDetector(config)
    state = {}
    feed(detector, state, burst(5))
    last = burst(5)[-1].timestamp
    alerts = []
    hour = 0
    while not alerts and hour < 24 * 10:
        hour += 1
        alerts = detector.on_tick(state, "A", last + hour * HOUR)
    # 48 h on the clock, then 6 h of the 14:00-19:00 burst window: about
    # three days, where counting 48 h of active hours would take ten.
    assert last + 48 * HOUR <= alerts[0].time <= last + 80 * HOUR


def test_no_alert_within_allowance_even_if_active_hours_silent():
    """Silence shorter than the allowance never alerts."""
    detector = GapDetector(GapConfig(allowance=timedelta(hours=30)))
    state = {}
    feed(detector, state, fixes(range(24 * 5)))
    assert ticks(detector, state, 24 * 5, 24 * 5 + 28) == []
    assert len(ticks(detector, state, 24 * 5 + 29, 24 * 5 + 31)) == 1
