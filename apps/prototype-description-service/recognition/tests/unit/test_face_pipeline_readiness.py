"""FIR-4 S3: eager profile-aware face_pipeline readiness ([EMB-05][OBS-08]).

Real ONNX bytes are only required for the default-dir happy path. All other
cases use a synthetic MODEL_MANIFEST + small files so the no-models CI gate
still exercises control flow (cache, drift, tamper, probe branching).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recognition.application import health as health_mod
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    ModelProvenance,
    ModelVerifyOutcome,
    load_verified_model,
)
from recognition.tests.unit.face_pipeline_support import MODELS_PRESENT, MODELS_SKIP


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_entry(
    *,
    file_name: str,
    sha256: str,
    size_bytes: int,
    license_file: str,
    license_payload: bytes,
    embedding_dim: int | None = None,
    normalization: str | None = None,
    metric: str | None = None,
    license_id: str = "MIT",
) -> ModelProvenance:
    return ModelProvenance(
        file_name=file_name,
        sha256=sha256,
        source_url=f"https://example.test/{file_name}",
        source_ref="synthetic-readiness",
        license_id=license_id,
        license_file=license_file,
        license_sha256=_sha256(license_payload),
        size_bytes=size_bytes,
        framework="opencv",
        embedding_dim=embedding_dim,
        normalization=normalization,
        metric=metric,
    )


def _install_synthetic_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    yunet_payload: bytes = b"syn-yunet-v1",
    sface_payload: bytes = b"syn-sface-v1",
    write_yunet: bool = True,
    write_sface: bool = True,
    tamper_sface: bool = False,
) -> tuple[bytes, bytes]:
    """Install synthetic yunet+sface manifest entries and optional on-disk files."""
    yunet_name = "face_detection_yunet_2026may.onnx"
    sface_name = "face_recognition_sface_2021dec.onnx"
    yunet_lic_name = "LICENSE.yunet"
    sface_lic_name = "LICENSE.sface"
    yunet_lic = b"MIT-yunet-syn"
    sface_lic = b"Apache-sface-syn"

    expected_sface = sface_payload
    on_disk_sface = bytearray(sface_payload)
    if tamper_sface:
        on_disk_sface[0] ^= 0xFF
    on_disk_sface_b = bytes(on_disk_sface)

    monkeypatch.setitem(
        MODEL_MANIFEST,
        "yunet",
        _make_entry(
            file_name=yunet_name,
            sha256=_sha256(yunet_payload),
            size_bytes=len(yunet_payload),
            license_file=yunet_lic_name,
            license_payload=yunet_lic,
            embedding_dim=None,
        ),
    )
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "sface",
        _make_entry(
            file_name=sface_name,
            sha256=_sha256(expected_sface),
            size_bytes=len(expected_sface),
            license_file=sface_lic_name,
            license_payload=sface_lic,
            embedding_dim=128,
            normalization="l2",
            metric="cosine",
            license_id="Apache-2.0",
        ),
    )

    if write_yunet:
        (tmp_path / yunet_name).write_bytes(yunet_payload)
        (tmp_path / yunet_lic_name).write_bytes(yunet_lic)
    if write_sface:
        (tmp_path / sface_name).write_bytes(on_disk_sface_b)
        (tmp_path / sface_lic_name).write_bytes(sface_lic)

    return yunet_payload, expected_sface


@pytest.fixture(autouse=True)
def _clear_verify_cache() -> None:
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    yield
    health_mod.reset_face_pipeline_verify_cache_for_tests()


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
def test_check_face_pipeline_models_happy_path_real_models() -> None:
    """Happy path: verify against real fetched models dir (models-present only)."""
    load_verified_model("yunet", models_dir=DEFAULT_MODELS_DIR)
    load_verified_model("sface", models_dir=DEFAULT_MODELS_DIR)

    result = health_mod.check_face_pipeline_models(DEFAULT_MODELS_DIR)
    assert result.status.value == "ok"
    assert "yunet" in result.detail or "verified" in result.detail


def test_check_face_pipeline_models_happy_path_synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Modelless happy path via synthetic manifest (CI coverage without ONNX)."""
    _install_synthetic_pair(tmp_path, monkeypatch)
    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "ok"
    assert "yunet" in result.detail or "verified" in result.detail


def test_check_face_pipeline_models_tampered_byte_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Corrupt one byte → UNHEALTHY naming the artifact (synthetic bytes)."""
    _install_synthetic_pair(tmp_path, monkeypatch, tamper_sface=True)

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    assert "sface" in result.detail


def test_check_face_pipeline_models_missing_sface_atomic_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half-activation: YuNet present, SFace absent → UNHEALTHY (names sface)."""
    _install_synthetic_pair(tmp_path, monkeypatch, write_sface=False)

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    assert "sface" in result.detail


def test_mtime_size_drift_triggers_reverify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_synthetic_pair(tmp_path, monkeypatch)

    verify_calls = {"n": 0}
    real = health_mod.verify_face_pipeline_model

    def _counting(name: str, *, models_dir: Path | None = None):
        verify_calls["n"] += 1
        return real(name, models_dir=models_dir)

    monkeypatch.setattr(health_mod, "verify_face_pipeline_model", _counting)

    first = health_mod.check_face_pipeline_models(tmp_path)
    assert first.status.value == "ok"
    assert verify_calls["n"] == 2  # yunet + sface

    # Cache hit: no re-verify
    second = health_mod.check_face_pipeline_models(tmp_path)
    assert second.status.value == "ok"
    assert verify_calls["n"] == 2

    # Drift mtime/size by rewriting sface (size change → integrity fail on re-verify)
    sface = tmp_path / MODEL_MANIFEST["sface"].file_name
    original = sface.read_bytes()
    sface.write_bytes(original + b"\x00")
    third = health_mod.check_face_pipeline_models(tmp_path)
    assert third.status.value == "unhealthy"
    assert verify_calls["n"] >= 3  # at least sface re-verified
    assert "sface" in third.detail


def test_unverified_bytes_never_ok_via_call_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mtime+size alone never green-lights never-verified bytes."""
    _install_synthetic_pair(tmp_path, monkeypatch)

    health_mod.reset_face_pipeline_verify_cache_for_tests()
    calls = {"n": 0}
    real = health_mod.verify_face_pipeline_model

    def _count(name: str, *, models_dir: Path | None = None):
        calls["n"] += 1
        return real(name, models_dir=models_dir)

    monkeypatch.setattr(health_mod, "verify_face_pipeline_model", _count)
    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "ok"
    assert calls["n"] == 2  # must have verified both before OK

    # Without any cache, probe must call verifier — never report OK with zero verifies.
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    calls["n"] = 0

    def _never_ok(name: str, *, models_dir: Path | None = None):
        calls["n"] += 1
        root = models_dir or DEFAULT_MODELS_DIR
        return ModelVerifyOutcome(
            name=name,
            ok=False,
            reason="forced-unverified",
            path=root / MODEL_MANIFEST[name].file_name,
            mtime_ns=0,
            size=0,
        )

    monkeypatch.setattr(health_mod, "verify_face_pipeline_model", _never_ok)
    blocked = health_mod.check_face_pipeline_models(tmp_path)
    assert blocked.status.value == "unhealthy"
    assert calls["n"] == 2
    assert "forced-unverified" in blocked.detail


def test_register_health_probes_branches_on_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """register_health_probes uses face_pipeline check when profile is face_pipeline."""
    from unittest.mock import AsyncMock

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.main import register_health_probes
    from recognition.interface_adapters.http import deps as dependencies
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from recognition.interface_adapters.http.deps.circuit_breaker import (
        SessionDependencyCircuitBreaker,
        initialize_session_dependency_circuit_breaker,
    )

    _install_synthetic_pair(tmp_path, monkeypatch)

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))
    # Keep dim pair valid (default 512).
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)

    app = FastAPI()
    breaker = SessionDependencyCircuitBreaker(failure_threshold=3, window_seconds=30, half_open_after_seconds=10)
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)
    register_health_probes(app)

    async def _session_yielder():
        session = MagicMock()
        session.execute = AsyncMock(return_value=None)
        yield session

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    client = TestClient(app)

    resp = client.get("/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    mc = next(c for c in body["checks"] if c["name"] == "model_cache")
    assert mc["status"] == "ok"

    detailed = client.get("/health/detailed")
    assert detailed.status_code == 200
    dbody = detailed.json()
    assert dbody["model_cache"]["profile"] == "face_pipeline"
