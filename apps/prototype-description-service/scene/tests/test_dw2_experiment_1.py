"""Regression tests for DEFWAVE-2 experiment manifest findings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.eval_harness.experiment_manifest as experiment_manifest
from scripts.bench.stack_pair import load_stack_pair
from scripts.bench.tests.conftest import valid_pair_dict, write_manifest, write_pair
from scripts.eval_harness.face_run_record import build_face_run_record

RUN_ID = "dw2-experiment-1-run"
HEAD_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _offline_head_sha_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(experiment_manifest, "normalize_head_sha", lambda raw: raw)


def _manifest_materials(tmp_path: Path) -> dict[str, Any]:
    corpus_path = write_manifest(tmp_path / "corpus.json", [1, 2])
    corpus_manifest = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    pair_path = write_pair(
        tmp_path / "stack-pair.yaml",
        valid_pair_dict(manifest_sha256=corpus_sha, item_max_attempts=3),
    )
    return {
        "run_id": RUN_ID,
        "created_at": "2026-09-26T00:00:00+00:00",
        "head_sha": HEAD_SHA,
        "corpus_manifest": corpus_manifest,
        "corpus_manifest_sha256": corpus_sha,
        "stack_pair": load_stack_pair(pair_path),
        "face_run_record": build_face_run_record([], provenance={"run_id": RUN_ID}),
        "aborted": False,
    }


def test_validator_rejects_corpus_sha_that_disagrees_with_stack_pair_pin(tmp_path: Path) -> None:
    document = experiment_manifest.build_experiment_manifest(**_manifest_materials(tmp_path))
    document["inputs"]["corpus_manifest_sha256"] = "b" * 64

    with pytest.raises(experiment_manifest.ExperimentManifestError, match="pin mismatch"):
        experiment_manifest.validate_experiment_manifest(document)


def test_builder_rejects_aborted_flag_that_disagrees_with_run_record(tmp_path: Path) -> None:
    kwargs = _manifest_materials(tmp_path)
    kwargs["face_run_record"] = build_face_run_record([], aborted=True)

    with pytest.raises(experiment_manifest.ExperimentManifestError, match="aborted"):
        experiment_manifest.build_experiment_manifest(**kwargs)


def test_builder_rejects_non_boolean_aborted_flag(tmp_path: Path) -> None:
    kwargs = _manifest_materials(tmp_path)
    kwargs["aborted"] = "false"

    with pytest.raises(experiment_manifest.ExperimentManifestError, match="boolean"):
        experiment_manifest.build_experiment_manifest(**kwargs)


def test_validator_rejects_status_that_disagrees_with_run_record(tmp_path: Path) -> None:
    kwargs = _manifest_materials(tmp_path)
    kwargs["face_run_record"] = build_face_run_record([], aborted=True)
    kwargs["aborted"] = True
    document = experiment_manifest.build_experiment_manifest(**kwargs)
    document["execution"]["status"] = "completed"

    with pytest.raises(experiment_manifest.ExperimentManifestError, match="aborted"):
        experiment_manifest.validate_experiment_manifest(document)
