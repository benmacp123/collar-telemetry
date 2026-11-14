"""Tests for sorting long still bouts into classes, on hand-built tracks."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from telemetry.analysis.bouts import (
    CLASSES,
    TITLES,
    LongBout,
    Rules,
    classify,
    long_bouts,
    markdown,
    measure,
)
from telemetry.analysis.evaluation import build_truth
from telemetry.analysis.experiment import experiment
from telemetry.core.fixes import Deployment, Fix
from telemetry.core.geo import offset

START = datetime(2014, 6, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
MONTH = timedelta(days=30)
STORK = "Ciconia ciconia"
NEST = (47.75, 8.93)
RULES = Rules(
    departure_radius_m=500.0,
    sparse_fixes_per_day=6.0,
    natal_radius_m=500.0,
    natal_days=365,
    site_radius_m=200.0,
    site_years=2,
    site_bouts=3,
    breeding_months=frozenset({3, 4, 5}),
    breeding_min_lat=44.0,
    marks_hours=(72.0, 168.0),
)


def track(deployment_id, pattern):
    """A stork track from ``pattern``.

    Args:
        deployment_id: The deployment.
        pattern: Steps in order: ("sit", metres east of the nest, hours,
            hours between fixes) jitters 10 m about one place, and
            ("walk", hours) moves 1 km north every hour.

    Returns:
        tuple: (truth, fixes in time order).
    """
    deployment = Deployment(
        deployment_id, "tag", deployment_id, STORK, START, None, None
    )
    fixes, hour, walked = [], 0, 0
    for step in pattern:
        if step[0] == "walk":
            for _ in range(step[1]):
                walked += 1
                point = offset(*NEST, 0.0, 1000.0 * walked)
                fixes.append(Fix(deployment_id, START + hour * HOUR, *point))
                hour += 1
            continue
        _, east_m, hours, every = step
        place = offset(*NEST, 90.0, east_m)
        for i in range(0, hours, every):
            point = offset(*place, 0.0 if i // every % 2 else 180.0, 10.0)
            fixes.append(Fix(deployment_id, START + (hour + i) * HOUR, *point))
        hour += hours
    truth = build_truth("storks-bavaria", [deployment], fixes, {})[0]
    return truth, fixes


def bout(**changes):
    """A departed, well-fixed bout at the nest in April of year two.

    Args:
        **changes: Fields to replace.

    Returns:
        LongBout: The bout.
    """
    base = LongBout(
        deployment_id="A",
        start=datetime(2016, 4, 10, tzinfo=timezone.utc),
        hours=40.0,
        fixes=30,
        lat=NEST[0],
        lon=NEST[1],
        from_start_m=20_000.0,
        age=timedelta(days=680),
        departed=True,
    )
    return replace(base, **changes)


def test_long_bouts_keeps_only_bouts_past_the_window():
    """A 20 h sit is under the stork window and is not a long bout; the
    nest stay before it is."""
    truth, fixes = track("A", [("sit", 0, 60, 1), ("walk", 5), ("sit", 9000, 20, 1)])
    found = long_bouts(truth, fixes, RULES)
    assert [(b.hours, b.departed) for b in found] == [(59.0, False)]


def test_a_stay_in_the_nest_before_leaving_is_a_nestling_bout():
    """A bout that starts before the first departure is the nestling
    class, however long or well fixed it is."""
    truth, fixes = track("A", [("sit", 0, 60, 1), ("walk", 30)])
    found = long_bouts(truth, fixes, RULES)
    assert [classify(b, found, RULES) for b in found] == ["nestling"]


def test_a_return_to_the_nest_in_the_first_year_is_a_natal_return():
    """After leaving, a long stay back at the tagging place is classed by
    place, not as a nestling."""
    truth, fixes = track(
        "A", [("sit", 0, 60, 1), ("walk", 5), ("sit", 0, 40, 1), ("walk", 5)]
    )
    found = long_bouts(truth, fixes, RULES)
    assert [classify(b, found, RULES) for b in found] == ["nestling", "natal_return"]


def test_a_tag_fixing_twice_a_day_makes_a_sparse_bout():
    """Twelve-hourly fixes at one place away from the nest are put down
    to the tag, and the rate is fixes over the bout's own length."""
    # The walk at the end keeps the stay from being the track's final
    # still period, which is left out as a possible carcass.
    pattern = [("sit", 0, 30, 1), ("walk", 5), ("sit", 9000, 120, 12), ("walk", 5)]
    truth, fixes = track("A", pattern)
    found = long_bouts(truth, fixes, RULES)
    assert found[-1].fixes_per_day < 3
    assert classify(found[-1], found, RULES) == "sparse"


def test_sparse_is_tested_before_place():
    """A sparse bout at the natal nest is still sparse: the tag would show
    no departure wherever the bird sat."""
    sparse = bout(from_start_m=10.0, age=timedelta(days=30), fixes=5, hours=40.0)
    assert classify(sparse, [sparse], RULES) == "sparse"


def test_a_site_used_in_two_years_in_spring_is_a_breeding_site():
    """Two long bouts 50 m apart in different years make a repeat site,
    and season and latitude decide which kind."""
    first = bout()
    lat, lon = offset(*NEST, 90.0, 50.0)
    later = bout(start=datetime(2017, 4, 2, tzinfo=timezone.utc), lat=lat, lon=lon)
    assert classify(first, [first, later], RULES) == "breeding_site"
    winter = bout(start=datetime(2017, 12, 2, tzinfo=timezone.utc))
    assert classify(winter, [first, winter], RULES) == "other_site"
    south = (36.0, -5.6)
    spanish = [
        bout(
            start=datetime(year, 4, 2, tzinfo=timezone.utc), lat=south[0], lon=south[1]
        )
        for year in (2016, 2017)
    ]
    assert classify(spanish[0], spanish, RULES) == "other_site"


def test_a_site_used_three_times_in_one_year_is_a_season_site():
    """Three bouts at one place in one calendar year are a single-year
    site; two are not enough and fall to one-off."""
    days = (1, 8, 15)
    same_year = [
        bout(start=datetime(2016, 4, day, tzinfo=timezone.utc)) for day in days
    ]
    assert classify(same_year[0], same_year, RULES) == "season_site"
    assert classify(same_year[0], same_year[:2], RULES) == "one_off"


def test_a_bout_far_from_the_birds_others_is_a_one_off():
    """Other bouts beyond the site radius do not make a repeat site."""
    here = bout()
    lat, lon = offset(*NEST, 90.0, 250.0)
    there = bout(start=datetime(2017, 4, 2, tzinfo=timezone.utc), lat=lat, lon=lon)
    assert classify(here, [here, there], RULES) == "one_off"


def test_spread_is_the_median_of_the_hours_inside_the_bout():
    """Only hours between the bout's first and last fix count, and a
    track with no readings gives None."""
    truth, fixes = track("A", [("sit", 0, 30, 1), ("walk", 5)])
    spread = {START + h * HOUR: float(h) for h in range(40)}
    assert long_bouts(truth, fixes, RULES, spread)[0].spread == 14.5
    assert long_bouts(truth, fixes, RULES)[0].spread is None


def test_measure_counts_each_bout_once_and_rates_use_the_whole_set():
    """Class counts add up to the total, and rates divide by every
    deployment's tracked time, bout or no bout."""
    a_truth, a_fixes = track(
        "A", [("sit", 0, 60, 1), ("walk", 5), ("sit", 0, 80, 1), ("walk", 5)]
    )
    b_truth, b_fixes = track("B", [("walk", 150)])
    result = measure([a_truth, b_truth], a_fixes + b_fixes, RULES, MONTH)
    counts = {row["class"]: row["bouts"] for row in result["classes"]}
    assert counts == {**dict.fromkeys(CLASSES, 0), "nestling": 1, "natal_return": 1}
    assert result["all"]["bouts"] == 2
    assert result["animal_months"] == round((149 + 149) / 720, 1)
    natal = next(r for r in result["classes"] if r["class"] == "natal_return")
    assert natal["share"] == 0.5
    assert [mark["count"] for mark in natal["beyond"]] == [1, 0]
    assert natal["by_month"][5] == 1 and sum(natal["by_month"]) == 1
    assert natal["per_animal_month"] == round(1 / ((149 + 149) / 720), 4)


def test_markdown_has_a_row_for_every_class_and_quotes_the_rules():
    """The table shows empty classes too, and the definitions carry the
    cut-offs in force."""
    truth, fixes = track("A", [("sit", 0, 60, 1), ("walk", 30)])
    entry = {"study": "s", "title": "Storks", **measure([truth], fixes, RULES, MONTH)}
    text = markdown([entry], RULES)
    for name in CLASSES:
        assert f"| Storks | {TITLES[name]} |" in text
    assert "Fewer than 6 fixes a day" in text
    assert "months 3, 4, 5" in text


def test_the_experiment_file_holds_every_rule():
    """The committed table builds the rules, so a missing or misspelt key
    fails here rather than in the script."""
    rules = Rules.from_table(experiment().descriptive["still_bouts"])
    assert rules.marks_hours == tuple(sorted(rules.marks_hours))
    assert rules.breeding_months <= frozenset(range(1, 13))
