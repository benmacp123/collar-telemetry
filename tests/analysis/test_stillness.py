"""Tests for living still-bout measurement on hand-built tracks."""

from datetime import datetime, timedelta, timezone

from telemetry.analysis.evaluation import (
    ANIMAL_MONTH,
    TAG_EVENT,
    Override,
    build_truth,
)
from telemetry.analysis.report import stillness_markdown
from telemetry.analysis.stillness import (
    THRESHOLDS_H,
    living_bouts,
    measure,
    still_bouts,
)
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset
from telemetry.core.species import profile_for

START = datetime(2009, 3, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
JACKAL = "Canis mesomelas"
ELEPHANT = "Loxodonta africana"


def track(deployment_id, pattern, taxon=JACKAL, end_type=None):
    """Hourly fixes from ``pattern``: ("walk", h) moves 300 m an hour, ("sit", h) jitters 10 m.

    Returns:
        tuple: (deployment, fixes).
    """
    deployment = Deployment(
        deployment_id, "tag", deployment_id, taxon, START, None, end_type
    )
    lat, lon = -19.0, 15.5
    fixes, hour = [], 0
    for kind, hours in pattern:
        for i in range(hours):
            if kind == "walk":
                lat, lon = offset(lat, lon, 0.0, 300.0)
                point = (lat, lon)
            else:
                point = offset(lat, lon, 90.0 if i % 2 else 270.0, 10.0)
            fixes.append(Fix(deployment_id, START + hour * HOUR, *point))
            hour += 1
    return deployment, fixes


def truth_for(deployment, fixes, label=None, event_from=None):
    """The deployment's Truth, with an optional label override."""
    overrides = {deployment.deployment_id: Override(label, event_from)} if label else {}
    return build_truth("jackals", [deployment], fixes, overrides)[0]


def test_still_bouts_finds_a_sit_between_walks():
    """A 40 h sit between walks is one bout, counting the arrival fix."""
    _, fixes = track("A", [("walk", 20), ("sit", 40), ("walk", 20)])
    bouts = still_bouts(fixes, profile_for(JACKAL).mortality)
    longest = max(bouts, key=lambda b: b.hours)
    assert (longest.hours, longest.fixes) == (40.0, 41)


def test_living_bouts_drop_short_clusters():
    """Clusters with fewer fixes than the detector needs are not bouts."""
    deployment, fixes = track("A", [("walk", 20), ("sit", 4), ("walk", 20)])
    assert living_bouts(truth_for(deployment, fixes), fixes) == []


def test_living_bouts_drop_a_dead_tracks_final_period():
    """A dead track's final stillness may be a carcass, so it is left out."""
    pattern = [("walk", 20), ("sit", 30), ("walk", 20), ("sit", 100)]
    deployment, fixes = track("A", pattern, end_type="dead")
    truth = truth_for(deployment, fixes, label="dead")
    assert living_bouts(truth, fixes) == [30.0]


def test_living_bouts_drop_everything_after_a_tag_event_began():
    """A stuck tag's stillness, even mid-track, is not an animal resting."""
    pattern = [("walk", 20), ("sit", 30), ("walk", 20), ("sit", 500), ("walk", 20)]
    deployment, fixes = track("A", pattern)
    truth = truth_for(deployment, fixes, TAG_EVENT, START + 70 * HOUR)
    assert living_bouts(truth, fixes) == [30.0]


def test_living_bouts_keep_an_alive_tracks_final_period():
    """An animal known alive was alive through its last stillness too."""
    pattern = [("walk", 20), ("sit", 30), ("walk", 20), ("sit", 100)]
    deployment, fixes = track("A", pattern)
    truth = truth_for(deployment, fixes, label="alive")
    assert living_bouts(truth, fixes) == [30.0, 100.0]


def test_measure_counts_beyond_each_threshold_per_animal_month():
    """Counts and rates use bouts strictly longer than each threshold."""
    deployment, fixes = track(
        "A", [("walk", 20), ("sit", 50), ("walk", 20), ("sit", 24)]
    )
    truth = truth_for(deployment, fixes, label="alive")
    group = measure([truth], fixes, {"A": "collar"})["groups"][0]
    months = (truth.last_fix - truth.first_fix) / ANIMAL_MONTH
    counts = {b["hours"]: b["count"] for b in group["beyond"]}
    assert [counts[h] for h in THRESHOLDS_H] == [2, 1, 1, 1, 0, 0]
    assert group["beyond"][0]["per_animal_month"] == round(2 / months, 4)
    assert group["beyond_window"] == {
        "hours": 24.0,
        "count": 1,
        "per_animal_month": round(1 / months, 4),
    }


def test_measure_splits_by_taxon_and_tag_only_where_they_differ():
    """Rows by taxon appear only for mixed sets, by tag only within a mixed taxon."""
    sets = [
        track("A", [("sit", 30)]),
        track("B", [("sit", 30)]),
        track("C", [("sit", 30)], ELEPHANT),
    ]
    truths = [truth_for(d, f, label="alive") for d, f in sets]
    fixes = [fix for _, f in sets for fix in f]
    groups = measure(truths, fixes, {"A": "argos", "B": "solar", "C": "argos"})[
        "groups"
    ]
    keys = [(g["taxon"], g["tag_model"]) for g in groups]
    assert keys == [
        (None, None),
        (JACKAL, None),
        (JACKAL, "argos"),
        (JACKAL, "solar"),
        (ELEPHANT, None),
    ]


def test_measure_lists_carcass_periods():
    """A dead track's long final stillness is reported as a carcass period."""
    deployment, fixes = track("A", [("walk", 20), ("sit", 100)], end_type="dead")
    truth = truth_for(deployment, fixes, label="dead")
    assert measure([truth], fixes, {"A": "collar"})["carcasses"]["hours"] == [100.0]


def test_stillness_markdown_names_species_and_tags():
    """Single-species rows use the common name and the short tag name."""
    deployment, fixes = track("A", [("sit", 30)])
    truth = truth_for(deployment, fixes, label="alive")
    result = measure([truth], fixes, {"A": "Argos PTT GPS transmitter"})
    text = stillness_markdown([{"study": "jackals", "set": "all", **result}])
    assert "| jackals all | Black-backed jackal | Argos PTT | 1 |" in text
    assert "| jackals all | none | 0.0000 |" in text
