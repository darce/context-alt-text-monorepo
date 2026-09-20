"""FIRDV-3 S1a RED contract for the declarable AuraFace embedding space.

These tests are intentionally offline.  They describe the provenance and
required-model seam that the production implementation must add, while using
small synthetic files for every integrity branch that needs bytes.
"""

from __future__ import annotations

import hashlib
import importlib.util
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.infrastructure.face_pipeline import provenance
from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    PENDING_OPERATOR_FETCH,
    ModelIntegrityError,
    ModelMissingError,
    ModelProvenance,
    load_verified_model,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[3]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_fetch_script() -> ModuleType:
    path = _SERVICE_ROOT / "scripts" / "fetch_face_pipeline_models.py"
    spec = importlib.util.spec_from_file_location("fetch_face_pipeline_models_firdv3", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _auraface_entry() -> ModelProvenance:
    entry = MODEL_MANIFEST.get("auraface")
    assert entry is not None, "MODEL_MANIFEST must declare the candidate auraface space"
    return entry


def _preprocessing(entry: ModelProvenance) -> Any:
    """Read the named optional preprocessing record without importing a future symbol."""
    for field_name in ("preprocessing", "input_preprocessing"):
        value = getattr(entry, field_name, None)
        if value is not None:
            return value
    pytest.fail("auraface ModelProvenance must attach an input-preprocessing record")


def _synthetic_auraface_entry(
    entry: ModelProvenance,
    *,
    expected_model: bytes,
    expected_license: bytes,
    expected_size: int | None = None,
) -> ModelProvenance:
    return replace(
        entry,
        sha256=_sha256(expected_model),
        size_bytes=len(expected_model) if expected_size is None else expected_size,
        license_sha256=_sha256(expected_license),
    )


def test_model_provenance_declares_frozen_typed_preprocessing_record() -> None:
    """Preprocessing is a typed optional sub-record, not an embedding-field overload."""
    provenance_fields = {field.name: field for field in fields(ModelProvenance)}
    field_name = next(
        (name for name in ("preprocessing", "input_preprocessing") if name in provenance_fields),
        None,
    )
    assert field_name is not None, "ModelProvenance needs an optional preprocessing field"
    assert provenance_fields[field_name].default is None

    input_preprocessing = getattr(provenance, "InputPreprocessing", None)
    assert input_preprocessing is not None, "the preprocessing sub-record must be named InputPreprocessing"
    assert is_dataclass(input_preprocessing)
    params = getattr(input_preprocessing, "__dataclass_params__", None)
    assert params is not None and params.frozen, "InputPreprocessing must be frozen"
    assert {
        "input_size",
        "channel_order",
        "input_scale",
        "alignment_template_id",
        "output_l2_normalized",
    } <= {field.name for field in fields(input_preprocessing)}


def test_auraface_manifest_is_declarable_and_operator_pinned() -> None:
    """AuraFace metadata is present without pretending its bytes were locally hashed."""
    entry = _auraface_entry()

    assert entry.file_name.endswith(".onnx")
    assert entry.source_url
    assert entry.source_ref
    assert entry.license_id
    assert entry.license_file
    assert entry.size_bytes == 260_694_151
    assert entry.embedding_dim == 512
    assert entry.framework
    assert entry.normalization
    assert entry.metric
    assert entry.sha256 == PENDING_OPERATOR_FETCH
    assert entry.license_sha256 == PENDING_OPERATOR_FETCH


def test_auraface_preprocessing_is_rgb_arcface_family_and_declared() -> None:
    entry = _auraface_entry()
    preprocessing = _preprocessing(entry)

    assert tuple(preprocessing.input_size) == (112, 112)
    assert preprocessing.channel_order == "RGB"
    assert preprocessing.input_scale is not None
    assert isinstance(preprocessing.alignment_template_id, str)
    assert preprocessing.alignment_template_id.strip()
    assert "sface" not in preprocessing.alignment_template_id.lower()
    assert isinstance(preprocessing.output_l2_normalized, bool)

    sface_preprocessing = getattr(MODEL_MANIFEST["sface"], "preprocessing", None)
    if sface_preprocessing is not None:
        assert preprocessing.alignment_template_id != sface_preprocessing.alignment_template_id


def test_pending_auraface_pin_is_missing_not_loadable(tmp_path: Path) -> None:
    _auraface_entry()

    with pytest.raises(ModelMissingError, match=PENDING_OPERATOR_FETCH):
        load_verified_model("auraface", models_dir=tmp_path)


def test_auraface_model_sha256_mismatch_refuses_synthetic_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _auraface_entry()
    expected_model = b"0123456789abcdef"
    actual_model = b"fedcba9876543210"
    license_payload = b"synthetic-license"
    synthetic = _synthetic_auraface_entry(
        entry,
        expected_model=expected_model,
        expected_license=license_payload,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", synthetic)
    (tmp_path / synthetic.file_name).write_bytes(actual_model)
    (tmp_path / synthetic.license_file).write_bytes(license_payload)

    with pytest.raises(ModelIntegrityError, match="sha256 mismatch"):
        load_verified_model("auraface", models_dir=tmp_path)


def test_auraface_size_mismatch_refuses_synthetic_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _auraface_entry()
    model_payload = b"synthetic-aura-model"
    license_payload = b"synthetic-license"
    synthetic = _synthetic_auraface_entry(
        entry,
        expected_model=model_payload,
        expected_license=license_payload,
        expected_size=len(model_payload) + 1,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", synthetic)
    (tmp_path / synthetic.file_name).write_bytes(model_payload)
    (tmp_path / synthetic.license_file).write_bytes(license_payload)

    with pytest.raises(ModelIntegrityError, match="size mismatch"):
        load_verified_model("auraface", models_dir=tmp_path)


def test_auraface_missing_license_refuses_synthetic_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _auraface_entry()
    model_payload = b"synthetic-aura-model"
    license_payload = b"expected-license"
    synthetic = _synthetic_auraface_entry(
        entry,
        expected_model=model_payload,
        expected_license=license_payload,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", synthetic)
    (tmp_path / synthetic.file_name).write_bytes(model_payload)

    with pytest.raises(ModelMissingError, match="license file missing"):
        load_verified_model("auraface", models_dir=tmp_path)


def test_auraface_license_hash_mismatch_refuses_synthetic_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _auraface_entry()
    model_payload = b"synthetic-aura-model"
    expected_license = b"expected-license"
    synthetic = _synthetic_auraface_entry(
        entry,
        expected_model=model_payload,
        expected_license=expected_license,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", synthetic)
    (tmp_path / synthetic.file_name).write_bytes(model_payload)
    (tmp_path / synthetic.license_file).write_bytes(b"wrong-license")

    with pytest.raises(ModelIntegrityError, match="license sha256 mismatch"):
        load_verified_model("auraface", models_dir=tmp_path)


def test_auraface_embedding_manifest_wire_form_is_structurally_parsed() -> None:
    """The candidate id keeps its full name token and parses only the @ suffix."""
    entry = _auraface_entry()
    assert entry.embedding_dim is not None
    assert entry.normalization is not None
    assert entry.metric is not None

    manifest = EmbeddingModelManifest(
        framework=entry.framework,
        name="glintr100",
        dimensions=entry.embedding_dim,
        normalization=entry.normalization,
        metric=entry.metric,
    )
    name_part, suffix = manifest.model_id.rsplit("@", 1)
    dimensions, normalization, metric = suffix.split("/", 2)

    assert name_part.startswith(f"{entry.framework}-")
    assert dimensions.endswith("d")
    assert int(dimensions[:-1]) == 512
    assert normalization == entry.normalization
    assert metric == entry.metric


def test_sface_embedding_manifest_regression_is_still_128d() -> None:
    """Adding a candidate space does not alter the incumbent SFace wire shape."""
    from recognition.infrastructure.embeddings.face_pipeline_adapter import sface_embedding_model_manifest

    entry = MODEL_MANIFEST["sface"]
    manifest = sface_embedding_model_manifest()
    name_part, suffix = manifest.model_id.rsplit("@", 1)
    dimensions, normalization, metric = suffix.split("/", 2)

    expected_name = f"{entry.framework}-sface+{provenance.numeric_runtime_fingerprint().space_token}"
    assert name_part == expected_name
    assert int(dimensions[:-1]) == entry.embedding_dim == 128
    assert normalization == entry.normalization == "l2"
    assert metric == entry.metric == "cosine"


def test_fetch_and_verify_defaults_are_exactly_the_live_baseline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A declarable candidate must not become a gate-preflight requirement."""
    fetch = _load_fetch_script()
    candidate = ModelProvenance(
        file_name="synthetic-auraface.onnx",
        sha256=PENDING_OPERATOR_FETCH,
        source_url="https://example.test/auraface.onnx",
        source_ref="pinned-revision",
        license_id="Apache-2.0",
        license_file="LICENSE.auraface",
        license_sha256=PENDING_OPERATOR_FETCH,
        size_bytes=1,
        framework="insightface",
        embedding_dim=512,
        normalization="l2",
        metric="cosine",
    )
    candidate_manifest = dict(fetch.MODEL_MANIFEST)
    candidate_manifest["auraface"] = candidate
    monkeypatch.setattr(fetch, "MODEL_MANIFEST", candidate_manifest)

    fetched: list[str] = []

    def _fake_fetch_one(name: str, *, dest_dir: Path) -> Path:
        fetched.append(name)
        return dest_dir / name

    monkeypatch.setattr(fetch, "fetch_one", _fake_fetch_one)
    fetch.fetch_all(dest_dir=tmp_path)
    assert tuple(fetched) == ("yunet", "sface")

    verified: list[str] = []

    def _fake_load_verified(name: str, *, models_dir: Path) -> Path:
        verified.append(name)
        return models_dir / name

    monkeypatch.setattr(fetch, "load_verified_model", _fake_load_verified)
    fetch.verify_only(dest_dir=tmp_path)
    assert tuple(verified) == ("yunet", "sface")


def test_verify_face_pipeline_models_keeps_candidate_out_of_gate_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate = ModelProvenance(
        file_name="synthetic-auraface.onnx",
        sha256=PENDING_OPERATOR_FETCH,
        source_url="https://example.test/auraface.onnx",
        source_ref="pinned-revision",
        license_id="Apache-2.0",
        license_file="LICENSE.auraface",
        license_sha256=PENDING_OPERATOR_FETCH,
        size_bytes=1,
        framework="insightface",
        embedding_dim=512,
        normalization="l2",
        metric="cosine",
    )
    monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", candidate)
    verified: list[str] = []

    def _fake_verify(name: str, *, models_dir: Path | None = None) -> object:
        verified.append(name)
        return object()

    monkeypatch.setattr(provenance, "verify_face_pipeline_model", _fake_verify)
    provenance.verify_face_pipeline_models(models_dir=tmp_path)

    assert tuple(verified) == ("yunet", "sface")


def test_fetch_cli_accepts_explicit_auraface_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = _load_fetch_script()
    selected: list[tuple[str, ...] | None] = []

    def _fake_verify_only(*, dest_dir: Path | None = None, models: tuple[str, ...] | None = None) -> list[Path]:
        selected.append(models)
        return []

    monkeypatch.setattr(fetch, "verify_only", _fake_verify_only)
    result = fetch.main(
        ["--dest", str(tmp_path), "--verify-only", "--models", "auraface"],
    )

    assert result == 0
    assert selected == [("auraface",)]
