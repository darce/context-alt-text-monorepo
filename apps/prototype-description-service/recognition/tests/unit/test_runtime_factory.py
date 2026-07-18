"""FIR-4 S3: shared build_embedding_runtime factory + site wiring.

Heuristics: [SERVE-01][SERVE-03][RLSE-05][TEST-03][TEST-06]
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recognition.application.embedding.detector import (
    StubFaceDetector,
    UnavailableFaceDetector,
)
from recognition.application.embedding.generator import (
    StubEmbeddingGenerator,
    UnavailableEmbeddingGenerator,
)
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.embeddings import runtime_factory as rf
from recognition.infrastructure.embeddings.face_pipeline_adapter import (
    FACE_PIPELINE_GENERATOR_REASON,
    FacePipelineRuntime,
    FacePipelineRuntimeUnavailableError,
    reset_shared_face_pipeline_runtime_for_tests,
)
from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR


def _settings(
    *,
    runtime_mode: str = "production",
    profile: str = "insightface",
    models_dir: Path | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        runtime_mode=runtime_mode,
        face_pipeline=SimpleNamespace(
            profile=profile,
            resolved_models_dir=models_dir or DEFAULT_MODELS_DIR,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
            timeout_s=5.0,
        ),
        identity_detection=SimpleNamespace(embedding_dimension=512),
    )


@pytest.fixture(autouse=True)
def _reset_face_pipeline_singleton() -> None:
    reset_shared_face_pipeline_runtime_for_tests()
    yield
    reset_shared_face_pipeline_runtime_for_tests()


@pytest.mark.asyncio
async def test_factory_default_profile_returns_insightface_types(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production default (no env overrides) = InsightFace types ([SERVE-03])."""
    adapter = object()

    async def _adapter() -> object:
        return adapter

    monkeypatch.setattr(rf, "get_shared_insightface_adapter", _adapter)

    # Bypass real InsightFace constructor work: use light stand-ins that keep types.
    class _Det:
        def __init__(self, a, client=None) -> None:
            self.adapter = a
            self.client = client

    class _Gen:
        def __init__(self, a) -> None:
            self.adapter = a

    monkeypatch.setattr(rf, "InsightFaceFaceDetector", _Det)
    monkeypatch.setattr(rf, "InsightFaceEmbeddingGenerator", _Gen)

    det, gen = await rf.build_embedding_runtime(settings=_settings(profile="insightface"))
    assert isinstance(det, _Det)
    assert isinstance(gen, _Gen)
    assert det.adapter is adapter


@pytest.mark.asyncio
async def test_factory_runtime_mode_test_returns_stubs() -> None:
    det, gen = await rf.build_embedding_runtime(settings=_settings(runtime_mode="test"))
    assert isinstance(det, StubFaceDetector)
    assert isinstance(gen, StubEmbeddingGenerator)


@pytest.mark.asyncio
async def test_factory_insightface_failure_both_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom() -> object:
        raise RuntimeError("adapter missing")

    monkeypatch.setattr(rf, "get_shared_insightface_adapter", _boom)
    det, gen = await rf.build_embedding_runtime(settings=_settings(profile="insightface"))
    assert isinstance(det, UnavailableFaceDetector)
    assert isinstance(gen, UnavailableEmbeddingGenerator)
    assert "adapter missing" in det.reason


@pytest.mark.asyncio
async def test_factory_face_pipeline_success(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = object()

    def _get_runtime(**kwargs: Any) -> object:
        return runtime

    class _FPDet:
        def __init__(self, rt, *, client=None, timeout=None) -> None:
            self.runtime = rt
            self.client = client
            self.timeout = timeout

    # Lazy import reads from face_pipeline_adapter (S3CR-01); patch there.
    monkeypatch.setattr(fpa, "get_shared_face_pipeline_runtime", _get_runtime)
    monkeypatch.setattr(fpa, "FacePipelineFaceDetector", _FPDet)

    client = object()
    det, gen = await rf.build_embedding_runtime(
        settings=_settings(profile="face_pipeline"),
        http_client=client,  # type: ignore[arg-type]
    )
    assert isinstance(det, _FPDet)
    assert det.runtime is runtime
    assert det.client is client
    assert isinstance(gen, UnavailableEmbeddingGenerator)
    assert FACE_PIPELINE_GENERATOR_REASON in gen.reason


@pytest.mark.asyncio
async def test_factory_face_pipeline_failure_atomic_both_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(**kwargs: Any) -> FacePipelineRuntime:
        raise FacePipelineRuntimeUnavailableError("sface missing")

    monkeypatch.setattr(fpa, "get_shared_face_pipeline_runtime", _boom)
    det, gen = await rf.build_embedding_runtime(settings=_settings(profile="face_pipeline"))
    assert isinstance(det, UnavailableFaceDetector)
    assert isinstance(gen, UnavailableEmbeddingGenerator)
    assert "sface missing" in det.reason
    assert det.reason == gen.reason


@pytest.mark.asyncio
async def test_factory_face_pipeline_ignores_adapter_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _provider() -> object:
        called["n"] += 1
        return object()

    runtime = object()

    class _FPDet:
        def __init__(self, rt, *, client=None, timeout=None) -> None:
            self.runtime = rt

    monkeypatch.setattr(fpa, "get_shared_face_pipeline_runtime", lambda **kw: runtime)
    monkeypatch.setattr(fpa, "FacePipelineFaceDetector", _FPDet)

    await rf.build_embedding_runtime(
        settings=_settings(profile="face_pipeline"),
        adapter_provider=_provider,
    )
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_factory_insightface_survives_poisoned_face_pipeline_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3CR-01: insightface factory path must not import face_pipeline_adapter."""
    import sys
    import types

    # Poison the adapter module so any import raises.
    poisoned = types.ModuleType("recognition.infrastructure.embeddings.face_pipeline_adapter")

    def _boom_getattr(name: str) -> object:
        raise ImportError(f"poisoned face_pipeline_adapter: {name}")

    poisoned.__getattr__ = _boom_getattr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "recognition.infrastructure.embeddings.face_pipeline_adapter", poisoned)

    adapter = object()

    async def _adapter() -> object:
        return adapter

    class _Det:
        def __init__(self, a, client=None) -> None:
            self.adapter = a

    class _Gen:
        def __init__(self, a) -> None:
            self.adapter = a

    monkeypatch.setattr(rf, "get_shared_insightface_adapter", _adapter)
    monkeypatch.setattr(rf, "InsightFaceFaceDetector", _Det)
    monkeypatch.setattr(rf, "InsightFaceEmbeddingGenerator", _Gen)

    det, gen = await rf.build_embedding_runtime(settings=_settings(profile="insightface"))
    assert isinstance(det, _Det)
    assert isinstance(gen, _Gen)
    assert det.adapter is adapter


@pytest.mark.asyncio
async def test_factory_adapter_provider_used_for_insightface(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = object()
    shared_calls = 0

    async def _shared() -> object:
        nonlocal shared_calls
        shared_calls += 1
        return object()

    async def _provider() -> object:
        return adapter

    class _Det:
        def __init__(self, a, client=None) -> None:
            self.adapter = a

    class _Gen:
        def __init__(self, a) -> None:
            self.adapter = a

    monkeypatch.setattr(rf, "get_shared_insightface_adapter", _shared)
    monkeypatch.setattr(rf, "InsightFaceFaceDetector", _Det)
    monkeypatch.setattr(rf, "InsightFaceEmbeddingGenerator", _Gen)

    det, gen = await rf.build_embedding_runtime(
        settings=_settings(profile="insightface"),
        adapter_provider=_provider,
    )
    assert shared_calls == 0
    assert isinstance(det, _Det)
    assert det.adapter is adapter
    assert isinstance(gen, _Gen)


# ---------------------------------------------------------------------------
# Site wiring: both profiles at all three construction sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_worker_insightface_and_face_pipeline_and_test_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from recognition.worker import scan_worker as sw

    calls: list[str] = []

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        calls.append(settings.face_pipeline.profile if settings.runtime_mode != "test" else "test")
        if settings.runtime_mode == "test":
            return StubFaceDetector(), StubEmbeddingGenerator()
        if settings.face_pipeline.profile == "face_pipeline":
            if getattr(settings, "_force_fail", False):
                return UnavailableFaceDetector("fp fail"), UnavailableEmbeddingGenerator("fp fail")
            return object(), UnavailableEmbeddingGenerator(FACE_PIPELINE_GENERATOR_REASON)
        return object(), object()

    def _settings_for(mode: str, profile: str, *, fail: bool = False):
        ns = SimpleNamespace(
            runtime_mode=mode,
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile=profile),
        )
        if fail:
            ns._force_fail = True  # type: ignore[attr-defined]
        return ns

    monkeypatch.setattr(sw, "build_embedding_runtime", _fake_build)

    # test mode short-circuits before factory
    monkeypatch.setattr(sw, "get_recognition_settings", lambda: _settings_for("test", "insightface"))
    worker = sw.ScanWorker(sw.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    await worker._ensure_embedding_runtime()
    assert isinstance(worker._detector, StubFaceDetector)
    assert calls == []  # test mode does not call factory
    await worker.__aexit__(None, None, None)

    # insightface
    monkeypatch.setattr(sw, "get_recognition_settings", lambda: _settings_for("prod", "insightface"))
    worker = sw.ScanWorker(sw.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    await worker._ensure_embedding_runtime()
    assert worker._embedding_runtime_ready is True
    assert "insightface" in calls
    await worker.__aexit__(None, None, None)

    # face_pipeline success
    calls.clear()
    monkeypatch.setattr(sw, "get_recognition_settings", lambda: _settings_for("prod", "face_pipeline"))
    worker = sw.ScanWorker(sw.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    await worker._ensure_embedding_runtime()
    assert worker._embedding_runtime_ready is True
    assert "face_pipeline" in calls
    await worker.__aexit__(None, None, None)

    # face_pipeline failure → both Unavailable, not ready, 30s retry
    async def _fail_build(*, settings, http_client=None, adapter_provider=None):
        return UnavailableFaceDetector("half"), UnavailableEmbeddingGenerator("half")

    monkeypatch.setattr(sw, "build_embedding_runtime", _fail_build)
    monkeypatch.setattr(sw, "get_recognition_settings", lambda: _settings_for("prod", "face_pipeline"))
    worker = sw.ScanWorker(sw.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    await worker._ensure_embedding_runtime()
    assert worker._embedding_runtime_ready is False
    assert isinstance(worker._detector, UnavailableFaceDetector)
    assert isinstance(worker._generator, UnavailableEmbeddingGenerator)
    assert worker._embedding_retry_after is not None
    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_scan_tasks_site_both_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    import recognition.application.scan.service as scan_service_module
    import recognition.config as recognition_config
    from recognition.application.tasks import scan as scan_tasks

    built: list[str] = []
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            pass

        async def mark_job_running(self, job_id):
            return SimpleNamespace(id=job_id)

        async def mark_job_failed(self, job_id, error_message: str):
            return SimpleNamespace(id=job_id)

        async def save_job_results(self, **kwargs):
            return SimpleNamespace(id=kwargs["job_id"])

    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    for mode, profile, expect in (
        ("test", "insightface", "test"),
        ("prod", "insightface", "insightface"),
        ("prod", "face_pipeline", "face_pipeline"),
    ):
        built.clear()
        monkeypatch.setattr(
            recognition_config,
            "get_settings",
            lambda m=mode, p=profile: SimpleNamespace(runtime_mode=m, face_pipeline=SimpleNamespace(profile=p)),
        )

        async def _build2(*, settings, http_client=None, adapter_provider=None):
            class _D:
                async def detect(self, sources):
                    return []

            class _G:
                async def generate(self, imgs):
                    return []

            if settings.runtime_mode == "test":
                built.append("test")
            else:
                built.append(settings.face_pipeline.profile)
            return _D(), _G()

        monkeypatch.setattr(rf, "build_embedding_runtime", _build2)
        await scan_tasks.process_scan_job_inline(
            tenant_id=str(__import__("uuid").uuid4()),
            job_id=str(__import__("uuid").uuid4()),
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _Sess(),
        )
        assert expect in built


@pytest.mark.asyncio
async def test_http_builder_site_both_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    import recognition.config as recognition_config
    from recognition.interface_adapters.http.deps import services as services_mod

    built: list[str] = []

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        if settings.runtime_mode == "test":
            built.append("test")
            return StubFaceDetector(), StubEmbeddingGenerator()
        built.append(settings.face_pipeline.profile)
        if settings.face_pipeline.profile == "face_pipeline":
            return object(), UnavailableEmbeddingGenerator(FACE_PIPELINE_GENERATOR_REASON)
        return object(), object()

    monkeypatch.setattr(rf, "build_embedding_runtime", _fake_build)

    class _Session:
        pass

    for mode, profile, expect in (
        ("test", "insightface", "test"),
        ("production", "insightface", "insightface"),
        ("production", "face_pipeline", "face_pipeline"),
    ):
        built.clear()
        monkeypatch.setattr(
            recognition_config,
            "get_settings",
            lambda m=mode, p=profile: SimpleNamespace(runtime_mode=m, face_pipeline=SimpleNamespace(profile=p)),
        )
        builder = services_mod.get_scan_service_builder(session=_Session())  # type: ignore[arg-type]
        svc = await builder("tenant")
        assert expect in built
        assert svc is not None


@pytest.mark.asyncio
async def test_worker_capability_heartbeat_includes_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from recognition.worker import scan_worker as sw

    published: dict[str, Any] = {}

    async def _publish(session, *, available, reason, now=None):
        published["available"] = available
        published["reason"] = reason

    monkeypatch.setattr(sw, "publish_embedding_runtime_capability", _publish)
    monkeypatch.setattr(
        sw,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="face_pipeline"),
        ),
    )

    async def _ok_build(*, settings, http_client=None, adapter_provider=None):
        return object(), UnavailableEmbeddingGenerator(FACE_PIPELINE_GENERATOR_REASON)

    monkeypatch.setattr(sw, "build_embedding_runtime", _ok_build)

    # Force postgres dialect path
    import recognition.shared.db.dialect as dialect

    monkeypatch.setattr(dialect, "is_postgres", lambda session: True)

    worker = sw.ScanWorker(sw.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:"))
    await worker._ensure_embedding_runtime()
    assert published.get("available") is True
    reason = str(published.get("reason") or "")
    assert reason.startswith("profile=face_pipeline")
    assert "media_processed=0" in reason
    assert "faces_detected=0" in reason
    assert "rows_matched=0" in reason
    assert "rows_new=0" in reason
    await worker.__aexit__(None, None, None)
