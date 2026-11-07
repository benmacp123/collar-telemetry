"""Tests for scoring replayed incidents against deployment labels.

Tracks and incidents are hand-built, so no test looks at the vulture
scoring set.
"""

import csv
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telemetry.core.alerts import (
    GAP,
    LATE_FIX,
    MORTALITY,
    OPEN,
    POTENTIAL_DEATH,
    RESOLVED,
    Incident,
)
from telemetry.analysis.evaluation import (
    clear_times,
    ALIVE,
    ALL,
    AMBIGUOUS,
    DEAD,
    DEAD_AFTER_TRACK,
    SCORING,
    TAG_EVENT,
    TUNING,
    Override,
    Truth,
    build_truth,
    classify,
    death_timeline,
    detection_rate,
    evaluate,
    false_alerts,
    false_mortality,
    final_still_start,
    first_alert,
    gap_detection,
    label_for,
    mortality_detection,
    precision,
    random_precision,
    read_incidents,
    read_labels,
    reference_mark,
    score_synthetic,
    split_for,
)
from telemetry.core.fixes import Arrival, Deployment, Fix
from telemetry.core.geo import offset
from telemetry.sim.synthetic import InjectedDeath

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
    overrides = {"A": Override(DEAD_AFTER_TRACK)}
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


def test_clear_times_are_the_median_on_false_alerts_only():
    """Time to clear measures false alerts; one left open is counted apart,
    and an alert on the carcass itself does not count."""
    death = truth(still_start=START + 100 * HOUR, last_fix=START + 200 * HOUR)
    own = {
        ("A", "mortality"): [
            incident("mortality", START, resolved=START + 4 * HOUR),
            incident("mortality", START + 10 * HOUR, resolved=START + 20 * HOUR),
            incident("mortality", START + 30 * HOUR, resolved=START + 60 * HOUR),
            incident("mortality", START + 150 * HOUR),
        ]
    }
    assert clear_times([death], own) == {
        "false": 3,
        "never_resolved": 0,
        "median_hours": 10.0,
    }
    alive = truth(label=ALIVE, last_fix=START + 200 * HOUR)
    assert clear_times([alive], own)["never_resolved"] == 1


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


def test_first_alert_takes_earliest_of_mortality_and_gap():
    """A gap that opens after the death start can be the first alert."""
    death = START + 10 * HOUR
    mortality = [incident("mortality", death + 40 * HOUR)]
    gap = [incident("gap", death + 30 * HOUR, resolved=death + 35 * HOUR)]
    assert first_alert(death, mortality, gap) == 30.0
    assert first_alert(death, mortality, []) == 40.0
    assert first_alert(death, [], gap) == 30.0


def test_first_alert_gap_delay_uses_processing_clock():
    """A gap's delay runs to raised_at, not to its evidence time."""
    death = START + 10 * HOUR
    gap = [incident("gap", death + 30 * HOUR, raised=death + 48 * HOUR)]
    assert first_alert(death, [], gap) == 48.0


def test_first_alert_ignores_gap_opened_before_death_start():
    """A silence that began while the animal was alive does not count."""
    death = START + 10 * HOUR
    gap = [incident("gap", START + 5 * HOUR, resolved=death + 5 * HOUR)]
    assert first_alert(death, [], gap) is None


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
        "late_fix_per_animal_month": round(1 / (2 * 60 / 730.5), 3),
    }
    assert result["false_mortality"]["incidents"] == 0
    assert result["mortality"]["detected"] == 1
    assert result["mortality"]["rate_at_mark"] == 1.0
    assert result["deaths"][0]["mortality_delay_hours"] == 24.0
    assert result["deaths"][0]["gap_delay_hours"] == 6.0
    assert result["both_detectors"] == 1
    assert result["deaths"][0]["first_alert_delay_hours"] == 24.0
    assert result["first_alert"] == {
        "deaths": 1,
        "detected": 1,
        "rate_at_mark": 1.0,
        "median_delay_hours": 24.0,
    }
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
        ("A", "potential_death"): [incident("potential_death", START + 30 * HOUR)],
        ("B", "potential_death"): [
            Incident("B:x", "B", "potential_death", OPEN, START, "", raised_at=START)
        ],
    }
    assert precision([dead, alive], own, "potential_death") == {
        "true": 1,
        "false": 1,
        "ambiguous": 0,
        "tag-event": 0,
        "judged": 2,
        "correct": 1,
        "precision": 0.5,
        "death_precision": 0.5,
        "wilson": [0.094529, 0.905471],
        "bootstrap": [0.0, 1.0],
    }
    empty = precision([dead], {}, "potential_death")
    assert empty["precision"] is None
    assert empty["wilson"] is None and empty["bootstrap"] is None


def test_evaluate_puts_ceiling_and_gap_baseline_beside_precision():
    """Mortality's ceiling counts carcass deaths, the gap baseline's every
    death, each against its own false alerts."""
    dead = truth()
    alive = Truth(**{**dead.__dict__, "deployment_id": "B", "label": ALIVE})
    incidents = [
        incident("mortality", START + 34 * HOUR),
        incident("gap", START + 66 * HOUR),
        Incident("B:m", "B", "mortality", OPEN, START, "", raised_at=START),
        Incident("B:g1", "B", "gap", OPEN, START, "", raised_at=START),
        Incident("B:g2", "B", "gap", OPEN, START, "", raised_at=START),
    ]
    scored = evaluate([dead, alive], incidents, mark_hours=48.0)["precision"]
    assert (scored["mortality"]["cases"], scored["mortality"]["ceiling"]) == (1, 0.5)
    assert scored["gap"]["true"] == 1 and scored["gap"]["false"] == 2
    assert scored["gap"]["ceiling"] == round(1 / 3, 6)


def test_random_precision_is_share_of_judged_time_dead():
    """Dead time over tracked time, with ambiguous tails left out of both."""
    dead = truth()  # 60 h tracked, 50 h after the death start
    alive = Truth(**{**dead.__dict__, "deployment_id": "B", "label": ALIVE})
    ambiguous = Truth(**{**dead.__dict__, "deployment_id": "C", "label": AMBIGUOUS})
    assert random_precision([dead, alive]) == round(50 / 120, 4)
    assert random_precision([dead, alive, ambiguous]) == round(50 / 130, 4)
    assert random_precision([]) is None


def test_false_alerts_by_deployment_and_taxon():
    """Birds are listed most false alerts first, birds without any left
    out; taxa are always listed."""
    dead = truth()
    alive = Truth(**{**dead.__dict__, "deployment_id": "B", "label": ALIVE})
    own = {
        ("A", "mortality"): [incident("mortality", START + 30 * HOUR)],
        ("B", "mortality"): [
            Incident(f"B:{i}", "B", "mortality", OPEN, START, "", raised_at=START)
            for i in range(3)
        ],
    }
    by = false_alerts([dead, alive], own, "mortality")
    assert [r["name"] for r in by["by_deployment"]] == ["B"]
    assert by["by_deployment"][0]["false"] == 3
    assert by["by_taxon"] == [
        {
            "name": JACKAL,
            "animal_months": round(120 / 730.5, 1),
            "true": 1,
            "false": 3,
            "false_per_animal_month": round(3 / (120 / 730.5), 3),
        }
    ]


def test_score_synthetic_reports_regimes_and_injected_delays():
    """Synthetic deaths are split by regime and also scored from the injected time."""
    death = START + 10 * HOUR
    fixes = walk_then_still(11, 50, "A") + walk_then_still(11, 50, "B")
    dead = [deployment("A", "dead"), deployment("B", "dead")]
    truths = build_truth("jackals-synthetic", dead, fixes, {})
    injected = [
        InjectedDeath("A", "a", "reporting", death, 0.0, 0.0, 50, DAY),
        InjectedDeath("B", "b", "sparse", death, 0.0, 0.0, 50, DAY),
    ]
    raised = START + 20 * HOUR
    incidents = [
        Incident(
            incident_id=f"{d}:mortality",
            deployment_id=d,
            detector="mortality",
            status=OPEN,
            opened_at=raised,
            message="",
            raised_at=raised,
        )
        for d in ("A", "B")
    ]
    result = score_synthetic(truths, incidents, 90.0, injected)
    regimes = {d["deployment_id"]: d["regime"] for d in result["deaths"]}
    assert regimes == {"A": "reporting", "B": "sparse"}
    assert all(d["mortality_delay_hours"] == 10.0 for d in result["deaths"])
    assert all(d["mortality_delay_hours_injected"] == 10.0 for d in result["deaths"])
    summary = result["synthetic"]
    assert summary["pooled"]["deaths"] == 2
    assert summary["reporting"]["deaths"] == summary["sparse"]["deaths"] == 1
    assert summary["pooled"]["mortality"]["detected_injected"] == 2
    assert summary["pooled"]["mortality"]["median_delay_hours_injected"] == 10.0
    assert summary["pooled"]["potential_death"]["detected"] == 0
    assert summary["pooled"]["death_start_offset_hours"]["exact"] == 2


def test_score_synthetic_offset_is_positive_when_computed_start_is_later():
    """A computed death start after the injected time shows as a later offset."""
    fixes = walk_then_still(30, 40)
    truths = build_truth("jackals-synthetic", [deployment("A", "dead")], fixes, {})
    injected = [InjectedDeath("A", "a", "reporting", START, 0.0, 0.0, 40, DAY)]
    result = score_synthetic(truths, [], 90.0, injected)
    offset_hours = result["synthetic"]["reporting"]["death_start_offset_hours"]
    assert offset_hours["later"] == 1
    assert offset_hours["min"] == pytest.approx((truths[0].still_start - START) / HOUR)
    assert result["synthetic"]["reporting"]["mortality"]["detected"] == 0


def test_death_timeline_puts_everything_in_hours_from_death_start():
    """Fixes, arrivals and incidents share one axis from the death start."""
    fixes = walk_then_still(10, 50)
    arrivals = {"ideal": [Arrival(f.timestamp + 2 * HOUR, f) for f in fixes]}
    gap = replace(
        incident("gap", START + 30 * HOUR, resolved=START + 35 * HOUR),
        resolve_raised_at=START + 35 * HOUR,
    )
    old = replace(
        incident("mortality", START, resolved=START + 2 * HOUR),
        incident_id="A:mortality:old",
        resolve_raised_at=START + 2 * HOUR,
    )
    other = replace(incident("mortality", START + 20 * HOUR), deployment_id="B")
    incidents = {
        "ideal": [
            incident("mortality", START + 50 * HOUR),
            gap,
            old,
            other,
            incident("movement", START + 12 * HOUR),
        ]
    }
    timeline = death_timeline(fixes, arrivals, incidents, (-5.0, 100.0))
    assert timeline["deployment_id"] == "A"
    # The walk's last fix is the carcass spot, so death starts at hour 9.
    assert timeline["still_hours"] == 50.0
    assert [h for h, _ in timeline["fixes"]][:6] == [-5.0, -4.0, -3.0, -2.0, -1.0, 0.0]
    # The final position is one side of the 10 m jitter, so still fixes
    # lie 0 or 20 m from it.
    assert all(m <= 20.5 for h, m in timeline["fixes"] if h >= 0)
    ideal = timeline["scenarios"]["ideal"]
    assert ideal["arrivals"][0] == -5.0 and ideal["arrivals"][-1] == 52.0
    assert ideal["incidents"] == [
        {"detector": "mortality", "raised": 41.0, "resolved": None},
        {"detector": "gap", "raised": 21.0, "resolved": 26.0},
    ]


EVENT_FROM = START + 30 * HOUR


def tag_truth(deployment_id="A"):
    """A tag-event truth record whose event began at EVENT_FROM."""
    return Truth(
        **{
            **truth().__dict__,
            "deployment_id": deployment_id,
            "label": TAG_EVENT,
            "event_from": EVENT_FROM,
        }
    )


def test_read_labels_keeps_tag_event_start(tmp_path):
    """A tag event's start time comes through; other labels carry none."""
    path = tmp_path / "labels.csv"
    path.write_text(
        "deployment-id,label,event-from\n"
        "A,dead,\n"
        "B,tag-event,2013-02-03T23:00:00+00:00\n",
        encoding="utf-8",
    )
    labels = read_labels(path)
    assert labels["A"] == Override(DEAD)
    assert labels["B"] == Override(
        TAG_EVENT, datetime(2013, 2, 3, 23, tzinfo=timezone.utc)
    )


@pytest.mark.parametrize(
    "row",
    ["A,tag-event,", "A,dead,2013-02-03T23:00:00+00:00"],
    ids=["missing", "extra"],
)
def test_read_labels_ties_event_from_to_tag_events(tmp_path, row):
    """A tag event without a start, or a start on another label, is refused."""
    path = tmp_path / "labels.csv"
    path.write_text(f"deployment-id,label,event-from\n{row}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="event-from"):
        read_labels(path)


def test_committed_labels_cover_the_named_tag_events():
    """The stuck, grounded and sighted birds are tag events with evidence."""
    path = Path(__file__).resolve().parents[2] / "data" / "labels.csv"
    labels = read_labels(path)
    assert labels["EAX_BLVU_121786"].event_from == datetime(
        2015, 5, 31, 21, tzinfo=timezone.utc
    )
    assert labels["CAT_BLVU_121784"].event_from == datetime(
        2013, 2, 3, 23, tzinfo=timezone.utc
    )
    assert labels["VPC_BLVU_283"].event_from == datetime(
        2016, 9, 30, 12, 56, 4, tzinfo=timezone.utc
    )
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            assert row["basis"].strip() and row["evidence"].strip()


def test_tag_event_label_overrides_ambiguous_end():
    """A sighted bird's still tail is a tag event, not a possible death."""
    overrides = {"A": Override(TAG_EVENT, EVENT_FROM)}
    ended = deployment(end_type="transmission-end")
    assert label_for(ended, overrides, 400 * HOUR, DAY) == TAG_EVENT


def test_build_truth_carries_the_event_start():
    """Only an overridden tag event gets a start time."""
    deployments = [deployment(i) for i in ("A", "B")]
    fixes = [
        Fix(i, START + n * HOUR, -19.0, 15.0) for i in ("A", "B") for n in range(3)
    ]
    truths = build_truth(
        "jackals", deployments, fixes, {"A": Override(TAG_EVENT, EVENT_FROM)}
    )
    assert [t.event_from for t in truths] == [EVENT_FROM, None]
    assert truths[0].outcome_start == EVENT_FROM
    assert truths[1].outcome_start == truths[1].still_start


@pytest.mark.parametrize(
    "resolved, expected",
    [
        (None, TAG_EVENT),
        (EVENT_FROM + HOUR, TAG_EVENT),
        (EVENT_FROM, "false"),
        (EVENT_FROM - HOUR, "false"),
    ],
)
def test_classify_credits_tag_events_only_from_their_start(resolved, expected):
    """An alert that ended before the event began stays false."""
    alert = incident(MORTALITY, START, resolved=resolved)
    assert classify(tag_truth(), alert) == expected


def test_tag_event_uses_event_start_not_death_start():
    """An alert open after the final still period but not the event is false."""
    record = tag_truth()
    assert record.still_start < EVENT_FROM
    alert = incident(MORTALITY, START, resolved=record.still_start + HOUR)
    assert classify(record, alert) == "false"
    assert false_mortality(record, [alert]) == 1


def test_three_outcomes_score_differently_by_tier():
    """Tag events are correct for the watch and baseline, wrong for death."""
    dead, tagged = truth(), tag_truth("B")
    alive = Truth(**{**dead.__dict__, "deployment_id": "C", "label": ALIVE})
    own = {
        (i, detector): [
            replace(
                incident(detector, START + HOUR),
                deployment_id=i,
                incident_id=f"{i}:{detector}",
            )
        ]
        for i in ("A", "B", "C")
        for detector in (MORTALITY, POTENTIAL_DEATH, GAP)
    }
    truths = [dead, tagged, alive]
    for detector in (MORTALITY, GAP):
        watch = precision(truths, own, detector)
        assert (watch["true"], watch[TAG_EVENT], watch["false"]) == (1, 1, 1)
        assert watch["judged"] == 3
        assert watch["correct"] == 2
        assert watch["precision"] == 0.667
        assert watch["death_precision"] == 0.333
    escalated = precision(truths, own, POTENTIAL_DEATH)
    assert escalated[TAG_EVENT] == 1
    assert escalated["judged"] == 3
    assert escalated["correct"] == 1
    assert escalated["precision"] == 0.333


def test_ceiling_counts_tag_events_as_not_deaths():
    """Crediting tag events must not lift the death ceiling."""
    dead, tagged = truth(), tag_truth("B")
    incidents = [
        replace(incident(MORTALITY, START + HOUR), deployment_id=i, incident_id=i)
        for i in ("A", "B")
    ]
    scored = evaluate([dead, tagged], incidents, None)["precision"][MORTALITY]
    assert scored["precision"] == 1.0
    assert scored["ceiling"] == 0.5


def test_random_baseline_credits_tag_windows_only_on_request():
    """The tag-crediting baseline adds event time; the death one does not."""
    alive = Truth(**{**truth().__dict__, "label": ALIVE})
    tagged = tag_truth("B")
    assert random_precision([alive, tagged]) == 0.0
    assert random_precision([alive, tagged], tag_events_correct=True) == round(
        30 / 120, 4
    )
