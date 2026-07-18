"""FIR-3 S1: face_pipeline model provenance loader (fail-closed, no network).

Synthetic hashes only — never touches real ONNX model bytes.
See docs/tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md (S1).
Heuristics: rg-008 (validate at load), TEST-06/TEST-08.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from recognition.infrastructure.face_pipeline.provenance import (
    PENDING_OPERATOR_FETCH,
    MODEL_MANIFEST,
    ModelIntegrityError,
    ModelProvenance,
    load_verified_model,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_model(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def test_load_verified_model_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Temp file whose sha256 matches a synthetic manifest entry loads successfully."""
    payload = b"synthetic-yunet-bytes-v1"
    digest = _sha256(payload)
    file_name = "face_detection_yunet_2026may.onnx"
    _write_model(tmp_path, file_name, payload)

    entry = ModelProvenance(
        file_name=file_name,
        sha256=digest,
        source_url="https://example.test/yunet.onnx",
        source_ref="deadbeef" * 5,
        license_id="MIT",
        license_file="LICENSE.yunet",
        license_sha256=_sha256(b"MIT"),
        size_bytes=len(payload),
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    path = load_verified_model("yunet", models_dir=tmp_path)
    assert path == tmp_path / file_name
    assert path.is_file()


def test_load_verified_model_tampered_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tampered on-disk bytes refuse to load (rg-008 fail-closed)."""
    file_name = "face_detection_yunet_2026may.onnx"
    expected = b"expected-model-bytes"
    # Same length as expected so the size gate does not short-circuit; sha256 must fail.
    tampered = b"TAMPERED-model-bytes"
    assert len(tampered) == len(expected)
    _write_model(tmp_path, file_name, tampered)

    entry = ModelProvenance(
        file_name=file_name,
        sha256=_sha256(expected),
        source_url="https://example.test/yunet.onnx",
        source_ref="abc123",
        license_id="MIT",
        license_file="LICENSE.yunet",
        license_sha256=_sha256(b"MIT"),
        size_bytes=len(expected),
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelIntegrityError, match="sha256 mismatch"):
        load_verified_model("yunet", models_dir=tmp_path)


def test_load_verified_model_missing_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing on-disk model refuses to load."""
    file_name = "face_recognition_sface_2021dec.onnx"
    entry = ModelProvenance(
        file_name=file_name,
        sha256="a" * 64,
        source_url="https://example.test/sface.onnx",
        source_ref="abc123",
        license_id="Apache-2.0",
        license_file="LICENSE.sface",
        license_sha256="b" * 64,
        size_bytes=1,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "sface", entry)

    with pytest.raises(ModelIntegrityError, match="missing"):
        load_verified_model("sface", models_dir=tmp_path)


def test_load_verified_model_sentinel_hash_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PENDING_OPERATOR_FETCH sentinel never returns a path (AGT-02 no fabricated hashes)."""
    file_name = "face_detection_yunet_2026may.onnx"
    _write_model(tmp_path, file_name, b"any-bytes")

    entry = ModelProvenance(
        file_name=file_name,
        sha256=PENDING_OPERATOR_FETCH,
        source_url="https://example.test/yunet.onnx",
        source_ref="unresolved",
        license_id="MIT",
        license_file="LICENSE.yunet",
        license_sha256=PENDING_OPERATOR_FETCH,
        size_bytes=0,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "yunet", entry)

    with pytest.raises(ModelIntegrityError, match=PENDING_OPERATOR_FETCH):
        load_verified_model("yunet", models_dir=tmp_path)


def test_load_verified_model_unknown_name_raises(tmp_path: Path) -> None:
    """Unknown logical name is fail-closed (not KeyError)."""
    with pytest.raises(ModelIntegrityError, match="unknown model"):
        load_verified_model("not-a-model", models_dir=tmp_path)


def test_module_manifest_covers_yunet_and_sface() -> None:
    """Production manifest registers both models with required provenance fields."""
    assert set(MODEL_MANIFEST) == {"yunet", "sface"}
    for key, entry in MODEL_MANIFEST.items():
        assert isinstance(entry, ModelProvenance)
        assert entry.file_name.endswith(".onnx")
        assert entry.source_url
        assert entry.source_ref
        assert entry.license_id
        assert entry.license_file
        assert entry.sha256  # real hex or PENDING sentinel
        assert entry.license_sha256
        assert entry.size_bytes >= 0
        # Never invent: either 64-hex or explicit pending sentinel.
        assert entry.sha256 == PENDING_OPERATOR_FETCH or (
            len(entry.sha256) == 64 and all(c in "0123456789abcdef" for c in entry.sha256)
        )


def test_face_pipeline_import_purity() -> None:
    """face_pipeline must not import cv2, onnxruntime, worker, or HTTP layers (rg-013)."""
    import recognition.infrastructure.face_pipeline as pkg
    import recognition.infrastructure.face_pipeline.provenance as prov

    forbidden_substrings = (
        "cv2",
        "onnxruntime",
        "recognition.worker",
        "recognition.interface_adapters",
        "fastapi",
        "starlette",
    )
    for mod in (pkg, prov):
        for name, value in vars(mod).items():
            if isinstance(value, ModuleType):
                full = value.__name__ or ""
                for bad in forbidden_substrings:
                    assert bad not in full, f"{mod.__name__} imported {full}"


def _load_fetch_script() -> ModuleType:
    service_root = Path(__file__).resolve().parents[3]
    path = service_root / "scripts" / "fetch_face_pipeline_models.py"
    spec = importlib.util.spec_from_file_location("fetch_face_pipeline_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_script_download_failure_is_actionable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every I/O call has a degrade path: download failure raises typed error (not silent)."""
    fetch = _load_fetch_script()

    def _boom(url: str, dest: Path) -> None:  # noqa: ARG001
        raise fetch.ModelFetchError(f"download failed: {url}")

    monkeypatch.setattr(fetch, "download_file", _boom)
    with pytest.raises(fetch.ModelFetchError, match="download failed"):
        fetch.fetch_all(dest_dir=tmp_path)


def test_fetch_script_verifies_against_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful download of matching bytes lands files; hash mismatch refuses."""
    fetch = _load_fetch_script()
    yunet = MODEL_MANIFEST["yunet"]
    # Only exercise when real hashes are pinned (not pending sentinel).
    if yunet.sha256 == PENDING_OPERATOR_FETCH:
        pytest.skip("manifest still PENDING_OPERATOR_FETCH; operator fetch required")

    payload = b"x" * 16  # wrong bytes relative to production hash

    def _write_wrong(url: str, dest: Path) -> None:  # noqa: ARG001
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    monkeypatch.setattr(fetch, "download_file", _write_wrong)
    with pytest.raises((fetch.ModelFetchError, ModelIntegrityError)):
        fetch.fetch_all(dest_dir=tmp_path, models=("yunet",))
