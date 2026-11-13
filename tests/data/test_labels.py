"""Tests for the stork rows of ``data/labels.csv``: that each is well
formed, points at a real deployment and quotes the recorded comment."""

import csv
from pathlib import Path

import pytest

from telemetry.analysis.evaluation import read_labels
from telemetry.data.studies import STORKS

ROOT = Path(__file__).resolve().parents[2]
LABELS = ROOT / "data" / "labels.csv"
RAW = ROOT / "data" / "raw"
GRADES = {"found", "reported", "acc-inferred"}


def _rows() -> list[dict]:
    """Read every row of the label file.

    Returns:
        list[dict]: One dict per row, keyed by column name.
    """
    with open(LABELS, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _stork_comments() -> dict[str, tuple[str, str]]:
    """Map each stork deployment to its animal's death comment.

    Returns:
        dict[str, tuple[str, str]]: Deployment ID to (population slug,
        the animal's ``death_comments`` with whitespace collapsed).
    """
    found = {}
    for study in STORKS:
        base = RAW / "storks"
        with open(
            base / f"{study.stem}-individuals.csv", newline="", encoding="utf-8"
        ) as handle:
            comments = {
                row["id"]: " ".join(row["death_comments"].split())
                for row in csv.DictReader(handle)
            }
        with open(
            base / f"{study.stem}-deployments.csv", newline="", encoding="utf-8"
        ) as handle:
            for row in csv.DictReader(handle):
                found[row["id"]] = (study.slug, comments.get(row["individual_id"], ""))
    return found


def test_label_file_is_accepted_by_the_evaluator():
    """The reader that scoring uses takes the whole file, new column
    included, so a malformed label fails here and not mid-run."""
    assert len(read_labels(LABELS)) == len(_rows())


def test_every_stork_label_has_a_grade_and_nothing_else_does():
    """Stork rows carry one known evidence grade; the vulture and mammal
    rows, labelled before grades existed, carry none."""
    comments = _stork_comments()
    for row in _rows():
        if row["deployment-id"] in comments:
            assert row["grade"] in GRADES, row["deployment-id"]
        else:
            assert row["grade"] == "", row["deployment-id"]


def test_stork_labels_quote_the_recorded_comment_verbatim():
    """Evidence is the animal's own death comment, unedited, so a label
    cannot drift from the record it claims to rest on."""
    comments = _stork_comments()
    for row in _rows():
        if row["deployment-id"] in comments:
            assert row["evidence"] == comments[row["deployment-id"]][1]


def test_deployment_ids_are_unique():
    """A deployment has one label, since the reader keys on its ID."""
    ids = [row["deployment-id"] for row in _rows()]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("slug", [study.slug for study in STORKS])
def test_each_population_has_labelled_deaths(slug):
    """No population was missed in the review."""
    comments = _stork_comments()
    assert any(
        comments.get(row["deployment-id"], ("", ""))[0] == slug for row in _rows()
    )
