"""Tests for the local replay runner on small hand-built tracks.

Tracks use the jackal profile (24 h mortality window, 3 km movement floor)
and walk 300 m an hour, well below its speed limit and movement floor.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telemetry.core.alerts import OPEN
from telemetry.sim.arrival import SCENARIOS, simulate_arrival
from telemetry.core.detectors.geofence import EXIT, Fence
from telemetry.core.fixes import Arrival, Deployment, Fix
from telemetry.core.geo import offset
from telemetry.sim.replay import (
    DEFAULT_SEED,
    SILENT_HORIZON,
    replay,
    watch_until,
)
from telemetry.core.pipeline import UPLOAD_MARGIN, gap_config
from telemetry.core.stream import first_tick_after
from telemetry.data.studies import STUDIES, part_number

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"


def deployment(deployment_id="A", end_type=None, deploy_off=None, taxon=JACKAL):
    """A deployment starting at START."""
    return Deployment(
        deployment_id, "tag", deployment_id, taxon, START, deploy_off, end_type
    )


def walk(hours, deployment_id="A", start_hour=0, lat=-19.0, lon=15.5):
    """Hourly fixes walking north 300 m an hour, from ``start_hour``."""
    fixes = []
    for i in range(hours):
        lat, lon = offset(lat, lon, 0.0, 300.0)
        fixes.append(Fix(deployment_id, START + (start_hour + i) * HOUR, lat, lon))
    return fixes


def by_detector(result, detector):
    """Incidents in ``result`` raised by ``detector``."""
    return [i for i in result.incidents if i.detector == detector]


def test_same_seed_gives_same_result():
    """Two replays with one seed agree exactly, incidents and summary."""
    deployments = [deployment("A"), deployment("B")]
    fixes = walk(24 * 10, "A") + walk(24 * 6, "B")
    first = replay(deployments, fixes, SCENARIOS["gsm"], seed=7)
    again = replay(deployments, fixes, SCENARIOS["gsm"], seed=7)
    assert first.incidents == again.incidents
    assert first.summary == again.summary


def test_silent_collar_raises_one_gap_soon_after_threshold():
    """A collar that stops raises one gap, within a tick of its threshold."""
    fixes = walk(24 * 5)
    result = replay([deployment(end_type="dead")], fixes, SCENARIOS["ideal"])
    gaps = by_detector(result, "gap")
    assert len(gaps) == 1
    assert gaps[0].status == OPEN
    crossed = fixes[-1].timestamp + gap_config(SCENARIOS["ideal"]).allowance
    assert crossed <= gaps[0].raised_at <= crossed + HOUR


def test_daily_upload_does_not_raise_daily_gaps():
    """A steady collar on daily uploads raises no gap until it stops."""
    fixes = walk(24 * 20)
    result = replay([deployment()], fixes, SCENARIOS["satellite_daily"])
    gaps = by_detector(result, "gap")
    assert len(gaps) == 1
    allowance = gap_config(SCENARIOS["satellite_daily"]).allowance
    assert gaps[0].opened_at == fixes[-1].timestamp + allowance


def test_planned_end_raises_no_gap():
    """A removal at the last fix is known to the operator, so no gap."""
    fixes = walk(24 * 5)
    off = fixes[-1].timestamp
    removed = replay(
        [deployment(end_type="removal", deploy_off=off)], fixes, SCENARIOS["ideal"]
    )
    died = replay(
        [deployment(end_type="dead", deploy_off=off)], fixes, SCENARIOS["ideal"]
    )
    assert not by_detector(removed, "gap")
    assert len(by_detector(died, "gap")) == 1


def test_batched_upload_delays_raised_time():
    """A death on daily uploads is raised at an upload, after its evidence."""
    moving = walk(24 * 4)
    last = moving[-1]
    dead = [
        Fix("A", last.timestamp + h * HOUR, last.lat, last.lon) for h in range(1, 72)
    ]
    fixes = moving + dead
    ideal = by_detector(replay([deployment()], fixes, SCENARIOS["ideal"]), "mortality")
    daily = by_detector(
        replay([deployment()], fixes, SCENARIOS["satellite_daily"]), "mortality"
    )
    assert len(ideal) == len(daily) == 1
    assert ideal[0].opened_at == daily[0].opened_at
    assert ideal[0].raised_at == ideal[0].opened_at
    uploads = {
        a.time
        for a in simulate_arrival(fixes, SCENARIOS["satellite_daily"], DEFAULT_SEED)
    }
    assert daily[0].raised_at in uploads
    assert timedelta(0) < daily[0].raised_at - daily[0].opened_at < timedelta(days=1)


def test_event_parts_sort_numerically():
    """Split event files load part 2 before part 10."""
    assert part_number(Path("x-gps-10.csv")) == 10
    assert part_number(Path("x-gps-2.csv")) == 2
    assert part_number(Path("x.csv")) == 0


def test_summary_counts_fixes_drops_and_incidents():
    """The summary reports every fix, the duplicates sent and the incidents."""
    fixes = walk(24 * 10)
    result = replay([deployment(end_type="dead")], fixes, SCENARIOS["gsm"], seed=3)
    summary = result.summary
    assert summary["fixes"] == len(fixes)
    assert summary["arrivals"] >= len(fixes)
    assert summary["cleaner_dropped"]["duplicate"] <= summary["arrivals"] - len(fixes)
    assert summary["incidents"]["gap"]["incidents"] == len(by_detector(result, "gap"))
    assert summary["settings"]["gap_allowance_hours"] == 1.0 + UPLOAD_MARGIN / HOUR


def test_deployment_without_fixes_is_skipped():
    """A deployment with no fixes takes no part and is not counted."""
    result = replay(
        [deployment("A"), deployment("B")], walk(24 * 4, "A"), SCENARIOS["ideal"]
    )
    assert result.summary["deployments"] == 1


def test_unknown_taxon_is_an_error():
    """A taxon with no species profile stops the replay."""
    with pytest.raises(KeyError):
        replay([deployment(taxon="Panthera leo")], walk(5), SCENARIOS["ideal"])


def test_watch_ends_by_end_type():
    """Planned ends stop at deploy-off; other ends watch on for the horizon."""
    fixes = walk(10)
    arrivals = [Arrival(f.timestamp, f) for f in fixes]
    off = fixes[-1].timestamp + 30 * HOUR
    ideal = SCENARIOS["ideal"]
    removed = deployment(end_type="removal", deploy_off=off)
    assert watch_until(removed, arrivals, ideal) == off
    dead = deployment(end_type="dead", deploy_off=off)
    assert watch_until(dead, arrivals, ideal) == fixes[-1].timestamp + SILENT_HORIZON
    open_ended = deployment(end_type="removal")
    assert watch_until(open_ended, arrivals, ideal) == (
        fixes[-1].timestamp + SILENT_HORIZON
    )


def test_planned_end_waits_for_cleaner_hold():
    """A removal before the last fixes clear the cleaner waits for them."""
    fixes = walk(10)
    arrivals = [Arrival(f.timestamp, f) for f in fixes]
    removed = deployment(end_type="removal", deploy_off=fixes[-1].timestamp)
    gsm = SCENARIOS["gsm"]
    assert watch_until(removed, arrivals, gsm) == (
        fixes[-1].timestamp + gsm.max_lateness
    )


def test_ticks_fall_on_a_fixed_grid():
    """Ticks fall on whole hours, strictly after the given time."""
    on_hour = START + 5 * HOUR
    assert first_tick_after(on_hour, HOUR) == on_hour + HOUR
    assert first_tick_after(on_hour + timedelta(minutes=1), HOUR) == on_hour + HOUR


def test_idle_stretch_between_deployments_is_skipped():
    """A deployment starting after an idle month replays as if alone."""
    early = walk(24 * 5, "A")
    late = walk(24 * 5, "B", start_hour=24 * 60)
    both = replay(
        [deployment("A", "dead"), deployment("B", "dead")],
        early + late,
        SCENARIOS["ideal"],
    )
    alone = replay([deployment("B", "dead")], late, SCENARIOS["ideal"])
    assert [i for i in both.incidents if i.deployment_id == "B"] == alone.incidents
    assert len(by_detector(both, "gap")) == 2


def test_committed_studies_have_their_files():
    """Every study's reference file and event parts are committed."""
    raw = Path(__file__).resolve().parents[2] / "data" / "raw"
    for study in STUDIES:
        assert study.reference_path(raw).is_file()
        parts = study.event_paths(raw)
        assert parts
        assert parts == sorted(parts, key=part_number)
    vultures = STUDIES[0].event_paths(raw)
    assert [part_number(p) for p in vultures] == [1, 2, 3, 4, 5, 6]


def test_replay_runs_the_geofence_when_given_a_fence():
    """A deployment walking out of a fence raises one geofence incident."""
    lat, lon = -19.0, 15.5
    ring = [
        [lon - 0.05, lat - 0.05],
        [lon + 0.05, lat - 0.05],
        [lon + 0.05, lat + 0.05],
        [lon - 0.05, lat + 0.05],
        [lon - 0.05, lat - 0.05],
    ]
    fence = Fence({"type": "Polygon", "coordinates": [ring]}, "Box", EXIT, 100.0)
    # Walks north 300 m an hour, leaving the box (5.5 km) after ~19 h.
    result = replay([deployment()], walk(48), SCENARIOS["ideal"], fence=fence)
    geofence = by_detector(result, "geofence")
    assert len(geofence) == 1
    assert geofence[0].message.startswith("Left Box")
    assert "geofence" not in {
        i.detector
        for i in replay([deployment()], walk(48), SCENARIOS["ideal"]).incidents
    }
