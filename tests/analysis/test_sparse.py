"""Tests for the sparse-tag mark measurement."""

from datetime import datetime, timedelta, timezone

from telemetry.analysis.sparse import Case, baseline_rate, choose, threshold_row

START = datetime(2020, 5, 1, tzinfo=timezone.utc)
DAY = timedelta(days=1)
GATE = {"thresholds_per_day": [2.0, 4.0, 6.0], "max_true_marked": 1}


def case(rate: float | None, kind: str | None = "false", found: bool = False) -> Case:
    """A watch alert on bird A with the given baseline rate and outcome."""
    return Case("A", rate, natal=False, kind=kind, found=found)


def test_baseline_rate_counts_fixes_before_the_run_only():
    """Fixes on or after the run start do not count towards the baseline."""
    times = [START + timedelta(hours=6 * n) for n in range(4 * 20)]
    run = START + 10 * DAY
    assert baseline_rate(times, run, 7, 2) == 4.0


def test_baseline_rate_uses_tracked_days_for_a_young_track():
    """A track younger than the span is divided by its own tracked days."""
    times = [START + timedelta(hours=12 * n) for n in range(10)]
    assert baseline_rate(times, START + 3 * DAY, 7, 2) == 2.0


def test_baseline_rate_is_undefined_under_the_minimum():
    """Under the minimum tracked days there is no value, so no mark."""
    times = [START + timedelta(hours=n) for n in range(30)]
    assert baseline_rate(times, START + DAY, 7, 2) is None
    assert not case(None).marked(100.0)


def test_mark_is_strictly_below_the_threshold():
    """A rate equal to the threshold is not marked."""
    assert case(1.9).marked(2.0) and not case(2.0).marked(2.0)


def test_choose_takes_the_highest_passing_threshold():
    """The rule picks the highest threshold within the carcass limit in every population."""
    rows = lambda counts: [
        {"threshold_per_day": t, "newly_marked_true_found": n}
        for t, n in zip(GATE["thresholds_per_day"], counts)
    ]
    ok = [{"rows": rows([0, 1, 2])}, {"rows": rows([0, 0, 1])}]
    assert choose(ok, GATE) == 4.0
    assert choose([{"rows": rows([2, 2, 2])}], GATE) is None


def test_threshold_row_counts_marked_carcasses_and_hidden_deaths():
    """A marked true alert on a found bird is counted, and its death hidden."""

    class Truth:  # pylint: disable=too-few-public-methods
        """A stand-in bird tracked for 30 days."""

        deployment_id = "A"
        first_fix = START
        last_fix = START + 30 * DAY

    cases = [case(1.0, "true", found=True), case(1.0), case(20.0)]
    row = threshold_row(cases, [Truth()], 2.0, timedelta(days=30))
    assert row["newly_marked"] == 2 and row["newly_marked_true_found"] == 1
    assert row["unmarked"] == 1 and row["load_unmarked"] == 1.0
    assert row["deaths_only_marked"] == 1
    reference = threshold_row(cases, [Truth()], None, timedelta(days=30))
    assert reference["newly_marked"] == 0 and reference["deaths_only_marked"] == 0
