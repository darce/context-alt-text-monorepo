from __future__ import annotations

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
async def test_scan_worker_reuses_shared_insightface_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = object()
    calls = 0

    async def _fake_get_shared_adapter() -> object:
        nonlocal calls
        calls += 1
        return adapter

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod"),
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
async def test_scan_worker_retries_runtime_init_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def _failing_get_shared_adapter() -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("transient load failure")

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="prod"),
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
