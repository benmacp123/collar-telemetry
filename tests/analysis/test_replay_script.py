"""Tests for the held-out gate in ``scripts/replay.py``."""

import importlib.util
import sys
from pathlib import Path

import pytest

from telemetry.analysis.experiment import experiment
from telemetry.data.studies import STORKS

ROOT = Path(__file__).resolve().parents[2]


def _replay_script():
    """The replay script, loaded as a module.

    Returns:
        module: ``scripts/replay.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "replay_script", ROOT / "scripts" / "replay.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fresh() -> list:
    """The stork populations held out unseen.

    Returns:
        list: Populations whose set the experiment file marks fresh.
    """
    return [s for s in STORKS if experiment().is_fresh(s.group, s.split)]


def test_fresh_populations_are_not_replayed():
    """A routine replay covers tuning storks and no unseen held-out one."""
    replayed = {study.slug for study in _replay_script().REPLAYED}
    assert _fresh()
    assert replayed.isdisjoint(study.slug for study in _fresh())
    assert {"storks-sw-germany", "storks-bavaria", "vultures"} <= replayed


def test_a_fresh_population_cannot_be_named(monkeypatch):
    """``--study`` refuses a held-out population instead of replaying it."""
    script = _replay_script()
    monkeypatch.setattr(
        sys, "argv", ["replay.py", "--study", _fresh()[0].slug, "--scenario", "ideal"]
    )
    with pytest.raises(SystemExit):
        script.parse_args()
