"""Tests for per-species settings."""

from datetime import timedelta

import pytest

from telemetry.core.alerts import default_merge_within
from telemetry.core.pipeline import Overrides
from telemetry.core.species import PROFILES, profile_for


def test_every_study_taxon_has_a_profile():
    """Each taxon in the committed studies has settings."""
    for taxon in ("Cathartes aura", "Coragyps atratus", "Canis mesomelas"):
        assert profile_for(taxon).taxon == taxon
    assert profile_for("Loxodonta africana").max_speed_mps == 11.0


def test_unknown_taxon_is_an_error():
    """A missing profile fails loudly instead of borrowing another species'."""
    with pytest.raises(KeyError, match="no species profile"):
        profile_for("Panthera leo")


def test_cleaning_config_carries_species_limits():
    """The cleaner gets the species' speed limit and the caller's lateness."""
    config = profile_for("Canis mesomelas").cleaning(timedelta(hours=6))
    assert config.max_speed_mps == 17.0
    assert config.max_lateness == timedelta(hours=6)


def test_mortality_merge_window_exceeds_every_species_window():
    """A reopen can only merge if each species' merge window outlasts its
    detector window, a longer black-vulture window included."""
    for profile in PROFILES.values():
        merge = Overrides().lifecycle(profile).config.merge_within["mortality"]
        assert profile.mortality.window < merge
        assert merge >= default_merge_within()["mortality"]


def test_each_species_window_is_pinned():
    """Each species' mortality window, black vultures kept at 36 h by step 2.4."""
    hours = {
        taxon: profile.mortality.window / timedelta(hours=1)
        for taxon, profile in PROFILES.items()
    }
    assert hours == {
        "Cathartes aura": 36.0,
        "Coragyps atratus": 36.0,
        "Canis mesomelas": 24.0,
        "Loxodonta africana": 12.0,
    }
