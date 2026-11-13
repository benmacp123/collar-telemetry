"""Tests for the frozen vulture flat-activity cue."""

from telemetry.analysis.activity import flat_activity
from telemetry.analysis.experiment import experiment


def test_a_constant_counter_is_flat():
    """Identical counts on two transmissions are what the manual calls a
    constant counter."""
    assert flat_activity([7, 7], experiment()) is True
    assert flat_activity([0, 0, 0, 0], experiment()) is True


def test_any_change_in_the_counter_is_not_flat():
    """The frozen range is zero, so a single count of difference fails."""
    assert flat_activity([7, 7, 8], experiment()) is False


def test_too_few_readings_is_unknown_not_false():
    """One reading, or blanks, cannot show constancy over two periods; the
    answer is None so the gap is counted apart from a moving counter."""
    assert flat_activity([7], experiment()) is None
    assert flat_activity([7, None, None], experiment()) is None
    assert flat_activity([], experiment()) is None


def test_blank_counts_are_not_readings():
    """A blank between two equal counts is skipped, not read as zero."""
    assert flat_activity([5, None, 5], experiment()) is True


def test_the_rule_is_frozen_unfitted_in_the_experiment_file():
    """The cue is committed as the manual states it: two transmissions,
    zero range, and marked as not fitted."""
    cue = experiment().cues["vulture_flat_activity"]
    assert cue["fitted"] is False
    assert (cue["min_transmissions"], cue["max_range"]) == (2, 0)
    assert "grid" not in cue
