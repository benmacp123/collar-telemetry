"""Tests for slicing a timeline: the cloud runner's messages must give the
same incidents as the replay runner's single pass.

Tracks use the jackal profile, walk 300 m an hour for five days, then stay
put (a death) for three days, then fall silent, so mortality, gap and
lifecycle transitions all happen inside the sliced stretch.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.sim.arrival import SCENARIOS, simulate_arrival
from telemetry.core.fixes import Arrival, Fix
from telemetry.core.geo import offset
from telemetry.core.pipeline import stream_for
from telemetry.sim.replay import SILENT_HORIZON
from telemetry.core.slices import Slice, slice_timeline
from telemetry.core.stream import AnimalState

START = datetime(2009, 3, 1, 0, 20, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"


def track(start=START):
    """Five days walking, then three days still, one fix an hour."""
    fixes = []
    lat, lon = -19.0, 15.5
    for i in range(24 * 8):
        if i < 24 * 5:
            lat, lon = offset(lat, lon, 0.0, 300.0)
        fixes.append(Fix("A", start + i * HOUR, lat, lon))
    return fixes


def one_pass(scenario, start=START):
    """Incidents and final state from running the whole timeline at once."""
    arrivals = simulate_arrival(track(start), scenario, seed=3)
    until = arrivals[-1].time + SILENT_HORIZON
    stream = stream_for(JACKAL, scenario)
    incidents = stream.advance("A", arrivals, until)
    return arrivals, until, incidents, stream.states["A"].to_dict()


def sliced(scenario, arrivals, until, **kwargs):
    """Run the timeline slice by slice, saving state and slice through JSON
    between invocations, as the cloud handler does."""
    saved = None
    incidents = []
    for part in slice_timeline("A", arrivals, until, **kwargs):
        stream = stream_for(JACKAL, scenario)
        if saved is not None:
            stream.states["A"] = AnimalState.from_dict(json.loads(saved))
        message = Slice.from_dict(json.loads(json.dumps(part.to_dict())))
        incidents += stream.advance("A", list(message.arrivals), message.until)
        saved = json.dumps(stream.states["A"].to_dict())
    return incidents, json.loads(saved)


@pytest.mark.parametrize("start", [START, START.replace(minute=0)])
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"every": HOUR},
        {"every": timedelta(days=3)},
        {"max_arrivals": 1},
        {"max_arrivals": 7, "every": timedelta(hours=5)},
    ],
)
def test_any_slicing_gives_the_one_pass_result(scenario, kwargs, start):
    """Slicing, and saving state between slices, never changes an incident,
    whether or not arrivals fall exactly on the tick grid."""
    arrivals, until, expected, state = one_pass(SCENARIOS[scenario], start)
    assert {i.detector for i in expected} >= {"mortality", "gap"}
    incidents, final = sliced(SCENARIOS[scenario], arrivals, until, **kwargs)
    assert incidents == expected
    assert final == state


def test_slices_cover_every_arrival_once_in_order():
    """Slices carry each arrival once, end on the grid and finish at until."""
    arrivals = simulate_arrival(track(), SCENARIOS["gsm"], seed=3)
    until = arrivals[-1].time + timedelta(hours=30, minutes=7)
    slices = slice_timeline("A", arrivals, until)
    assert [a for s in slices for a in s.arrivals] == arrivals
    assert slices[-1].until == until
    for part in slices[:-1]:
        assert part.until.hour == 0 and part.until.minute == 0
        assert all(a.time <= part.until for a in part.arrivals)


def test_empty_days_still_get_a_clock_slice():
    """A silent stretch yields arrival-free slices, so ticks keep running."""
    arrivals = [Arrival(START, Fix("A", START, -19.0, 15.5))]
    slices = slice_timeline("A", arrivals, START + timedelta(days=3))
    assert len(slices) == 4
    assert [len(s.arrivals) for s in slices] == [1, 0, 0, 0]


def test_split_day_leaves_the_clock_until_its_last_part():
    """Only the last part of a split stretch moves the clock on."""
    arrivals = simulate_arrival(track(), SCENARIOS["satellite_daily"], seed=3)
    slices = slice_timeline("A", arrivals, arrivals[-1].time, max_arrivals=10)
    assert max(len(s.arrivals) for s in slices) == 10
    # A daily upload of 24 fixes splits into 10 + 10 + 4.
    sizes = [len(s.arrivals) for s in slices if s.arrivals]
    assert 4 in sizes
    assert all(s.until is None for s in slices if 0 < len(s.arrivals) == 10)


def test_no_arrivals_means_no_slices():
    """The clock does not start before the first arrival."""
    assert not slice_timeline("A", [], START)


def test_arrival_after_end_of_watch_is_an_error():
    """An end of watch before the last arrival would drop fixes."""
    arrivals = [Arrival(START, Fix("A", START, -19.0, 15.5))]
    with pytest.raises(ValueError, match="end of watch"):
        slice_timeline("A", arrivals, START - HOUR)


def test_max_arrivals_must_be_positive():
    """A limit of zero arrivals per slice can never finish."""
    with pytest.raises(ValueError, match="at least 1"):
        slice_timeline("A", [], START, max_arrivals=0)


def test_slice_survives_a_json_round_trip():
    """A slice written as a message body reads back unchanged."""
    arrivals = simulate_arrival(track()[:30], SCENARIOS["gsm"], seed=3)
    for part in slice_timeline("A", arrivals, arrivals[-1].time, max_arrivals=4):
        assert Slice.from_dict(json.loads(json.dumps(part.to_dict()))) == part
