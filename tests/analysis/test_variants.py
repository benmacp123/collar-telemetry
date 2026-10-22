"""Tests for the synthetic variants of the mammal studies."""

from telemetry.analysis.variants import VARIANTS
from telemetry.data.studies import STUDIES


def test_variants_are_the_mammal_studies_and_stay_out_of_studies():
    """Variants cover jackals and elephants and never join the real study list."""
    assert [v.base.slug for v in VARIANTS] == ["jackals", "elephants"]
    assert {v.slug for v in VARIANTS}.isdisjoint(s.slug for s in STUDIES)
    assert all(v.slug == f"{v.base.slug}-synthetic" for v in VARIANTS)
