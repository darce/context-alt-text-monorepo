"""FIRDV-2 S1 RED contracts for immutable experiment-run provenance."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.eval_harness.experiment_manifest as experiment_manifest
from scripts.bench.stack_pair import StackPairConfig, load_stack_pair
from scripts.bench.tests.conftest import valid_pair_dict, write_manifest, write_pair
from scripts.eval_harness.face_run_record import build_face_run_record, validate_face_run_record
from scripts.eval_harness.manifest import _SHA256_RE, SUPPORTED_MANIFEST_VERSION

RUN_ID = "fir-dv-2-red-run-001"
CREATED_AT = "2026-09-20T00:00:00+00:00"
HEAD_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _offline_head_sha_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the contract suite offline while still requiring the shared helper call."""

    def normalize(raw: str | None, **_kwargs: Any) -> str | None:
        if raw is None:
            return None
        normalized = raw.strip().lower()
        if normalized != HEAD_SHA:
            raise SystemExit("invalid test HEAD_SHA")
        return normalized

    monkeypatch.setattr(experiment_manifest, "normalize_head_sha", normalize)


def _materials(tmp_path: Path) -> tuple[dict[str, Any], StackPairConfig, dict[str, Any], str]:
    corpus_path = write_manifest(tmp_path / "corpus.json", [1, 2])
    corpus_payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    pair_path = write_pair(
        tmp_path / "stack-pair.yaml",
        valid_pair_dict(manifest_sha256=corpus_sha, item_max_attempts=3),
    )
    pair = load_stack_pair(pair_path)
    face_record = build_face_run_record([], provenance={"run_id": RUN_ID, "head_sha": HEAD_SHA})
    kwargs: dict[str, Any] = {
        "run_id": RUN_ID,
        "created_at": CREATED_AT,
        "head_sha": HEAD_SHA,
        "corpus_manifest": corpus_payload,
        "corpus_manifest_sha256": corpus_sha,
        "stack_pair": pair,
        "face_run_record": face_record,
        "aborted": False,
    }
    return kwargs, pair, corpus_payload, corpus_sha


def _build(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    kwargs, _pair, _corpus, _sha = _materials(tmp_path)
    kwargs.update(overrides)
    return experiment_manifest.build_experiment_manifest(**kwargs)


@pytest.mark.parametrize("missing", ["run_id", "created_at", "head_sha"])
def test_run_identity_requires_stable_id_created_at_and_head_sha(tmp_path: Path, missing: str) -> None:
    kwargs, _pair, _corpus, _sha = _materials(tmp_path)
    kwargs[missing] = None

    with pytest.raises(experiment_manifest.ExperimentManifestError):
        experiment_manifest.build_experiment_manifest(**kwargs)


def test_run_identity_is_preserved_across_rebuilds(tmp_path: Path) -> None:
    first = _build(tmp_path)
    second = _build(tmp_path)

    assert first.get("identity", {}).get("run_id") == RUN_ID
    assert second.get("identity", {}).get("run_id") == RUN_ID
    assert first.get("identity", {}).get("run_id") == second.get("identity", {}).get("run_id")


def test_head_sha_uses_existing_normalizer_and_stores_normalized_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str | None] = []

    def fake_normalize(raw: str | None, **_kwargs: Any) -> str | None:
        seen.append(raw)
        return None if raw is None else raw.strip().lower()

    monkeypatch.setattr(experiment_manifest, "normalize_head_sha", fake_normalize)
    document = _build(tmp_path, head_sha=HEAD_SHA.upper())

    assert seen == [HEAD_SHA.upper()]
    assert document.get("identity", {}).get("head_sha") == HEAD_SHA


@pytest.mark.parametrize("bad_head_sha", ["a" * 39, "not-a-git-sha"])
def test_head_sha_rejects_short_or_non_hex_values(tmp_path: Path, bad_head_sha: str) -> None:
    with pytest.raises((SystemExit, experiment_manifest.ExperimentManifestError)):
        _build(tmp_path, head_sha=bad_head_sha)


@pytest.mark.parametrize("bad_corpus_sha", ["a" * 63, "g" * 64])
def test_corpus_hash_uses_existing_sha256_shape_gate(tmp_path: Path, bad_corpus_sha: str) -> None:
    assert experiment_manifest._SHA256_RE is _SHA256_RE
    with pytest.raises(experiment_manifest.ExperimentManifestError):
        _build(tmp_path, corpus_manifest_sha256=bad_corpus_sha)


def test_config_provenance_records_corpus_hash_and_stack_pair_policy(tmp_path: Path) -> None:
    kwargs, pair, _corpus, corpus_sha = _materials(tmp_path)
    document = experiment_manifest.build_experiment_manifest(**kwargs)

    assert document.get("inputs", {}).get("corpus_manifest_sha256") == corpus_sha
    assert document.get("policy", {}).get("stack_pair") == {
        "primary_endpoint": pair.primary_endpoint,
        "secondary_endpoints": list(pair.secondary_endpoints),
        "head_to_head_delta": pair.head_to_head_delta,
        "accepted_set_floor": pair.accepted_set_floor,
        "max_differential_attrition": pair.max_differential_attrition,
        "bootstrap_seed": pair.bootstrap_seed,
        "item_max_attempts": pair.item_max_attempts,
        "manifest_sha256": pair.manifest_sha256,
    }


def test_config_provenance_refuses_corpus_hash_mismatch(tmp_path: Path) -> None:
    kwargs, _pair, _corpus, _sha = _materials(tmp_path)
    kwargs["corpus_manifest_sha256"] = "b" * 64

    with pytest.raises(experiment_manifest.ExperimentManifestError):
        experiment_manifest.build_experiment_manifest(**kwargs)


def test_version_adapter_reuses_existing_manifest_version_gate(tmp_path: Path) -> None:
    kwargs, _pair, corpus, _sha = _materials(tmp_path)
    unsupported = copy.deepcopy(corpus)
    unsupported["manifest_version"] = SUPPORTED_MANIFEST_VERSION + 1
    kwargs["corpus_manifest"] = unsupported

    with pytest.raises(Exception, match="unsupported manifest_version"):
        experiment_manifest.build_experiment_manifest(**kwargs)


def test_output_provenance_composes_and_round_trips_face_run_record(tmp_path: Path) -> None:
    kwargs, _pair, _corpus, _sha = _materials(tmp_path)
    document = experiment_manifest.build_experiment_manifest(**kwargs)
    document = experiment_manifest.validate_experiment_manifest(document)
    embedded = document.get("output", {}).get("face_run_record")

    assert embedded is not None
    assert validate_face_run_record(embedded) == embedded


def test_aborted_run_is_distinct_from_completed_zero_result_run(tmp_path: Path) -> None:
    kwargs, _pair, _corpus, _sha = _materials(tmp_path)
    completed_record = build_face_run_record([], provenance={"run_id": RUN_ID}, aborted=False)
    aborted_record = build_face_run_record([], provenance={"run_id": RUN_ID}, aborted=True)

    completed_kwargs = {**kwargs, "face_run_record": completed_record, "aborted": False}
    aborted_kwargs = {**kwargs, "face_run_record": aborted_record, "aborted": True}
    completed = experiment_manifest.build_experiment_manifest(**completed_kwargs)
    aborted = experiment_manifest.build_experiment_manifest(**aborted_kwargs)

    assert completed.get("execution", {}).get("status") == "completed"
    assert aborted.get("execution", {}).get("status") == "aborted"
    assert completed.get("output", {}).get("face_run_record", {}).get("items") == []
    assert aborted.get("output", {}).get("face_run_record", {}).get("aborted") is True
    assert completed != aborted
