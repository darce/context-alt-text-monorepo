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


def _align_dims_to_sface(monkeypatch: pytest.MonkeyPatch) -> None:
    """SFace manifest is 128-d; readiness three-way guard needs matching env."""
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
    monkeypatch.setenv("PGVECTOR_DIM", "128")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _live_face_pipeline_adapter():
    """Resolve face_pipeline_adapter from live sys.modules (not package attrs)."""
    import importlib

    return importlib.import_module("recognition.infrastructure.embeddings.face_pipeline_adapter")


def _stub_shared_runtime_loader(monkeypatch: pytest.MonkeyPatch, models_dir: Path | None = None) -> None:
    """Avoid real ORT session construction for synthetic-byte readiness tests."""
    fpa = _live_face_pipeline_adapter()
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    def loader(*, models_dir: Path, **kwargs: object) -> object:
        return fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=fpa.sface_embedding_model_manifest(),
            models_dir=models_dir,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )

    # String form → importlib.import_module → live sys.modules entry production uses.
    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter._load_face_pipeline_runtime",
        loader,
    )


@pytest.fixture(autouse=True)
def _clear_verify_cache() -> None:
    fpa = _live_face_pipeline_adapter()

    health_mod.reset_face_pipeline_verify_cache_for_tests()
    health_mod._persisted_embedding_models_for_ready.set(None)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    yield
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    health_mod._persisted_embedding_models_for_ready.set(None)
    fpa = _live_face_pipeline_adapter()
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
def test_check_face_pipeline_models_happy_path_real_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: verify against real fetched models dir (models-present only)."""
    _align_dims_to_sface(monkeypatch)
    load_verified_model("yunet", models_dir=DEFAULT_MODELS_DIR)
    load_verified_model("sface", models_dir=DEFAULT_MODELS_DIR)

    result = health_mod.check_face_pipeline_models(DEFAULT_MODELS_DIR)
    assert result.status.value == "ok"
    assert "yunet" in result.detail or "verified" in result.detail


def test_check_face_pipeline_models_happy_path_synthetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Modelless happy path via synthetic manifest (CI coverage without ONNX)."""
    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)
    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "ok"
    assert "yunet" in result.detail or "verified" in result.detail


def test_check_face_pipeline_models_dim_mismatch_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E-03: verified models + env dim != manifest 128 → UNHEALTHY with dim reason."""
    _install_synthetic_pair(tmp_path, monkeypatch)
    # Defaults / explicit 512 disagree with SFace-128.
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "512")
    monkeypatch.setenv("PGVECTOR_DIM", "512")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    assert "dimension" in result.detail.lower() or "mismatch" in result.detail.lower()


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
    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)

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


def test_license_only_drift_triggers_unhealthy_without_model_byte_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FINALB-04 [EMB-05][DRIFT-02][OBS-08]: LICENSE.sface drift invalidates readiness.

    After one successful synthetic model+license verification, tampering or
    deleting only the license file (model bytes untouched) must make the next
    probe UNHEALTHY and name sface/license. Cache freshness must restat license
    identity — not only model mtime/size — while still avoiding full model
    rehash on every healthy probe when both artifacts are stable.
    """
    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)

    model_hash_calls = {"n": 0}
    # Count full model-file sha256 via provenance helper used by load_verified_model.
    import recognition.infrastructure.face_pipeline.provenance as prov_mod

    real_sha = prov_mod._file_sha256

    def _counting_sha(path: Path) -> str:
        # Only count model ONNX hashes (not license) so healthy re-probes stay cheap.
        if path.suffix == ".onnx" or path.name.endswith(".onnx"):
            model_hash_calls["n"] += 1
        return real_sha(path)

    monkeypatch.setattr(prov_mod, "_file_sha256", _counting_sha)

    first = health_mod.check_face_pipeline_models(tmp_path)
    assert first.status.value == "ok", first.detail
    hashes_after_first = model_hash_calls["n"]
    assert hashes_after_first >= 2  # yunet + sface model bytes verified once

    # Stable re-probe: model + license unchanged → must not rehash large model
    # on every healthy hit (efficient cache intent preserved).
    second = health_mod.check_face_pipeline_models(tmp_path)
    assert second.status.value == "ok", second.detail
    assert model_hash_calls["n"] == hashes_after_first, (
        "healthy re-probe must not rehash model bytes when model+license identity "
        f"is stable; hashes first={hashes_after_first} second={model_hash_calls['n']}"
    )

    # Tamper only LICENSE.sface — model ONNX bytes and mtime/size untouched.
    sface_lic = tmp_path / MODEL_MANIFEST["sface"].license_file
    assert sface_lic.is_file()
    sface_model = tmp_path / MODEL_MANIFEST["sface"].file_name
    model_before = sface_model.read_bytes()
    sface_lic.write_bytes(sface_lic.read_bytes() + b"\n#tampered-license\n")

    third = health_mod.check_face_pipeline_models(tmp_path)
    assert third.status.value == "unhealthy", (
        f"license-only drift must flip readiness UNHEALTHY; got status={third.status.value!r} detail={third.detail!r}"
    )
    detail_l = third.detail.lower()
    assert "sface" in detail_l, f"detail must name sface: {third.detail!r}"
    assert "license" in detail_l, f"detail must name license: {third.detail!r}"
    # Model bytes truly unchanged (contract is license identity, not model rewrite).
    assert sface_model.read_bytes() == model_before

    # Delete-only path: restore valid license then remove it entirely.
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    _install_synthetic_pair(tmp_path, monkeypatch)  # rewrite clean pair
    _stub_shared_runtime_loader(monkeypatch, tmp_path)
    ok_again = health_mod.check_face_pipeline_models(tmp_path)
    assert ok_again.status.value == "ok", ok_again.detail

    lic_path = tmp_path / MODEL_MANIFEST["sface"].license_file
    model_path = tmp_path / MODEL_MANIFEST["sface"].file_name
    model_snapshot = model_path.read_bytes()
    lic_path.unlink()
    assert model_path.read_bytes() == model_snapshot

    deleted = health_mod.check_face_pipeline_models(tmp_path)
    assert deleted.status.value == "unhealthy", deleted.detail
    deleted_l = deleted.detail.lower()
    assert "sface" in deleted_l
    assert "license" in deleted_l


def test_unverified_bytes_never_ok_via_call_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """mtime+size alone never green-lights never-verified bytes."""
    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)

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


class _NestedSavepointCM:
    """Async context manager for session.begin_nested() on readiness session mocks."""

    def __init__(self, session: _TxnAwareSession) -> None:
        self._session = session

    async def __aenter__(self) -> _NestedSavepointCM:
        self._session._in_savepoint = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        self._session._in_savepoint = False
        # Savepoint rollback recovers the outer txn; do not leave it aborted.
        return False


class _TxnAwareSession:
    """Session mock that aborts the outer txn when execute fails outside a savepoint.

    Mirrors PostgreSQL: a failed statement aborts the enclosing transaction unless
    isolated by a savepoint (begin_nested). Used to prove GR-01 / GR-10 wiring.
    """

    def __init__(
        self,
        *,
        typmod_rows: list[tuple[str, str, int]],
        distinct_rows: list[tuple[str, ...]] | None = None,
        distinct_error: BaseException | None = None,
    ) -> None:
        from unittest.mock import AsyncMock

        self._typmod_rows = typmod_rows
        self._distinct_rows = distinct_rows if distinct_rows is not None else []
        self._distinct_error = distinct_error
        self._aborted = False
        self._in_savepoint = False
        self.begin_nested_calls = 0
        self.execute = AsyncMock(side_effect=self._execute)

    def begin_nested(self) -> _NestedSavepointCM:
        self.begin_nested_calls += 1
        return _NestedSavepointCM(self)

    async def _execute(self, stmt, *args, **kwargs):  # noqa: ANN001, ANN002
        if self._aborted and not self._in_savepoint:
            raise RuntimeError("InFailedSqlTransaction: current transaction is aborted")

        sql = str(getattr(stmt, "text", stmt))
        if "DISTINCT" in sql.upper() and "embedding_model" in sql:
            if self._distinct_error is not None:
                if not self._in_savepoint:
                    self._aborted = True
                raise self._distinct_error
            result = MagicMock()
            result.all = MagicMock(return_value=list(self._distinct_rows))
            result.fetchall = MagicMock(return_value=list(self._distinct_rows))
            return result

        result = MagicMock()
        result.all = MagicMock(return_value=list(self._typmod_rows))
        result.fetchall = MagicMock(return_value=list(self._typmod_rows))
        return result


def _identity_typmod_rows() -> list[tuple[str, str, int]]:
    from db.settings import get_database_settings

    dim = int(get_database_settings().pgvector_dimension)
    return [
        ("media_identities", "embedding", dim),
        ("identity_cluster_representatives", "embedding", dim),
        ("mv_identity_cluster_centroids", "centroid", dim),
    ]


def _standalone_ready_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session_factory=None,  # noqa: ANN001
):
    """Minimal FastAPI with health probes + open session/auth (no full create_app)."""
    from fastapi import FastAPI

    from api.main import register_health_probes
    from recognition.interface_adapters.http import deps as dependencies
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from recognition.interface_adapters.http.deps.circuit_breaker import (
        SessionDependencyCircuitBreaker,
        initialize_session_dependency_circuit_breaker,
    )

    app = FastAPI()
    breaker = SessionDependencyCircuitBreaker(failure_threshold=3, window_seconds=30, half_open_after_seconds=10)
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)
    register_health_probes(app)

    async def _default_session_yielder():
        # Live pgvector typmod probe (FINALA-02): return matching identity columns.
        # Distinct embedding_model probe (CVUP1-PR-03): empty = fresh deploy, not partition.
        yield _TxnAwareSession(typmod_rows=_identity_typmod_rows(), distinct_rows=[])

    yielder = session_factory if session_factory is not None else _default_session_yielder
    app.dependency_overrides[dependencies.get_observability_session] = yielder

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    return app


def test_register_health_probes_branches_on_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """register_health_probes uses face_pipeline check when profile is face_pipeline."""
    from fastapi.testclient import TestClient

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))

    app = _standalone_ready_app(monkeypatch)
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


def test_ready_face_pipeline_dim_mismatch_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """E2E-03: /ready UNHEALTHY when models verify but env dims != SFace-128."""
    from fastapi.testclient import TestClient

    _install_synthetic_pair(tmp_path, monkeypatch)
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "512")
    monkeypatch.setenv("PGVECTOR_DIM", "512")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()

    app = _standalone_ready_app(monkeypatch)
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "unhealthy"
    mc = next(c for c in body["checks"] if c["name"] == "model_cache")
    assert mc["status"] == "unhealthy"
    assert "dimension" in mc["detail"].lower() or "mismatch" in mc["detail"].lower()


def test_model_probe_verify_runs_off_event_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """S3CR-03: face_pipeline verify must not run on the event-loop thread."""
    import asyncio
    import threading

    from fastapi.testclient import TestClient

    import api.main as api_main

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))

    verify_threads: list[int] = []
    loop_threads: list[int] = []
    real = health_mod.verify_face_pipeline_model
    real_to_thread = asyncio.to_thread

    def _record_thread(name: str, *, models_dir: Path | None = None):
        verify_threads.append(threading.get_ident())
        return real(name, models_dir=models_dir)

    async def _spy_to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
        loop_threads.append(threading.get_ident())
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(health_mod, "verify_face_pipeline_model", _record_thread)
    monkeypatch.setattr(api_main.asyncio, "to_thread", _spy_to_thread)

    app = _standalone_ready_app(monkeypatch)
    client = TestClient(app)

    resp = client.get("/ready")
    assert resp.status_code == 200, resp.text
    assert verify_threads, "verify_face_pipeline_model must run for face_pipeline probe"
    assert loop_threads, "asyncio.to_thread must be used for face_pipeline model probe"
    assert all(vtid != ltid for vtid in verify_threads for ltid in loop_threads), (
        f"verify ran on event-loop thread; loop={loop_threads} verify={verify_threads}"
    )


def test_ready_invalid_profile_returns_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """S3CR-04: invalid profile → /ready 503 with named model_cache detail (not 500)."""
    from fastapi.testclient import TestClient

    # Register with a valid default so RegistrationSettings() succeeds, then
    # flip the env so the per-probe profile re-read sees the bad value.
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_PROFILE", raising=False)
    app = _standalone_ready_app(monkeypatch)
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "not_a_real_profile")

    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "unhealthy"
    mc = next(c for c in body["checks"] if c["name"] == "model_cache")
    assert mc["status"] == "unhealthy"
    assert "invalid face_pipeline profile" in mc["detail"]
    assert "not_a_real_profile" in mc["detail"]


def test_check_face_pipeline_models_ort_construction_failure_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local finding GROKHARM-04 [OBS-08, EMB-05, SERVE-01]: hashes + dims alone are insufficient.

    For face_pipeline profile, readiness must prove ORT session / shared runtime
    construction. Valid verified files with InferenceSession construction failure
    must return UNHEALTHY with a runtime-unavailable reason (not OK).
    """
    fpa = _live_face_pipeline_adapter()

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    def boom_loader(*, models_dir: Path, **kwargs: object) -> object:
        raise RuntimeError("InferenceSession construction failed: synthetic ORT boom")

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter._load_face_pipeline_runtime",
        boom_loader,
    )

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "unhealthy"
    detail = result.detail.lower()
    assert "runtime" in detail or "unavailable" in detail or "inferencesession" in detail
    fpa.reset_shared_face_pipeline_runtime_for_tests()


def test_check_face_pipeline_models_healthy_implies_usable_shared_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """local finding GROKHARM-04: healthy ready must correspond to a usable shared runtime.

    Readiness and serve path must not diverge — a successful check must go
    through (or populate) get_shared_face_pipeline_runtime so serve can reuse it.
    """
    fpa = _live_face_pipeline_adapter()

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    load_calls = 0
    mock_runtime = fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=fpa.sface_embedding_model_manifest(),
        models_dir=tmp_path,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )

    def loader(*, models_dir: Path, **kwargs: object) -> object:
        nonlocal load_calls
        load_calls += 1
        return mock_runtime

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter._load_face_pipeline_runtime",
        loader,
    )

    result = health_mod.check_face_pipeline_models(tmp_path)
    assert result.status.value == "ok"
    assert load_calls >= 1, "readiness must construct/prove shared runtime, not only hashes+dims"

    shared = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert shared is mock_runtime
    fpa.reset_shared_face_pipeline_runtime_for_tests()


def test_check_active_embedding_model_degrades_on_space_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CVUP1-PR-03: active model_id matching zero persisted rows → DEGRADED.

    If the check regressed to resolve-only always-OK, this assertion goes red:
    persisted rows carry a foreign model_id while active resolves to another.
    """
    from recognition.application import health as health_mod
    from shared.health import HealthStatus

    active = "opencv-sface+cv5.0.0/ort1.28@128d/l2/cosine"
    stale = "opencv-sface+cv4.13.0.92/ort1.22@128d/l2/cosine"

    monkeypatch.setattr(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        lambda: active,
    )

    # Auth-gated detail (verbose=True) keeps full space tokens for operators.
    partitioned = health_mod.check_active_embedding_model(persisted_model_ids=[stale], verbose=True)
    assert partitioned.status is HealthStatus.DEGRADED, partitioned.detail
    assert partitioned.name == "embedding_model"
    assert "partition" in partitioned.detail.lower() or "matches no persisted" in partitioned.detail
    assert active in partitioned.detail
    assert stale in partitioned.detail

    # Public path (verbose=False): status identical, detail coarse (no raw ids).
    public = health_mod.check_active_embedding_model(persisted_model_ids=[stale])
    assert public.status is HealthStatus.DEGRADED, public.detail
    assert active not in public.detail
    assert stale not in public.detail
    assert "active_space=" in public.detail
    assert "persisted_spaces=1" in public.detail

    # Matching active among persisted → OK (not a partition).
    matched = health_mod.check_active_embedding_model(persisted_model_ids=[stale, active], verbose=True)
    assert matched.status is HealthStatus.OK, matched.detail

    # Empty embeddings table is a fresh deploy, not a partition.
    fresh = health_mod.check_active_embedding_model(persisted_model_ids=[], verbose=True)
    assert fresh.status is HealthStatus.OK, fresh.detail

    # Probe unavailable (None) keeps prior resolve-only OK behaviour.
    no_probe = health_mod.check_active_embedding_model(persisted_model_ids=None, verbose=True)
    assert no_probe.status is HealthStatus.OK, no_probe.detail
    assert no_probe.detail.startswith("active=")


@pytest.mark.asyncio
async def test_check_database_contextvar_wires_partition_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CVUP1-GR-10: check_database → ContextVar → check_active_embedding_model (no kwarg).

    Production /ready never passes persisted_model_ids=; it relies on the stash
    filled by check_database. This must reach DEGRADED on a real partition.
    """
    from shared.health import HealthStatus

    active = "opencv-sface+cv5.0.0/ort1.28@128d/l2/cosine"
    stale = "opencv-sface+cv4.13.0.92/ort1.22@128d/l2/cosine"

    monkeypatch.setattr(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        lambda: active,
    )
    health_mod._persisted_embedding_models_for_ready.set(None)

    session = _TxnAwareSession(
        typmod_rows=_identity_typmod_rows(),
        distinct_rows=[(stale,)],
    )
    db = await health_mod.check_database(session)
    assert db.status is HealthStatus.OK, db.detail

    # No explicit kwarg — production wiring via ContextVar only.
    emb = health_mod.check_active_embedding_model()
    assert emb.status is HealthStatus.DEGRADED, emb.detail
    assert "partition" in emb.detail.lower() or "matches no persisted" in emb.detail
    assert emb.name == "embedding_model"


@pytest.mark.asyncio
async def test_check_database_distinct_failure_does_not_poison_typmod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CVUP1-GR-01/GR-10: DISTINCT probe raise must not flip database UNHEALTHY.

    Without a savepoint the failed DISTINCT aborts the outer txn and the
    subsequent typmod probe raises InFailedSqlTransaction → UNHEALTHY.
    With begin_nested, check_database stays OK (resolve-only partition skip).
    """
    from shared.health import HealthStatus

    session = _TxnAwareSession(
        typmod_rows=_identity_typmod_rows(),
        distinct_error=RuntimeError("relation media_identities does not exist"),
    )
    db = await health_mod.check_database(session)
    assert db.status is HealthStatus.OK, db.detail
    assert "vector dimension probe failed" not in db.detail
    assert session.begin_nested_calls >= 1
    # Stash cleared so partition check falls back to resolve-only.
    emb = health_mod.check_active_embedding_model()
    assert emb.status is HealthStatus.OK, emb.detail


def test_ready_distinct_probe_failure_still_200(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CVUP1-GR-10: /ready stays 200 when DISTINCT probe raises (savepoint isolation).

    This assertion fails against unfixed code where the poisoned txn makes
    check_database UNHEALTHY and aggregate /ready 503.
    """
    from fastapi.testclient import TestClient

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch, tmp_path)
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))

    async def _session_yielder():
        yield _TxnAwareSession(
            typmod_rows=_identity_typmod_rows(),
            distinct_error=RuntimeError("relation media_identities does not exist"),
        )

    app = _standalone_ready_app(monkeypatch, session_factory=_session_yielder)
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] in {"ok", "degraded"}
    db = next(c for c in body["checks"] if c["name"] == "database")
    assert db["status"] == "ok", db


@pytest.mark.asyncio
async def test_savepoint_allows_typmod_after_distinct_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CVUP1-GR-10: typmod probe succeeds after DISTINCT has raised inside savepoint."""
    from shared.health import HealthStatus

    session = _TxnAwareSession(
        typmod_rows=_identity_typmod_rows(),
        distinct_error=RuntimeError("permission denied for table media_identities"),
    )
    db = await health_mod.check_database(session)
    assert db.status is HealthStatus.OK, db.detail
    assert "reachable" in db.detail or "pgvector_dimension" in db.detail
    assert session.begin_nested_calls >= 1
    # Outer txn not aborted — a follow-up execute still works.
    follow = await session.execute("SELECT 1")
    assert follow is not None
    assert follow.all() == list(_identity_typmod_rows())


def test_ready_ort_construction_failure_returns_503(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """local finding GROKHARM-04: /ready must 503 when model verify passes but ORT runtime fails."""
    from fastapi.testclient import TestClient

    fpa = _live_face_pipeline_adapter()

    _align_dims_to_sface(monkeypatch)
    _install_synthetic_pair(tmp_path, monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(tmp_path))

    def boom_loader(*, models_dir: Path, **kwargs: object) -> object:
        raise RuntimeError("InferenceSession construction failed: synthetic ORT boom")

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter._load_face_pipeline_runtime",
        boom_loader,
    )

    app = _standalone_ready_app(monkeypatch)
    client = TestClient(app)
    resp = client.get("/ready")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == "unhealthy"
    mc = next(c for c in body["checks"] if c["name"] == "model_cache")
    assert mc["status"] == "unhealthy"
    detail = mc["detail"].lower()
    assert "runtime" in detail or "unavailable" in detail or "inferencesession" in detail
    fpa.reset_shared_face_pipeline_runtime_for_tests()
