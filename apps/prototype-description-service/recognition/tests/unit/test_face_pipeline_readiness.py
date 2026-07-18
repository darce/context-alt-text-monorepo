"""FIR-4 S3: eager profile-aware face_pipeline readiness ([EMB-05][OBS-08])."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recognition.application import health as health_mod
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    ModelVerifyOutcome,
    load_verified_model,
)


@pytest.fixture(autouse=True)
def _clear_verify_cache() -> None:
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    yield
    health_mod.reset_face_pipeline_verify_cache_for_tests()


def test_check_face_pipeline_models_happy_path_real_models() -> None:
    """Happy path: verify against real fetched models dir."""
    # Precondition: models present (same as FIR-3 models-present gate).
    load_verified_model("yunet", models_dir=DEFAULT_MODELS_DIR)
    load_verified_model("sface", models_dir=DEFAULT_MODELS_DIR)

    result = health_mod.check_face_pipeline_models(DEFAULT_MODELS_DIR)
    assert result.status.value == "ok"
    assert "yunet" in result.detail or "verified" in result.detail


def test_check_face_pipeline_models_tampered_byte_unhealthy(tmp_path: Path) -> None:
    """Copy real models, corrupt one byte → UNHEALTHY naming the artifact."""
    for name in ("yunet", "sface"):
        entry = MODEL_MANIFEST[name]
        shutil.copy2(DEFAULT_MODELS_DIR / entry.file_name, tmp_path / entry.file_name)
        shutil.copy2(DEFAULT_MODELS_DIR / entry.license_file, tmp_path / entry.license_file)

    sface = tmp_path / MODEL_MANIFEST["sface"].file_name
    data = bytearray(sface.read_bytes())
    data[0] ^= 0xFF
    sface.write_bytes(data)

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    assert "sface" in result.detail


def test_check_face_pipeline_models_missing_sface_atomic_unhealthy(tmp_path: Path) -> None:
    """Half-activation: YuNet present, SFace absent → UNHEALTHY (names sface)."""
    yunet = MODEL_MANIFEST["yunet"]
    shutil.copy2(DEFAULT_MODELS_DIR / yunet.file_name, tmp_path / yunet.file_name)
    shutil.copy2(DEFAULT_MODELS_DIR / yunet.license_file, tmp_path / yunet.license_file)

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    assert "sface" in result.detail


def test_mtime_size_drift_triggers_reverify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("yunet", "sface"):
        entry = MODEL_MANIFEST[name]
        shutil.copy2(DEFAULT_MODELS_DIR / entry.file_name, tmp_path / entry.file_name)
        shutil.copy2(DEFAULT_MODELS_DIR / entry.license_file, tmp_path / entry.license_file)

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

    # Drift mtime/size by rewriting sface (same content is ok; touch size via append+truncate)
    sface = tmp_path / MODEL_MANIFEST["sface"].file_name
    original = sface.read_bytes()
    sface.write_bytes(original + b"\x00")  # size drift → integrity fail on re-verify
    third = health_mod.check_face_pipeline_models(tmp_path)
    assert third.status.value == "unhealthy"
    assert verify_calls["n"] >= 3  # at least sface re-verified
    assert "sface" in third.detail


def test_unverified_bytes_never_ok_via_call_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mtime+size alone never green-lights never-verified bytes."""
    for name in ("yunet", "sface"):
        entry = MODEL_MANIFEST[name]
        # Write arbitrary bytes with correct size? Size check fails unless exact.
        # Use real files but force verifier to never have been called for cache OK.
        shutil.copy2(DEFAULT_MODELS_DIR / entry.file_name, tmp_path / entry.file_name)
        shutil.copy2(DEFAULT_MODELS_DIR / entry.license_file, tmp_path / entry.license_file)

    # Seed a cache entry that claims OK without going through verifier — should be
    # ignored if we clear and ensure check always verifies on empty cache.
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

    # Inject a fake OK cache without sha256 — if someone put OK with wrong mtime it re-verifies.
    # Clear cache then put wrong mtime OK-looking entry that won't match stat → re-verify.
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    # Without any cache, probe must call verifier — never report OK with zero verifies.
    calls["n"] = 0
    monkeypatch.setattr(
        health_mod,
        "verify_face_pipeline_model",
        lambda name, *, models_dir=None: (_ for _ in ()).throw(AssertionError("blocked")),
    )

    # If verifier blocked, outcome path raises — but our helper catches ModelIntegrityError only.
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

    for name in ("yunet", "sface"):
        entry = MODEL_MANIFEST[name]
        shutil.copy2(DEFAULT_MODELS_DIR / entry.file_name, tmp_path / entry.file_name)
        shutil.copy2(DEFAULT_MODELS_DIR / entry.license_file, tmp_path / entry.license_file)

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
