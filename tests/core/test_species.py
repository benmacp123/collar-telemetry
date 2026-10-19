"""Tests for per-species settings."""

from datetime import timedelta

import pytest

from telemetry.core.alerts import default_merge_within
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
    """A reopen can only merge if the merge window outlasts the detector window."""
    merge = default_merge_within()["mortality"]
    assert all(p.mortality.window < merge for p in PROFILES.values())
