from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from recognition.worker import scan_worker as scan_worker_module


class _FakeDetector:
    def __init__(self, adapter: object, client: object | None = None) -> None:
        self.adapter = adapter
        self.client = client


class _FakeGenerator:
    def __init__(self, adapter: object) -> None:
        self.adapter = adapter


@pytest.mark.asyncio
async def test_scan_worker_reuses_shared_insightface_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = object()
    calls = 0

    async def _fake_get_shared_adapter() -> object:
        nonlocal calls
        calls += 1
        return adapter

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod", blob_root=tmp_path / "blobs"),
    )
    monkeypatch.setattr(scan_worker_module, "get_shared_insightface_adapter", _fake_get_shared_adapter)
    monkeypatch.setattr(scan_worker_module, "InsightFaceFaceDetector", _FakeDetector)
    monkeypatch.setattr(scan_worker_module, "InsightFaceEmbeddingGenerator", _FakeGenerator)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    await worker._ensure_embedding_runtime()
    await worker._ensure_embedding_runtime()

    assert calls == 1
    assert worker._embedding_runtime_ready is True
    assert isinstance(worker._detector, _FakeDetector)
    assert isinstance(worker._generator, _FakeGenerator)
    assert worker._detector.adapter is adapter
    assert worker._generator.adapter is adapter

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_scan_worker_retries_runtime_init_after_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls = 0

    async def _failing_get_shared_adapter() -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient load failure")

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod", blob_root=tmp_path / "blobs"),
    )
    monkeypatch.setattr(scan_worker_module, "get_shared_insightface_adapter", _failing_get_shared_adapter)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    await worker._ensure_embedding_runtime()

    assert calls == 1
    assert worker._embedding_runtime_ready is False
    assert worker._embedding_retry_after is not None

    worker._embedding_retry_after = None
    await worker._ensure_embedding_runtime()
    assert calls == 2

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Phase 4: MV refresh suppression (finding 1169)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppress_mv_refresh_flag_initialises_false(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Worker must initialise _suppress_mv_refresh_once=False (no stale-flag state on startup)."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    assert worker._retry_suppressed_job_id is None
    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_refresh_mv_skips_when_next_job_matches_suppressed_id(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """_refresh_mv_if_needed must skip the DB refresh when the suppressed job ID matches the next pending job."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    target_job_id = uuid.uuid4()
    worker._retry_suppressed_job_id = target_job_id
    # Make _last_mv_refresh_time old enough that refresh would normally fire.
    worker._last_mv_refresh_time = datetime.min.replace(tzinfo=UTC)

    committed: list[bool] = []
    scalar_calls: list[object] = []

    class _FakeResult:
        def __init__(self, value: object) -> None:
            self._value = value

        def scalar(self) -> object:
            return self._value

    class _FakeSession:
        async def commit(self) -> None:
            committed.append(True)

        async def scalar(self, stmt: object) -> object:  # noqa: ANN001
            scalar_calls.append(stmt)
            return target_job_id  # next job matches the suppressed ID

    now = datetime.now(tz=UTC)
    await worker._refresh_mv_if_needed(_FakeSession(), now)

    suppressed_after: uuid.UUID | None = worker._retry_suppressed_job_id
    assert suppressed_after is None, "suppressed ID must be cleared"
    assert committed == [], "commit must not be called when MV refresh is suppressed"
    assert len(scalar_calls) == 1, "should peek the pending queue once"

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_refresh_mv_proceeds_when_next_job_differs_from_suppressed_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """_refresh_mv_if_needed must proceed with refresh when the next pending job is a different job."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    suppressed_id = uuid.uuid4()
    different_id = uuid.uuid4()
    worker._retry_suppressed_job_id = suppressed_id
    # Make _last_mv_refresh_time RECENT so the elapsed check aborts before any DB write.
    worker._last_mv_refresh_time = datetime.now(tz=UTC)

    class _FakeSession:
        async def commit(self) -> None:
            pass

        async def scalar(self, stmt: object) -> object:  # noqa: ANN001
            return different_id  # next job does NOT match

    now = datetime.now(tz=UTC)
    await worker._refresh_mv_if_needed(_FakeSession(), now)

    # Suppressed ID must be cleared even when suppression didn't apply.
    suppressed_after: uuid.UUID | None = worker._retry_suppressed_job_id
    assert suppressed_after is None

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# E15-11-BR-11 regression: factory must survive _ensure_embedding_runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_handler_keeps_object_store_factory_after_embedding_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """E15-11-BR-11: ScanWorker.__init__ wires an ObjectStoreFactory into the
    scan handler. _ensure_embedding_runtime later rebuilds the handler with
    the (now-real) detector + generator. That rebuild must preserve the
    factory; otherwise multipart queue items pass through as raw file:/// /
    strings to the detector and worker-side cleanup is silently disabled.
    """

    async def _fake_get_shared_adapter() -> object:
        return object()

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod", blob_root=tmp_path / "blobs"),
    )
    monkeypatch.setattr(scan_worker_module, "get_shared_insightface_adapter", _fake_get_shared_adapter)
    monkeypatch.setattr(scan_worker_module, "InsightFaceFaceDetector", _FakeDetector)
    monkeypatch.setattr(scan_worker_module, "InsightFaceEmbeddingGenerator", _FakeGenerator)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )

    initial_factory = worker._scan_handler._object_store_factory
    assert initial_factory is not None, "constructor must wire ObjectStoreFactory"

    await worker._ensure_embedding_runtime()

    rebuilt_factory = worker._scan_handler._object_store_factory
    assert rebuilt_factory is not None, (
        "BR-11: _ensure_embedding_runtime must preserve the ObjectStoreFactory "
        "when rebuilding the scan handler with the production detector/generator"
    )

    # Detector should now be the production InsightFace stub-equivalent.
    assert isinstance(worker._scan_handler._detector, _FakeDetector)

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_scan_handler_factory_persists_through_embedding_failure_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When the InsightFace adapter fails to load, _ensure_embedding_runtime
    falls back to stub detector/generator and rebuilds the handler. The
    factory must survive that fallback rebuild as well — otherwise a
    transient adapter failure permanently disables multipart support."""

    async def _failing_adapter() -> object:
        raise RuntimeError("transient failure")

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod", blob_root=tmp_path / "blobs"),
    )
    monkeypatch.setattr(scan_worker_module, "get_shared_insightface_adapter", _failing_adapter)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )

    await worker._ensure_embedding_runtime()

    assert worker._scan_handler._object_store_factory is not None, (
        "BR-11: factory must survive the stub-fallback rebuild on adapter failure"
    )

    await worker.__aexit__(None, None, None)
