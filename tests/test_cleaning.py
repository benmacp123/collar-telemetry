"""Tests for the cleaning stage.

Faults are injected, since the committed data has almost none.
"""

import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.cleaning import Cleaner, CleaningConfig, is_valid
from telemetry.fixes import Fix
from telemetry.stream import Alert, FixStream

START = datetime(2016, 4, 19, tzinfo=timezone.utc)
# 0.001 degrees of latitude is about 111 m.
STEP = 0.001


def fix(hours, lat=30.5, lon=-86.5, deployment_id="A"):
    """A fix ``hours`` after START."""
    return Fix(deployment_id, START + timedelta(hours=hours), lat, lon)


def walk(n):
    """n hourly fixes moving about 111 m an hour."""
    return [fix(hours, lat=30.5 + hours * STEP) for hours in range(n)]


def cleaner(lateness_hours=0, max_speed=10.0, **kwargs):
    """A cleaner holding fixes for ``lateness_hours``, with an m/s speed limit."""
    return Cleaner(CleaningConfig(timedelta(hours=lateness_hours), max_speed, **kwargs))


def run(clean, fixes, state=None):
    """Feed ``fixes`` to ``clean`` in order; return the released fixes and the state."""
    state = {} if state is None else state
    released = [out for f in fixes for out in clean.arrive(state, f)]
    return released, state


@pytest.mark.parametrize(
    "lat, lon", [(91, 0), (-91, 0), (0, 181), (0, -181), (0.0, 0.0)]
)
def test_impossible_coordinates_are_invalid(lat, lon):
    """Out-of-range coordinates and the (0, 0) placeholder are invalid."""
    assert not is_valid(fix(0, lat, lon))


def test_valid_coordinates():
    """An ordinary position is valid."""
    assert is_valid(fix(0, -24.5, 31.7))


def test_without_lateness_fixes_pass_straight_through():
    """With no lateness allowed, in-order fixes are released at once."""
    fixes = walk(5)
    released, state = run(cleaner(), fixes)
    assert released == fixes
    assert state["buffer"] == []


def test_buffer_reorders_out_of_order_arrival():
    """Shuffled arrival comes out in time order once the watermark passes."""
    fixes = walk(6)
    arrival = [fixes[i] for i in (0, 2, 1, 3, 5, 4)]
    released, state = run(cleaner(lateness_hours=2), arrival)
    # Fixes less than 2 h older than the newest are still held.
    assert released == fixes[:4]
    assert [Fix.from_dict(item) for item in state["buffer"]] == fixes[4:]


def test_tick_releases_held_fixes_after_a_collar_falls_silent():
    """Ticks release held fixes even when no new fix arrives."""
    clean = cleaner(lateness_hours=2)
    _, state = run(clean, walk(3))
    assert clean.tick(state, START + timedelta(hours=3)) == [fix(1, lat=30.501)]
    assert clean.tick(state, START + timedelta(hours=10)) == [fix(2, lat=30.502)]
    assert state["buffer"] == []


def test_fix_older_than_a_released_one_is_dropped_as_late():
    """A fix older than one already released cannot be inserted, so it is dropped."""
    fixes = walk(4)
    released, state = run(cleaner(lateness_hours=1), fixes + [fix(0.5, lat=30.5)])
    assert released == fixes[:3]
    assert state["dropped"]["late"] == 1


def test_duplicates_are_dropped_in_the_buffer_and_after_release():
    """Repeats are dropped whether still buffered or already released."""
    fixes = walk(3)
    arrival = [fixes[0], fixes[1], fixes[1], fixes[2], fixes[2], fixes[0]]
    released, state = run(cleaner(lateness_hours=1), arrival)
    assert released == fixes[:2]
    # fixes[1] and fixes[2] each repeat while still buffered.
    assert state["dropped"]["duplicate"] == 2
    # An older repeat cannot be told from a late fix, so counts as late.
    assert state["dropped"]["late"] == 1


def test_repeat_of_the_last_released_fix_is_a_duplicate():
    """A repeat of the most recent released fix counts as a duplicate, not late."""
    fixes = walk(2)
    released, state = run(cleaner(), fixes + [fixes[1]])
    assert released == fixes
    assert state["dropped"]["duplicate"] == 1


def test_impossible_jump_is_dropped():
    """A single 111 km jump in 30 minutes is removed and the track continues."""
    fixes = walk(4)
    spike = fix(1.5, lat=31.5)  # 111 km in 30 min
    released, state = run(cleaner(), fixes[:2] + [spike] + fixes[2:])
    assert released == fixes
    assert state["dropped"]["speed"] == 1


def test_gps_jitter_on_short_intervals_is_not_speed():
    """40 m of jitter in one second is 40 m/s, but within GPS error."""
    a = Fix("A", START, 30.5, -86.5)
    b = Fix("A", START + timedelta(seconds=1), 30.5 + 0.00036, -86.5)
    released, state = run(cleaner(max_speed=10.0, gps_error_m=30.0), [a, b])
    assert released == [a, b]
    assert state["dropped"]["speed"] == 0


def test_bad_anchor_does_not_reject_the_rest_of_the_track():
    """If the first fix is wrong, the cleaner recovers after a few rejects."""
    bad_first = fix(0, lat=35.0)
    good = [fix(hours, lat=30.5 + hours * STEP) for hours in range(1, 7)]
    released, state = run(cleaner(max_consecutive_rejects=3), [bad_first] + good)
    assert released[0] == bad_first
    assert released[1:] == good[3:]
    assert state["dropped"]["speed"] == 3


def test_invalid_fix_is_counted():
    """Invalid fixes are dropped and counted, not silently lost."""
    released, state = run(cleaner(), [fix(0, 0.0, 0.0)])
    assert not released
    assert state["dropped"]["invalid"] == 1


def test_state_is_json_and_resumes_mid_buffer():
    """Saving and resuming mid-buffer gives exactly the output of an unbroken run."""
    fixes = walk(8)
    rng = random.Random(1)
    arrival = fixes[:]
    rng.shuffle(arrival)
    clean = cleaner(lateness_hours=24)

    whole, _ = run(clean, arrival)
    first, state = run(clean, arrival[:4])
    state = json.loads(json.dumps(state))
    rest, _ = run(clean, arrival[4:], state)
    assert first + rest == whole


class OrderRecorder:
    """Records the fixes a detector receives."""

    name = "order"

    def on_fix(self, state, deployment_id, fix_):
        """Record the fix's timestamp."""
        state.setdefault("seen", []).append(fix_.timestamp.isoformat())
        return []

    def on_tick(self, state, deployment_id, now):
        """Return one alert per tick."""
        return [Alert(deployment_id, self.name, now, "tick")]


def test_stream_detectors_see_shuffled_arrival_in_time_order():
    """End to end: batched, shuffled arrival reaches detectors in exact time order."""
    fixes = walk(48)
    rng = random.Random(7)
    arrival = fixes[:]
    # Shuffle within 6-hour batches, as a batched upload might.
    for start in range(0, len(arrival), 6):
        batch = arrival[start : start + 6]
        rng.shuffle(batch)
        arrival[start : start + 6] = batch
    stream = FixStream([OrderRecorder()], cleaner(lateness_hours=6))
    for f in arrival:
        stream.ingest(f)
    stream.tick(START + timedelta(days=30))
    seen = stream.states["A"].detectors["order"]["seen"]
    assert seen == [f.timestamp.isoformat() for f in fixes]


def test_stream_tick_releases_before_detectors_check_the_clock():
    """A stream tick hands due fixes to detectors before they check the clock."""
    stream = FixStream([OrderRecorder()], cleaner(lateness_hours=2))
    for f in walk(3):
        stream.ingest(f)
    stream.tick(START + timedelta(days=1))
    assert len(stream.states["A"].detectors["order"]["seen"]) == 3
