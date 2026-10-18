"""Tests for scoring replayed incidents against deployment labels.

Tracks and incidents are hand-built, so no test looks at the vulture
scoring set.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from telemetry.alerts import LATE_FIX, OPEN, RESOLVED, Incident
from telemetry.evaluation import (
    ALIVE,
    ALL,
    AMBIGUOUS,
    DEAD,
    DEAD_AFTER_TRACK,
    SCORING,
    TUNING,
    Truth,
    build_truth,
    classify,
    detection_rate,
    evaluate,
    false_mortality,
    final_still_start,
    gap_detection,
    label_for,
    mortality_detection,
    precision,
    read_incidents,
    read_labels,
    reference_mark,
    split_for,
)
from telemetry.fixes import Deployment, Fix
from telemetry.geo import offset

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
JACKAL = "Canis mesomelas"


def deployment(deployment_id="A", end_type=None, deploy_on=START):
    """A jackal deployment (24 h carcass minimum)."""
    return Deployment(
        deployment_id, "tag", deployment_id, JACKAL, deploy_on, None, end_type
    )


def walk_then_still(walk_hours, still_hours, deployment_id="A", jitter_m=10.0):
    """Hourly fixes walking north 500 m an hour, then lying still.

    The still fixes alternate ``jitter_m`` east and west of one spot, like
    GPS scatter around a carcass.
    """
    lat, lon = -19.0, 15.5
    fixes = []
    for i in range(walk_hours):
        lat, lon = offset(lat, lon, 0.0, 500.0)
        fixes.append(Fix(deployment_id, START + i * HOUR, lat, lon))
    for i in range(still_hours):
        bearing = 90.0 if i % 2 else 270.0
        point = offset(lat, lon, bearing, jitter_m)
        fixes.append(Fix(deployment_id, START + (walk_hours + i) * HOUR, *point))
    return fixes


def truth(label=DEAD, still_start=START + 10 * HOUR, last_fix=START + 60 * HOUR):
    """A jackal truth record tracked from START."""
    return Truth(
        deployment_id="A",
        taxon=JACKAL,
        label=label,
        split=ALL,
        first_fix=START,
        last_fix=last_fix,
        still_start=still_start,
        still_start_wide=still_start,
        carcass_min=DAY,
    )


def incident(detector, opened, raised=None, resolved=None, resolution="moved"):
    """An incident for deployment A, resolved if ``resolved`` is given."""
    return Incident(
        incident_id=f"A:{detector}:{opened.isoformat()}",
        deployment_id="A",
        detector=detector,
        status=RESOLVED if resolved else OPEN,
        opened_at=opened,
        message="",
        resolved_at=resolved,
        resolution=resolution if resolved else None,
        raised_at=raised or opened,
    )


def test_still_start_is_first_fix_of_final_stationary_period():
    """Death start is the first fix from which the track stays put.

    The last walked fix (hour 9) is the spot the animal then lies at.
    """
    fixes = walk_then_still(10, 30)
    assert final_still_start(fixes, 100.0) == START + 9 * HOUR


def test_still_start_wider_radius_reaches_back_further():
    """A fix 150 m from the final spot is inside 200 m but not 100 m."""
    spot = (-19.0, 15.5)
    fixes = [Fix("A", START, *offset(*spot, 0.0, 150.0))]
    fixes += [Fix("A", START + (i + 1) * HOUR, *spot) for i in range(6)]
    assert final_still_start(fixes, 100.0) == START + HOUR
    assert final_still_start(fixes, 200.0) == START


def test_still_start_of_scattered_tail_is_last_fix():
    """A tail with no stationary period gives the last fix's time."""
    fixes = walk_then_still(12, 0)
    assert final_still_start(fixes, 100.0) == fixes[-1].timestamp


@pytest.mark.parametrize(
    "end_type, still, expected",
    [
        ("dead", timedelta(0), DEAD),
        ("dead/fall-off", timedelta(0), DEAD),
        ("removal", 3 * DAY, ALIVE),
        ("transmission-end", 3 * DAY, AMBIGUOUS),
        ("transmission-end", 10 * HOUR, ALIVE),
        (None, DAY, AMBIGUOUS),
    ],
)
def test_label_from_end_type_and_final_stillness(end_type, still, expected):
    """Dead ends are dead; unplanned ends that finish still are ambiguous."""
    assert label_for(deployment(end_type=end_type), {}, still, DAY) == expected


def test_label_override_wins_over_end_type():
    """A labels.csv override replaces the end type."""
    overrides = {"A": DEAD_AFTER_TRACK}
    assert label_for(deployment(end_type="dead"), overrides, DAY, DAY) == (
        DEAD_AFTER_TRACK
    )


def test_split_by_deployment_start_for_vultures_only():
    """Vultures split at 2013; other studies are scored whole."""
    early = deployment(deploy_on=datetime(2012, 12, 31, tzinfo=timezone.utc))
    late = deployment(deploy_on=datetime(2013, 1, 1, tzinfo=timezone.utc))
    assert split_for("vultures", early) == TUNING
    assert split_for("vultures", late) == SCORING
    assert split_for("jackals", late) == ALL


def test_read_labels_rejects_unknown_label(tmp_path):
    """Only the labels the review produces are accepted."""
    path = tmp_path / "labels.csv"
    path.write_text("deployment-id,label\nA,dead\nB,alive\n", encoding="utf-8")
    with pytest.raises(ValueError, match="alive"):
        read_labels(path)


def test_build_truth_skips_deployments_without_fixes():
    """Deployments with no fixes are left out; the rest get labels."""
    deployments = [deployment("A", "dead"), deployment("B", "dead")]
    truths = build_truth("jackals", deployments, walk_then_still(10, 30), {})
    assert [t.deployment_id for t in truths] == ["A"]
    assert truths[0].label == DEAD
    assert truths[0].carcass
    assert truths[0].still_hours == 30.0


def test_mortality_delay_from_death_start():
    """An incident raised after the death start scores its delay."""
    death = START + 10 * HOUR
    found = mortality_detection(death, [incident("mortality", death + 26 * HOUR)])
    assert found == (26.0, False)


def test_mortality_incident_open_before_death_counts_with_zero_delay():
    """An earlier incident still open at the death start detects it early."""
    death = START + 10 * HOUR
    found = mortality_detection(death, [incident("mortality", START)])
    assert found == (0.0, True)


def test_mortality_incident_resolved_at_death_start_does_not_count():
    """The move to the death site ends an earlier incident; that is no hit."""
    death = START + 10 * HOUR
    earlier = incident("mortality", START, resolved=death)
    assert mortality_detection(death, [earlier]) is None


def test_mortality_delay_uses_processing_clock():
    """Delay runs to raised_at, not to the evidence time."""
    death = START + 10 * HOUR
    late = incident("mortality", death + 24 * HOUR, raised=death + 40 * HOUR)
    assert mortality_detection(death, [late]) == (40.0, False)


def test_gap_delay_uses_incident_open_at_end():
    """Gap delay is from the last fix to the gap still open at the end."""
    last = START + 60 * HOUR
    earlier = incident("gap", START + 20 * HOUR, resolved=START + 30 * HOUR)
    final = incident("gap", last + 6 * HOUR, raised=last + 7 * HOUR)
    assert gap_detection(last, [earlier, final]) == 7.0
    assert gap_detection(last, [earlier]) is None


def test_false_mortality_alive_counts_every_incident():
    """Every mortality incident on a live animal is a false alarm."""
    incidents = [incident("mortality", START), incident("mortality", START + DAY)]
    assert false_mortality(truth(label=ALIVE), incidents) == 2


def test_false_mortality_dead_counts_only_resolved_before_death():
    """On a dead animal, only incidents that ended before death are false."""
    before = incident("mortality", START, resolved=START + 5 * HOUR)
    at_death = incident("mortality", START + 30 * HOUR)
    assert false_mortality(truth(), [before, at_death]) == 1


def test_detection_rate_counts_missed_deaths_in_denominator():
    """Missed deaths count against the rate."""
    assert detection_rate([10.0, 50.0, None, 100.0], 60.0) == 0.5
    assert detection_rate([], 60.0) is None


def test_reference_mark_is_median_carcass_period():
    """The mark is the median stationary end of carcass deaths only."""
    truths = [
        truth(still_start=START, last_fix=START + hours * HOUR)
        for hours in (25, 53, 88, 97)
    ]
    truths.append(truth(still_start=START, last_fix=START + 5 * HOUR))
    assert reference_mark(truths) == 70.5


def test_evaluate_scores_load_deaths_and_ambiguous_tracks():
    """One dead and one ambiguous track: rates, delays and exclusions."""
    dead = truth()
    ambiguous = Truth(**{**dead.__dict__, "deployment_id": "B", "label": AMBIGUOUS})
    incidents = [
        incident("mortality", START + 34 * HOUR),
        incident("gap", START + 66 * HOUR),
        incident("gap", START + HOUR, resolved=START + 2 * HOUR, resolution=LATE_FIX),
        Incident(
            "B:mortality:x",
            "B",
            "mortality",
            OPEN,
            START + 34 * HOUR,
            "",
            raised_at=START + 34 * HOUR,
        ),
    ]
    result = evaluate([dead, ambiguous], incidents, mark_hours=48.0)
    assert result["load"]["gap"] == {
        "incidents": 2,
        "late_fix": 1,
        "per_animal_month": round(2 / (2 * 60 / 730.5), 3),
    }
    assert result["false_mortality"]["incidents"] == 0
    assert result["mortality"]["detected"] == 1
    assert result["mortality"]["rate_at_mark"] == 1.0
    assert result["deaths"][0]["mortality_delay_hours"] == 24.0
    assert result["deaths"][0]["gap_delay_hours"] == 6.0
    assert result["both_detectors"] == 1
    assert result["ambiguous"] == [
        {"deployment_id": "B", "still_hours": 50.0, "mortality_delay_hours": 24.0}
    ]


def test_read_incidents_round_trip(tmp_path):
    """Incidents written as JSON lines read back unchanged."""
    original = [
        incident("gap", START),
        incident("mortality", START, resolved=START + DAY),
    ]
    path = tmp_path / "incidents.jsonl"
    path.write_text(
        "".join(json.dumps(i.to_dict()) + "\n" for i in original),
        encoding="utf-8",
    )
    assert read_incidents(path) == original


def test_carcass_split_does_not_follow_detector_window():
    """A 30 h vulture carcass stays a carcass though the window is 36 h."""
    vulture = Deployment("A", "tag", "A", "Cathartes aura", START, None, "dead")
    truths = build_truth("vultures", [vulture], walk_then_still(10, 31), {})
    assert truths[0].still_hours == 31.0
    assert truths[0].carcass


def test_classify_by_label_and_timing():
    """True only on a death and open after its start; ambiguous kept apart."""
    before = incident("mortality", START, resolved=START + 5 * HOUR)
    during = incident("mortality", START + 30 * HOUR)
    assert classify(truth(), before) == "false"
    assert classify(truth(), during) == "true"
    assert classify(truth(label=AMBIGUOUS), during) == "ambiguous"
    assert classify(truth(label=ALIVE), during) == "false"


def test_precision_leaves_ambiguous_out():
    """Precision is true over true plus false."""
    dead, alive = truth(), Truth(
        **{**truth().__dict__, "deployment_id": "B", "label": ALIVE}
    )
    own = {
        ("A", "likely_death"): [incident("likely_death", START + 30 * HOUR)],
        ("B", "likely_death"): [
            Incident("B:x", "B", "likely_death", OPEN, START, "", raised_at=START)
        ],
    }
    assert precision([dead, alive], own, "likely_death") == {
        "true": 1,
        "false": 1,
        "ambiguous": 0,
        "precision": 0.5,
    }
    assert precision([dead], {}, "likely_death")["precision"] is None
