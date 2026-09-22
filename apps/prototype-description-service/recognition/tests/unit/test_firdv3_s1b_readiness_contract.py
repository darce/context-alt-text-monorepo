"""FIRDV-3 S1b RED contract for model-space readiness and alignment.

The production symbols imported inside the test bodies are intentionally not
present on the RED baseline.  The synthetic AuraFace entries exercise the
artifact branches without pretending that the real operator-pending pin is
verified; the real manifest remains covered by the activation refusal test.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import numpy as np
import pytest

from recognition.application import health as health_mod
from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    PENDING_OPERATOR_FETCH,
    REQUIRED_MODELS,
    InputPreprocessing,
    ModelMissingError,
    ModelProvenance,
    load_verified_model,
)
from shared.health import HealthStatus


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _synthetic_auraface_entry(
    *,
    model_payload: bytes = b"synthetic-auraface-model",
    license_payload: bytes = b"synthetic-auraface-license",
) -> tuple[ModelProvenance, bytes, bytes]:
    """Return a fully hashable AuraFace fixture with activation-safe metadata."""
    entry = MODEL_MANIFEST["auraface"]
    # The real entry is intentionally unverified.  A branch fixture must carry
    # a measured-looking template so check_model_space can reach its artifact,
    # dimension, and runtime checks; test 4/5 pin the real refusal separately.
    preprocessing = InputPreprocessing(
        input_size=(112, 112),
        channel_order="RGB",
        input_scale=1.0 / 127.5,
        alignment_template_id="arcface-112",
        output_l2_normalized=True,
    )
    synthetic = replace(
        entry,
        file_name="glintr100.onnx",
        sha256=_sha256(model_payload),
        size_bytes=len(model_payload),
        license_file="LICENSE.auraface",
        license_sha256=_sha256(license_payload),
        preprocessing=preprocessing,
    )
    return synthetic, model_payload, license_payload


def _pin_auraface_ok_dimensions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the 512D AuraFace pair and drop cached settings (HEALTH-RECOVERY-4)."""
    monkeypatch.setenv("PGVECTOR_DIM", "512")
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "512")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _install_synthetic_auraface(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    write_model: bool = True,
    write_license: bool = True,
    model_payload: bytes = b"synthetic-auraface-model",
    license_payload: bytes = b"synthetic-auraface-license",
) -> ModelProvenance:
    entry, model_bytes, license_bytes = _synthetic_auraface_entry(
        model_payload=model_payload,
        license_payload=license_payload,
    )
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", entry)
    if write_model:
        (tmp_path / entry.file_name).write_bytes(model_bytes)
    if write_license:
        (tmp_path / entry.license_file).write_bytes(license_bytes)
    return entry


def _live_face_pipeline_adapter() -> Any:
    """Resolve the adapter from live sys.modules, matching the readiness tests."""
    import importlib

    return importlib.import_module("recognition.infrastructure.embeddings.face_pipeline_adapter")


def _stub_shared_runtime_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub only the shared runtime loader for the incumbent SFace dimension leg."""
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

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter._load_face_pipeline_runtime",
        loader,
    )


def _stub_ort_session_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid constructing ORT sessions while allowing the real loader to run."""
    fpa = _live_face_pipeline_adapter()
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    for name, value in tuple(vars(fpa).items()):
        if name.lower().startswith("ort") and isinstance(value, type):
            monkeypatch.setattr(fpa, name, MagicMock(name=name))


@pytest.fixture(autouse=True)
def _reset_face_pipeline_state() -> None:
    """Keep verification, runtime, and dimension settings isolated per test."""
    from db.settings import get_database_settings
    from recognition.config import get_settings

    fpa = _live_face_pipeline_adapter()
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    health_mod._persisted_embedding_models_for_ready.set(None)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    get_settings.cache_clear()
    get_database_settings.cache_clear()
    yield
    health_mod.reset_face_pipeline_verify_cache_for_tests()
    health_mod._persisted_embedding_models_for_ready.set(None)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _install_synthetic_sface_pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Install the small 128-d YuNet+SFace pair used by the incumbent leg."""
    from recognition.infrastructure.face_pipeline.provenance import ModelProvenance

    yunet_payload = b"synthetic-yunet"
    sface_payload = b"synthetic-sface"
    yunet_license = b"synthetic-yunet-license"
    sface_license = b"synthetic-sface-license"
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "yunet",
        ModelProvenance(
            file_name="face_detection_yunet_2026may.onnx",
            sha256=_sha256(yunet_payload),
            source_url="https://example.test/yunet.onnx",
            source_ref="synthetic-readiness",
            license_id="MIT",
            license_file="LICENSE.yunet",
            license_sha256=_sha256(yunet_license),
            size_bytes=len(yunet_payload),
            framework="opencv",
        ),
    )
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "sface",
        ModelProvenance(
            file_name="face_recognition_sface_2021dec.onnx",
            sha256=_sha256(sface_payload),
            source_url="https://example.test/sface.onnx",
            source_ref="synthetic-readiness",
            license_id="Apache-2.0",
            license_file="LICENSE.sface",
            license_sha256=_sha256(sface_license),
            size_bytes=len(sface_payload),
            framework="opencv",
            embedding_dim=128,
            normalization="l2",
            metric="cosine",
        ),
    )
    (tmp_path / "face_detection_yunet_2026may.onnx").write_bytes(yunet_payload)
    (tmp_path / "LICENSE.yunet").write_bytes(yunet_license)
    (tmp_path / "face_recognition_sface_2021dec.onnx").write_bytes(sface_payload)
    (tmp_path / "LICENSE.sface").write_bytes(sface_license)


class _NestedSavepointCM:
    """Small async savepoint context used by the real readiness DB probe."""

    def __init__(self, session: _TxnAwareSession) -> None:
        self._session = session

    async def __aenter__(self) -> _NestedSavepointCM:
        self._session._in_savepoint = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        self._session._in_savepoint = False
        return False


class _TxnAwareSession:
    """Session-shaped fake copied from the existing readiness test seam."""

    def __init__(self, *, typmod_rows: list[tuple[str, str, int]]) -> None:
        self._typmod_rows = typmod_rows
        self._in_savepoint = False
        self.execute = AsyncMock(side_effect=self._execute)

    def begin_nested(self) -> _NestedSavepointCM:
        return _NestedSavepointCM(self)

    async def _execute(self, stmt: object, *args: object, **kwargs: object) -> MagicMock:
        sql = str(getattr(stmt, "text", stmt))
        result = MagicMock()
        if "DISTINCT" in sql.upper() and "embedding_model" in sql:
            result.all = MagicMock(return_value=[])
            result.fetchall = MagicMock(return_value=[])
            return result
        result.all = MagicMock(return_value=list(self._typmod_rows))
        result.fetchall = MagicMock(return_value=list(self._typmod_rows))
        return result


def _identity_typmod_rows() -> list[tuple[str, str, int]]:
    from db.settings import get_database_settings

    dimension = int(get_database_settings().pgvector_dimension)
    return [
        ("media_identities", "embedding", dimension),
        ("identity_cluster_representatives", "embedding", dimension),
        ("mv_identity_cluster_centroids", "centroid", dimension),
    ]


def _standalone_ready_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model_cache_dir: Path,
    models_dirs: dict[Any, Path],
    session_factory: Any | None = None,
) -> Any:
    """Mount the real readiness routes onto a dependency-safe bare FastAPI app."""
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
    register_health_probes(app, model_cache_dir=model_cache_dir, models_dirs=models_dirs)

    async def _default_session_yielder():
        yield _TxnAwareSession(typmod_rows=_identity_typmod_rows())

    app.dependency_overrides[dependencies.get_observability_session] = (
        session_factory if session_factory is not None else _default_session_yielder
    )

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    return app


async def _get_ready(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        return await client.get("/ready")


async def _get_detailed(app: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        return await client.get("/health/detailed")


def test_auraface_space_missing_artifact_names_glintr100(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    entry = _install_synthetic_auraface(tmp_path, monkeypatch, write_model=False, write_license=False)
    result = check_model_space(ModelSpace.AURAFACE, tmp_path)

    assert result.status is HealthStatus.UNHEALTHY
    assert entry.file_name == "glintr100.onnx"
    assert "glintr100.onnx" in result.detail
    assert "missing" in result.detail.lower()
    assert "invalid face_pipeline profile" not in result.detail


def test_auraface_space_hash_mismatch_reason_differs_from_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    entry, expected_model, license_payload = _synthetic_auraface_entry()
    monkeypatch.setitem(MODEL_MANIFEST, "auraface", entry)
    missing = check_model_space(ModelSpace.AURAFACE, tmp_path)

    corrupted = bytes([expected_model[0] ^ 0xFF]) + expected_model[1:]
    (tmp_path / entry.file_name).write_bytes(corrupted)
    (tmp_path / entry.license_file).write_bytes(license_payload)
    tampered = check_model_space(ModelSpace.AURAFACE, tmp_path)

    assert missing.status is HealthStatus.UNHEALTHY
    assert tampered.status is HealthStatus.UNHEALTHY
    assert "sha256" in tampered.detail.lower() or "integrity" in tampered.detail.lower()
    assert tampered.detail != missing.detail


def test_auraface_space_verified_artifacts_reach_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    _pin_auraface_ok_dimensions(monkeypatch)
    _install_synthetic_auraface(tmp_path, monkeypatch)
    _stub_ort_session_classes(monkeypatch)
    result = check_model_space(ModelSpace.AURAFACE, tmp_path)

    assert result.status is HealthStatus.OK, result.detail
    assert "auraface" in result.detail.lower()
    assert "sface" not in result.detail.lower()

    fpa = _live_face_pipeline_adapter()
    runtime = fpa.get_shared_face_pipeline_runtime(
        profile=ModelSpace.AURAFACE.value,
        models_dir=tmp_path,
    )
    assert runtime.manifest.dimensions == 512
    assert "sface" not in runtime.manifest.model_id.lower()


def test_real_auraface_entry_blocks_activation_while_artifact_absent(tmp_path: Path) -> None:
    """Absent bytes still fail load; readiness must refuse the unverified template first."""
    with pytest.raises(ModelMissingError, match="model file missing"):
        load_verified_model("auraface", models_dir=tmp_path)


def _count_onnx_hashes(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Count model-file sha256 calls used by load_verified_model / verify_face_pipeline_model."""
    import recognition.infrastructure.face_pipeline.provenance as prov_mod

    calls = {"n": 0}
    real = prov_mod._file_sha256

    def _counting(path: Path) -> str:
        name = Path(path).name
        if name.endswith(".onnx"):
            calls["n"] += 1
        return real(path)

    monkeypatch.setattr(prov_mod, "_file_sha256", _counting)
    return calls


def _forbid_verified_model_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Fail the test if readiness reaches model hashing or verified-load."""
    import recognition.infrastructure.face_pipeline.provenance as prov_mod

    calls = {"sha": 0, "load": 0, "verify": 0}
    real_sha = prov_mod._file_sha256
    real_load = prov_mod.load_verified_model
    real_verify = health_mod.verify_face_pipeline_model

    def _count_sha(path: Path) -> str:
        calls["sha"] += 1
        return real_sha(path)

    def _count_load(name: str, *, models_dir: Path | None = None) -> Path:
        calls["load"] += 1
        return real_load(name, models_dir=models_dir)

    def _count_verify(name: str, *, models_dir: Path | None = None) -> object:
        calls["verify"] += 1
        return real_verify(name, models_dir=models_dir)

    monkeypatch.setattr(prov_mod, "_file_sha256", _count_sha)
    monkeypatch.setattr(prov_mod, "load_verified_model", _count_load)
    monkeypatch.setattr(health_mod, "load_verified_model", _count_load, raising=False)
    monkeypatch.setattr(health_mod, "verify_face_pipeline_model", _count_verify)
    return calls


def test_unverified_preprocessing_entry_is_refused_for_activation() -> None:
    from recognition.application.health import ModelSpace, assert_space_activatable

    with pytest.raises(Exception, match=f"{PENDING_OPERATOR_FETCH}|-unverified"):
        assert_space_activatable(ModelSpace.AURAFACE)

    entry = MODEL_MANIFEST["auraface"]
    assert "auraface" not in REQUIRED_MODELS
    assert entry.preprocessing is not None
    assert "sface" not in entry.preprocessing.alignment_template_id.lower()


def test_auraface_dimension_is_per_space_not_global_pgvector_dim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PGVECTOR_DIM", "128")
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()
    assert get_database_settings().pgvector_dimension == 128

    from recognition.application.health import ModelSpace, check_model_space, expected_embedding_dimension

    face_dir = tmp_path / "face-pipeline"
    face_dir.mkdir()
    _install_synthetic_sface_pair(face_dir, monkeypatch)
    _stub_shared_runtime_loader(monkeypatch)
    face_result = check_model_space(ModelSpace.FACE_PIPELINE, face_dir)
    assert face_result.status is HealthStatus.OK, face_result.detail

    aura_dir = tmp_path / "auraface"
    aura_dir.mkdir()
    _install_synthetic_auraface(aura_dir, monkeypatch)
    assert expected_embedding_dimension(ModelSpace.AURAFACE) == 512
    aura_result = check_model_space(ModelSpace.AURAFACE, aura_dir)
    assert aura_result.status is HealthStatus.UNHEALTHY
    assert "auraface" in aura_result.detail.lower()


# Keep literals at collection time so a missing ModelSpace fails in the test
# body rather than collapsing collection into an import error.
@pytest.mark.parametrize("space_value", ("insightface", "face_pipeline", "auraface"))
@pytest.mark.asyncio
async def test_each_model_space_routes_to_its_own_check_and_store(
    space_value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.main as api_main
    from recognition.application.health import ModelSpace

    space = ModelSpace(space_value)
    insightface_dir = tmp_path / "insightface"
    face_pipeline_dir = tmp_path / "face-pipeline"
    auraface_dir = tmp_path / "auraface"
    models_dirs = {
        ModelSpace.FACE_PIPELINE: face_pipeline_dir,
        ModelSpace.AURAFACE: auraface_dir,
    }
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", space.value)
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(face_pipeline_dir))
    monkeypatch.setenv("RECOGNITION_AURAFACE_MODELS_DIR", str(auraface_dir))

    cache_calls: list[tuple[Path, str]] = []
    face_calls: list[Path] = []

    def record_cache(cache_dir: Path, *args: object, **kwargs: object) -> health_mod.CheckResult:
        cache_calls.append((Path(cache_dir), str(kwargs.get("model_name", args[0] if args else "buffalo_l"))))
        return health_mod.CheckResult("model_cache", HealthStatus.OK, f"insightface: {cache_dir}")

    def record_face(models_dir: Path) -> health_mod.CheckResult:
        face_calls.append(Path(models_dir))
        return health_mod.CheckResult("model_cache", HealthStatus.OK, f"face_pipeline: {models_dir}")

    monkeypatch.setattr(api_main, "check_model_cache", record_cache)
    monkeypatch.setattr(api_main, "check_face_pipeline_models", record_face)
    resolver_calls: list[tuple[Any, Path, str]] = []
    real_resolver = api_main.resolve_model_space_probe

    def record_resolver(space_arg: Any, **kwargs: Any) -> tuple[Any, Path, str]:
        resolved = real_resolver(space_arg, **kwargs)
        resolver_calls.append((space_arg, resolved[1], resolved[2]))
        return resolved

    monkeypatch.setattr(api_main, "resolve_model_space_probe", record_resolver)
    app = _standalone_ready_app(
        monkeypatch,
        model_cache_dir=insightface_dir,
        models_dirs=models_dirs,
    )
    response = await _get_ready(app)

    # This test's subject is routing, not the verdict. Only insightface and
    # face_pipeline have their checks patched to OK above; auraface's real check runs,
    # and its manifest entry is PENDING_OPERATOR_FETCH, so it must not report ready --
    # see test_real_auraface_entry_blocks_activation_while_hash_pending.
    expected_code = 503 if space is ModelSpace.AURAFACE else 200
    assert response.status_code == expected_code, response.text
    assert resolver_calls and resolver_calls[-1][0] is space
    expected_store = {
        ModelSpace.INSIGHTFACE: insightface_dir,
        ModelSpace.FACE_PIPELINE: face_pipeline_dir,
        ModelSpace.AURAFACE: auraface_dir,
    }[space]
    assert resolver_calls[-1][1] == expected_store
    if space is ModelSpace.INSIGHTFACE:
        assert cache_calls == [(insightface_dir, "buffalo_l")]
        assert face_calls == []
    elif space is ModelSpace.FACE_PIPELINE:
        assert cache_calls == []
        assert face_calls == [face_pipeline_dir]
    else:
        assert cache_calls == []
        assert face_calls == []
        assert not insightface_dir.exists()


@pytest.mark.asyncio
async def test_unhandled_model_space_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import api.main as api_main
    from api.main import resolve_model_space_probe
    from recognition.application.health import ModelSpace, UnhandledModelSpaceError

    class FutureSpace(StrEnum):
        FUTURE = "future_space"

    cache_calls: list[Path] = []

    def record_cache(cache_dir: Path, *args: object, **kwargs: object) -> health_mod.CheckResult:
        cache_calls.append(Path(cache_dir))
        return health_mod.CheckResult("model_cache", HealthStatus.OK, "unexpected cache call")

    monkeypatch.setattr(api_main, "check_model_cache", record_cache)
    with pytest.raises(UnhandledModelSpaceError):
        resolve_model_space_probe(
            FutureSpace.FUTURE,
            insightface_cache_dir=tmp_path / "insightface",
            insightface_model_name="buffalo_l",
            models_dirs={
                ModelSpace.FACE_PIPELINE: tmp_path / "face-pipeline",
                ModelSpace.AURAFACE: tmp_path / "auraface",
            },
        )
    assert cache_calls == []

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface")
    app = _standalone_ready_app(
        monkeypatch,
        model_cache_dir=tmp_path / "insightface",
        models_dirs={
            ModelSpace.FACE_PIPELINE: tmp_path / "face-pipeline",
            ModelSpace.AURAFACE: tmp_path / "auraface",
        },
    )
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "future_space")

    response = await _get_ready(app)
    assert response.status_code == 503
    detail = next(check for check in response.json()["checks"] if check["name"] == "model_cache")["detail"]
    assert all(member.value in detail for member in ModelSpace)


def test_auraface_store_with_only_sface_artifacts_is_unhealthy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import api.main as api_main
    from api.main import resolve_model_space_probe
    from recognition.application.health import ModelSpace

    _install_synthetic_sface_pair(tmp_path, monkeypatch)
    entry = _install_synthetic_auraface(tmp_path, monkeypatch, write_model=False, write_license=False)
    cache_calls: list[Path] = []

    def record_cache(cache_dir: Path, *args: object, **kwargs: object) -> health_mod.CheckResult:
        cache_calls.append(Path(cache_dir))
        return health_mod.CheckResult("model_cache", HealthStatus.OK, "wrong-space cache")

    monkeypatch.setattr(api_main, "check_model_cache", record_cache)
    probe, store, _label = resolve_model_space_probe(
        ModelSpace.AURAFACE,
        insightface_cache_dir=tmp_path / "insightface",
        insightface_model_name="buffalo_l",
        models_dirs={ModelSpace.AURAFACE: tmp_path},
    )
    result = probe()

    assert store == tmp_path
    assert result.status is HealthStatus.UNHEALTHY
    assert entry.file_name in result.detail
    assert "missing" in result.detail.lower()
    assert cache_calls == []


def test_aligner_template_is_injected_per_space() -> None:
    from recognition.application.health import ModelSpace
    from recognition.infrastructure.face_pipeline.aligner import (
        SFACE_CANONICAL_LANDMARKS_112,
        FivePointAligner,
    )

    sface = FivePointAligner(space=ModelSpace.FACE_PIPELINE)
    aura = FivePointAligner(space=ModelSpace.AURAFACE)

    assert np.array_equal(sface.dst_landmarks, SFACE_CANONICAL_LANDMARKS_112)
    assert isinstance(aura.template_id, str)
    assert "sface" not in aura.template_id.lower()


def test_auraface_alignment_crop_is_rgb_relative_to_sface_bgr() -> None:
    from recognition.application.health import ModelSpace
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner

    image = np.zeros((180, 180, 3), dtype=np.uint8)
    image[..., 0] = 17
    image[..., 1] = 83
    image[..., 2] = 191
    landmarks = np.array(
        [[50.0, 55.0], [120.0, 55.0], [85.0, 85.0], [60.0, 125.0], [110.0, 125.0]],
        dtype=np.float64,
    )

    sface = FivePointAligner(space=ModelSpace.FACE_PIPELINE)
    aura = FivePointAligner(space=ModelSpace.AURAFACE)
    sface_result = sface.align(image, landmarks)
    aura_result = aura.align(image, landmarks)

    assert np.array_equal(aura_result.crop, sface_result.crop[..., ::-1])
    assert sface.channel_order == "BGR"
    assert aura.channel_order == "RGB"


def test_unverified_auraface_readiness_refuses_before_model_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    entry = MODEL_MANIFEST["auraface"]
    (tmp_path / entry.file_name).write_bytes(b"unverified-auraface-bytes")
    (tmp_path / entry.license_file).write_bytes(b"unverified-auraface-license")
    io_calls = _forbid_verified_model_io(monkeypatch)

    result = check_model_space(ModelSpace.AURAFACE, tmp_path)

    assert result.status is HealthStatus.UNHEALTHY, result.detail
    assert "alignment template" in result.detail
    assert "arcface-112-unverified" in result.detail
    assert io_calls == {"sha": 0, "load": 0, "verify": 0}


def test_auraface_repeated_probes_hash_model_bytes_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    _pin_auraface_ok_dimensions(monkeypatch)
    _install_synthetic_auraface(tmp_path, monkeypatch)
    _stub_ort_session_classes(monkeypatch)
    hash_calls = _count_onnx_hashes(monkeypatch)

    first = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert first.status is HealthStatus.OK, first.detail
    hashes_after_first = hash_calls["n"]
    assert hashes_after_first >= 1

    second = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert second.status is HealthStatus.OK, second.detail
    assert hash_calls["n"] == hashes_after_first


def test_auraface_license_only_drift_invalidates_cached_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    _pin_auraface_ok_dimensions(monkeypatch)
    entry = _install_synthetic_auraface(tmp_path, monkeypatch)
    _stub_ort_session_classes(monkeypatch)
    hash_calls = _count_onnx_hashes(monkeypatch)

    first = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert first.status is HealthStatus.OK, first.detail
    hashes_after_first = hash_calls["n"]
    assert hashes_after_first >= 1

    second = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert second.status is HealthStatus.OK, second.detail
    assert hash_calls["n"] == hashes_after_first

    model_path = tmp_path / entry.file_name
    license_path = tmp_path / entry.license_file
    model_before = model_path.read_bytes()
    license_path.write_bytes(license_path.read_bytes() + b"\n#tampered-license\n")

    third = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert third.status is HealthStatus.UNHEALTHY, third.detail
    detail_l = third.detail.lower()
    assert "license" in detail_l
    assert model_path.read_bytes() == model_before


def test_auraface_model_stat_drift_invalidates_cached_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    _pin_auraface_ok_dimensions(monkeypatch)
    entry = _install_synthetic_auraface(tmp_path, monkeypatch)
    _stub_ort_session_classes(monkeypatch)

    first = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert first.status is HealthStatus.OK, first.detail

    model_path = tmp_path / entry.file_name
    model_path.write_bytes(model_path.read_bytes() + b"\x00")
    drifted = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert drifted.status is HealthStatus.UNHEALTHY, drifted.detail
    detail_l = drifted.detail.lower()
    assert "sha256" in detail_l or "integrity" in detail_l or "size mismatch" in detail_l


def test_auraface_missing_artifacts_recover_on_later_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace, check_model_space

    entry = _install_synthetic_auraface(tmp_path, monkeypatch, write_model=False, write_license=False)
    missing = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert missing.status is HealthStatus.UNHEALTHY, missing.detail
    assert "missing" in missing.detail.lower()
    assert entry.file_name in missing.detail

    _pin_auraface_ok_dimensions(monkeypatch)
    _install_synthetic_auraface(tmp_path, monkeypatch)
    _stub_ort_session_classes(monkeypatch)
    recovered = check_model_space(ModelSpace.AURAFACE, tmp_path)
    assert recovered.status is HealthStatus.OK, recovered.detail


@pytest.mark.asyncio
async def test_unverified_auraface_ready_returns_503_not_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.application.health import ModelSpace

    entry = MODEL_MANIFEST["auraface"]
    aura_dir = tmp_path / "auraface"
    aura_dir.mkdir()
    (aura_dir / entry.file_name).write_bytes(b"unverified-auraface-bytes")
    (aura_dir / entry.license_file).write_bytes(b"unverified-auraface-license")
    io_calls = _forbid_verified_model_io(monkeypatch)

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "auraface")
    monkeypatch.setenv("RECOGNITION_AURAFACE_MODELS_DIR", str(aura_dir))
    app = _standalone_ready_app(
        monkeypatch,
        model_cache_dir=tmp_path / "insightface",
        models_dirs={
            ModelSpace.FACE_PIPELINE: tmp_path / "face-pipeline",
            ModelSpace.AURAFACE: aura_dir,
        },
    )
    response = await _get_ready(app)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "unhealthy"
    detail = next(check for check in body["checks"] if check["name"] == "model_cache")["detail"]
    assert "alignment template" in detail
    assert "arcface-112-unverified" in detail
    assert io_calls == {"sha": 0, "load": 0, "verify": 0}


@pytest.mark.asyncio
async def test_ready_respects_profile_change_after_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.main as api_main
    from recognition.application.health import ModelSpace

    insightface_dir = tmp_path / "insightface"
    face_pipeline_dir = tmp_path / "face-pipeline"
    auraface_dir = tmp_path / "auraface"
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "auraface")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(face_pipeline_dir))
    monkeypatch.setenv("RECOGNITION_AURAFACE_MODELS_DIR", str(auraface_dir))

    cache_calls: list[tuple[Path, str]] = []

    def record_cache(cache_dir: Path, *args: object, **kwargs: object) -> health_mod.CheckResult:
        cache_calls.append((Path(cache_dir), str(kwargs.get("model_name", args[0] if args else "buffalo_l"))))
        return health_mod.CheckResult("model_cache", HealthStatus.OK, f"insightface: {cache_dir}")

    monkeypatch.setattr(api_main, "check_model_cache", record_cache)
    app = _standalone_ready_app(
        monkeypatch,
        model_cache_dir=insightface_dir,
        models_dirs={
            ModelSpace.FACE_PIPELINE: face_pipeline_dir,
            ModelSpace.AURAFACE: auraface_dir,
        },
    )

    first = await _get_ready(app)
    assert first.status_code == 503, first.text
    first_detail = next(check for check in first.json()["checks"] if check["name"] == "model_cache")["detail"]
    assert "alignment template" in first_detail
    assert "arcface-112-unverified" in first_detail
    assert cache_calls == []

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface")
    second = await _get_ready(app)
    assert second.status_code == 200, second.text
    assert cache_calls == [(insightface_dir, "buffalo_l")]


@pytest.mark.asyncio
async def test_health_detailed_inventories_auraface_root_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEALTH-RECOVERY-1: count the store-root ONNX, not cache/auraface/*.onnx."""
    from recognition.application.health import ModelSpace

    aura_dir = tmp_path / "aura-store"
    aura_dir.mkdir()
    nested = aura_dir / "auraface"
    nested.mkdir()
    (nested / "decoy-a.onnx").write_bytes(b"nested-decoy-a")
    (nested / "decoy-b.onnx").write_bytes(b"nested-decoy-b")
    root_artifact = aura_dir / MODEL_MANIFEST["auraface"].file_name
    root_artifact.write_bytes(b"root-auraface-artifact")

    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "auraface")
    monkeypatch.setenv("RECOGNITION_AURAFACE_MODELS_DIR", str(aura_dir))
    app = _standalone_ready_app(
        monkeypatch,
        model_cache_dir=tmp_path / "insightface",
        models_dirs={
            ModelSpace.FACE_PIPELINE: tmp_path / "face-pipeline",
            ModelSpace.AURAFACE: aura_dir,
        },
    )
    response = await _get_detailed(app)
    assert response.status_code == 200, response.text
    cache = response.json()["model_cache"]
    assert cache["profile"] == "auraface"
    assert cache["model_name"] == "auraface"
    assert Path(cache["cache_dir"]) == aura_dir
    assert cache["bundle_files"] == 1


@pytest.mark.asyncio
async def test_build_embedding_runtime_auraface_uses_inhouse_not_insightface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HEALTH-RECOVERY-2: AuraFace routes to the 512D in-house runtime."""
    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.application.health import ModelSpace
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.embeddings import runtime_factory as rf

    _pin_auraface_ok_dimensions(monkeypatch)
    face_dir = tmp_path / "face-pipeline"
    aura_dir = tmp_path / "auraface"
    face_dir.mkdir()
    aura_dir.mkdir()
    _install_synthetic_auraface(aura_dir, monkeypatch)
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "auraface")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(face_dir))
    monkeypatch.setenv("RECOGNITION_AURAFACE_MODELS_DIR", str(aura_dir))
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()

    captured: dict[str, Any] = {}
    runtime = fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=fpa.auraface_embedding_model_manifest(),
        models_dir=face_dir,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
        embedder_models_dir=aura_dir,
    )

    def capture_runtime(**kwargs: Any) -> fpa.FacePipelineRuntime:
        captured.update(kwargs)
        return runtime

    monkeypatch.setattr(fpa, "get_shared_face_pipeline_runtime", capture_runtime)
    monkeypatch.setattr(
        rf,
        "InsightFaceFaceDetector",
        MagicMock(side_effect=AssertionError("InsightFace detector fallback")),
    )
    monkeypatch.setattr(
        rf,
        "get_shared_insightface_adapter",
        MagicMock(side_effect=AssertionError("InsightFace adapter fallback")),
    )

    settings = get_settings()
    detector, generator = await rf.build_embedding_runtime(settings=settings)
    assert not isinstance(detector, UnavailableFaceDetector)
    assert isinstance(detector, fpa.FacePipelineFaceDetector)
    assert captured["profile"] in {ModelSpace.AURAFACE, ModelSpace.AURAFACE.value, "auraface"}
    assert Path(captured["models_dir"]) == face_dir
    assert Path(captured["embedder_models_dir"]) == aura_dir
    assert generator.reason == fpa.FACE_PIPELINE_GENERATOR_REASON
    assert detector._runtime.manifest.dimensions == 512
    assert "auraface" in detector._runtime.manifest.model_id.lower()
    assert "buffalo" not in detector._runtime.manifest.model_id.lower()
    assert "sface" not in detector._runtime.manifest.model_id.lower()


def test_activation_policy_is_shared_infrastructure_helper() -> None:
    from recognition.application import health
    from recognition.infrastructure.face_pipeline import activation

    assert health.assert_space_activatable is activation.assert_space_activatable
    source = Path(activation.__file__).read_text(encoding="utf-8")
    assert "application.health" not in source
    assert "recognition.application" not in source


def test_incumbent_spaces_remain_activatable() -> None:
    from recognition.infrastructure.face_pipeline.activation import assert_space_activatable
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace

    assert_space_activatable(ModelSpace.INSIGHTFACE)
    assert_space_activatable(ModelSpace.FACE_PIPELINE)


def test_synthetic_verified_fixture_routes_same_activation_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recognition.application.health import assert_space_activatable as health_assert
    from recognition.infrastructure.face_pipeline.activation import assert_space_activatable
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace

    _install_synthetic_auraface(tmp_path, monkeypatch)
    assert_space_activatable(ModelSpace.AURAFACE)
    health_assert(ModelSpace.AURAFACE)


def _forbid_shared_runtime_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Explode if shared-runtime construction stats artifacts or builds ORT."""
    fpa = _live_face_pipeline_adapter()
    calls = {"stat": 0, "cache_key": 0, "load": 0, "detector": 0, "embedder": 0, "aligner": 0}

    def _boom(name: str):
        def _inner(*args: object, **kwargs: object) -> object:
            calls[name] += 1
            raise AssertionError(f"shared runtime reached {name} before activation policy")

        return _inner

    monkeypatch.setattr(fpa, "_artifact_stat_identity", _boom("stat"))
    monkeypatch.setattr(fpa, "_runtime_cache_key", _boom("cache_key"))
    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", _boom("load"))
    monkeypatch.setattr(fpa, "OrtYuNetDetector", _boom("detector"))
    monkeypatch.setattr(fpa, "OrtSFaceEmbedder", _boom("embedder"))
    monkeypatch.setattr(fpa, "FivePointAligner", _boom("aligner"))
    return calls


def test_shared_runtime_rejects_unverified_before_constructors_and_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace

    fpa = _live_face_pipeline_adapter()
    original = MODEL_MANIFEST["auraface"]
    _pin_auraface_ok_dimensions(monkeypatch)
    _install_synthetic_auraface(tmp_path, monkeypatch)
    seeded = fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=fpa.auraface_embedding_model_manifest(),
        models_dir=tmp_path,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
        embedder_models_dir=tmp_path,
    )

    def _seed(**kwargs: object) -> object:
        return seeded

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", _seed)
    cached = fpa.get_shared_face_pipeline_runtime(
        profile=ModelSpace.AURAFACE,
        models_dir=tmp_path,
        embedder_models_dir=tmp_path,
    )
    assert cached is seeded

    MODEL_MANIFEST["auraface"] = original
    assert original.preprocessing is not None
    assert "unverified" in original.preprocessing.alignment_template_id.lower()
    calls = _forbid_shared_runtime_io(monkeypatch)
    with pytest.raises(Exception, match="unverified|alignment template"):
        fpa.get_shared_face_pipeline_runtime(
            profile=ModelSpace.AURAFACE,
            models_dir=tmp_path,
            embedder_models_dir=tmp_path,
        )
    assert calls["stat"] == 0
    assert calls["cache_key"] == 0
    assert calls["load"] == 0
    assert calls["detector"] == 0
    assert calls["embedder"] == 0
    assert calls["aligner"] == 0


def test_load_runtime_rejects_unverified_before_constructors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace

    fpa = _live_face_pipeline_adapter()
    _pin_auraface_ok_dimensions(monkeypatch)
    calls = {"detector": 0, "embedder": 0, "aligner": 0}

    def _boom(name: str):
        def _inner(*args: object, **kwargs: object) -> object:
            calls[name] += 1
            raise AssertionError(f"shared runtime reached {name} before activation policy")

        return _inner

    monkeypatch.setattr(fpa, "OrtYuNetDetector", _boom("detector"))
    monkeypatch.setattr(fpa, "OrtSFaceEmbedder", _boom("embedder"))
    monkeypatch.setattr(fpa, "FivePointAligner", _boom("aligner"))
    with pytest.raises(Exception, match="unverified|alignment template"):
        fpa._load_face_pipeline_runtime(
            models_dir=tmp_path,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
            space=ModelSpace.AURAFACE,
            embedder_models_dir=tmp_path,
        )
    assert calls == {"detector": 0, "embedder": 0, "aligner": 0}


@pytest.mark.asyncio
async def test_factory_rejects_unverified_auraface_before_runtime_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.application.embedding.generator import UnavailableEmbeddingGenerator
    from recognition.infrastructure.embeddings import runtime_factory as rf

    fpa = _live_face_pipeline_adapter()
    _pin_auraface_ok_dimensions(monkeypatch)
    calls = _forbid_shared_runtime_io(monkeypatch)
    settings = SimpleNamespace(
        runtime_mode="production",
        face_pipeline=SimpleNamespace(
            profile="auraface",
            resolved_models_dir=tmp_path,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
            timeout_s=5.0,
        ),
        auraface_models_dir=tmp_path,
    )
    detector, generator = await rf.build_embedding_runtime(settings=settings)  # type: ignore[arg-type]
    assert isinstance(detector, UnavailableFaceDetector)
    assert isinstance(generator, UnavailableEmbeddingGenerator)
    assert "unverified" in detector.reason.lower() or "alignment template" in detector.reason.lower()
    assert calls == {"stat": 0, "cache_key": 0, "load": 0, "detector": 0, "embedder": 0, "aligner": 0}
    assert fpa._SHARED is None


@pytest.mark.asyncio
async def test_factory_missing_auraface_models_dir_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.infrastructure.embeddings import runtime_factory as rf

    _install_synthetic_auraface(tmp_path, monkeypatch)
    _pin_auraface_ok_dimensions(monkeypatch)
    constructed: list[object] = []

    def _boom(**kwargs: object) -> object:
        constructed.append(kwargs)
        raise AssertionError("missing auraface_models_dir must not construct runtime")

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.face_pipeline_adapter.get_shared_face_pipeline_runtime",
        _boom,
    )
    settings = SimpleNamespace(
        runtime_mode="production",
        face_pipeline=SimpleNamespace(
            profile="auraface",
            resolved_models_dir=tmp_path,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
            timeout_s=5.0,
        ),
    )
    detector, generator = await rf.build_embedding_runtime(settings=settings)  # type: ignore[arg-type]
    assert isinstance(detector, UnavailableFaceDetector)
    assert constructed == []
    assert "auraface_models_dir" in detector.reason or "AttributeError" in detector.reason
