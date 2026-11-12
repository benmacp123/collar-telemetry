"""Tests for the study registry: the stork populations, their split and
the files each study names."""

import csv
import importlib.util
from pathlib import Path

from telemetry.data.studies import (
    SCORING,
    SPLITS_PATH,
    STORKS,
    STUDIES,
    TUNING,
    part_number,
    read_splits,
    tuning_storks,
)

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"


def test_stork_split_is_read_from_the_committed_file():
    """Each population's side is whatever ``data/splits.csv`` says, and
    every study the file splits is registered."""
    with open(SPLITS_PATH, newline="", encoding="utf-8") as handle:
        committed = {
            int(row["movebank-study-id"]): row["split"]
            for row in csv.DictReader(handle)
            if row["split"] != "excluded"
        }
    assert {study.study_id: study.split for study in STORKS} == committed
    assert read_splits()[332044860] == "excluded"


def test_tuning_storks_leave_every_held_out_population_out():
    """Only tuning populations are offered to routine runs."""
    assert tuning_storks()
    assert all(study.split == TUNING for study in tuning_storks())
    held_out = [study for study in STORKS if study not in tuning_storks()]
    assert held_out and all(study.split == SCORING for study in held_out)


def test_storks_are_kept_out_of_the_export_study_list():
    """Iterating ``STUDIES`` can never load a stork population."""
    assert {study.slug for study in STUDIES}.isdisjoint(s.slug for s in STORKS)
    assert all(study.group == "storks" for study in STORKS)
    assert all(study.group == study.slug for study in STUDIES)
    assert all(study.split is None for study in STUDIES)


def test_stork_stems_match_the_fetch_script():
    """The loader reads the file names the fetch script writes."""
    spec = importlib.util.spec_from_file_location(
        "fetch_movebank", ROOT / "scripts" / "fetch_movebank.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert {study.study_id: study.stem for study in STORKS} == script.STUDIES


def test_every_stork_population_has_its_files():
    """Each population's tables and GPS parts are committed; checked by
    name only, so no held-out file is opened."""
    for study in STORKS:
        assert study.reference_path(RAW).is_file()
        for table in ("individuals", "tags"):
            assert (RAW / "storks" / f"{study.stem}-{table}.csv").is_file()
        parts = study.event_paths(RAW)
        assert parts and all(part.name.endswith(".csv.gz") for part in parts)


def test_part_number_reads_gzip_parts():
    """A ``.csv.gz`` part sorts by its number, as a ``.csv`` part does."""
    assert part_number(Path("sw-germany-gps-10.csv.gz")) == 10
    assert part_number(Path("sw-germany-gps-2.csv.gz")) == 2


def test_a_tuning_population_loads_with_no_unmatched_rows():
    """Every committed fix of a tuning population joins a deployment."""
    study = min(tuning_storks(), key=lambda s: s.event_paths(RAW)[0].stat().st_size)
    deployments, fixes, report = study.load(RAW)
    assert report.rows == len(fixes) > 0
    assert {fix.deployment_id for fix in fixes} <= {
        deployment.deployment_id for deployment in deployments
    }
    assert {deployment.taxon for deployment in deployments} == {"Ciconia ciconia"}
    assert set(study.tag_models(RAW)) == {d.deployment_id for d in deployments}
