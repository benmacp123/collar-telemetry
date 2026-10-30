"""Tests for the held-out gate in ``scripts/evaluate.py``.

The studies, the scoring and the plots are replaced with stand-ins, so the
tests check only which files a run writes, without the vulture data.
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from telemetry.analysis.evaluation import SCORING, TUNING

ROOT = Path(__file__).resolve().parents[2]


def _evaluate_script():
    """The evaluation script, loaded as a module.

    Returns:
        module: ``scripts/evaluate.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "evaluate_script", ROOT / "scripts" / "evaluate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scenario() -> dict:
    """The parts of one scenario's evaluation that the look log reads.

    Returns:
        dict: Precision, false-alert load and detection by the mark.
    """
    return {
        "precision": {
            "mortality": {"true": 1, "false": 3, "ambiguous": 0, "precision": 0.25},
            "potential_death": {
                "true": 1,
                "false": 1,
                "ambiguous": 0,
                "precision": 0.5,
            },
        },
        "false_mortality": {"incidents": 3, "per_animal_month": 0.3},
        "mortality": {"deaths": 1, "detected": 1, "rate_at_mark": 1.0},
    }


@pytest.fixture(name="script")
def fixture_script(tmp_path, monkeypatch):
    """The script pointed at a temporary results folder holding a scored
    held-out file and a look log, with one split study standing in.

    Returns:
        module: The patched script; ``written`` collects the reports
        passed to the Markdown writer.
    """
    module = _evaluate_script()
    results = tmp_path / "results"
    evaluation = results / "evaluation"
    evaluation.mkdir(parents=True)
    (evaluation / f"vultures-{SCORING}.json").write_text(
        '{"set": "scoring", "kept": true}\n', encoding="utf-8"
    )
    (results / "LOOKS.md").write_text("# Held-out looks\n", encoding="utf-8")
    study = SimpleNamespace(
        slug="vultures",
        title="Vultures",
        load=lambda raw: ([], [], None),
        fence=lambda raw: None,
    )
    truths = [
        SimpleNamespace(split=split, taxon="vulture", deployment_id=f"bird-{split}")
        for split in (TUNING, SCORING)
    ]
    module.written = []
    for name, value in {
        "ROOT": tmp_path,
        "RESULTS": results,
        "EVALUATION": evaluation,
        "LOOKS": results / "LOOKS.md",
        "STUDIES": [study],
        "VARIANTS": [],
        "read_labels": lambda path: {},
        "build_truth": lambda *args: truths,
        "reference_mark": lambda chosen: 92.5,
        "read_incidents": lambda path: [],
        "evaluate": lambda chosen, incidents, mark: _scenario(),
        "write_markdown": lambda reports, path: module.written.extend(reports),
        "write_figures": lambda reports, directory: None,
        "commit_label": lambda: "abc1234",
    }.items():
        monkeypatch.setattr(module, name, value)
    return module


def test_routine_run_keeps_the_held_out_file_and_log(script, monkeypatch):
    """Without ``--score`` the held-out file and look log stay byte for
    byte, yet the tables still include the last held-out scoring."""
    held_out = script.EVALUATION / f"vultures-{SCORING}.json"
    before = (held_out.read_bytes(), script.LOOKS.read_bytes())
    monkeypatch.setattr("sys.argv", ["evaluate.py"])
    script.main()
    assert (held_out.read_bytes(), script.LOOKS.read_bytes()) == before
    assert (script.EVALUATION / f"vultures-{TUNING}.json").exists()
    assert {"set": "scoring", "kept": True} in script.written


def test_score_rewrites_the_held_out_file_and_logs_one_look(script, monkeypatch):
    """``--score`` rescores the held-out set and appends exactly one look
    entry, carrying the commit and the reason given."""
    monkeypatch.setattr(
        "sys.argv", ["evaluate.py", "--score", "--why", "Tier field added."]
    )
    script.main()
    held_out = json.loads(
        (script.EVALUATION / f"vultures-{SCORING}.json").read_text(encoding="utf-8")
    )
    assert held_out["set"] == SCORING and "kept" not in held_out
    log = script.LOOKS.read_text(encoding="utf-8")
    entries = [line for line in log.splitlines() if line.startswith("## ")]
    assert len(entries) == 1 and entries[0].endswith(", abc1234")
    assert "Tier field added." in log


def test_score_without_a_reason_is_refused(script, monkeypatch):
    """A look cannot be logged without saying what changed."""
    monkeypatch.setattr("sys.argv", ["evaluate.py", "--score"])
    with pytest.raises(SystemExit):
        script.main()
    assert script.LOOKS.read_text(encoding="utf-8") == "# Held-out looks\n"
