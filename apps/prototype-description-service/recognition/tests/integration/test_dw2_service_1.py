"""Regression coverage for deferred scan persist-lock findings."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session

import recognition.application.scan.service as scan_service
import recognition.worker.scan_worker as scan_worker
from recognition.application.embedding.detector import FaceDetection
from recognition.application.embedding.generator import EmbeddingGeneratorProtocol, EmbeddingResult
from recognition.application.scan.service import (
    _IN_PROCESS_PERSIST_LOCKS,
    ReconcileResult,
    ScanService,
    _InProcessPersistLockEntry,
    _media_persist_lock,
    _persist_lock_key,
    _release_in_process_persist_waiter,
)

_DIM = int(scan_service._DB_SETTINGS.pgvector_dimension)


class _Scalars:
    def all(self) -> list[object]:
        return []


class _Result:
    def scalars(self) -> _Scalars:
        return _Scalars()


class _Session:
    def __init__(self, dialect_name: str | None = None) -> None:
        if dialect_name is not None:
            self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.executed: list[str] = []
        self.added: list[object] = []
        self.committed = False

    async def execute(self, statement: object, _params: object = None) -> _Result:
        self.executed.append(str(statement))
        return _Result()

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)

    async def delete(self, _row: object) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def get(self, _model: object, _key: object) -> object:
        return SimpleNamespace(
            processed_media=0,
            identities_detected=0,
            status=None,
            completed_at=None,
        )

    async def commit(self) -> None:
        self.committed = True


class _BlockingGenerator(EmbeddingGeneratorProtocol):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.finish = asyncio.Event()

    async def generate(self, face_images: Iterable[bytes]) -> list[EmbeddingResult]:
        self.started.set()
        await self.finish.wait()
        return [
            EmbeddingResult(
                media_id="generated",
                embedding=np.eye(1, _DIM, dtype=np.float32)[0],
                confidence=0.99,
            )
            for _ in face_images
        ]


def _unembedded_detection() -> FaceDetection:
    return FaceDetection(
        media_id="42",
        bbox=(10, 10, 50, 50),
        confidence=0.95,
        embedding=None,
        model_id="test-model",
    )


@pytest.mark.asyncio
async def test_postgres_dialect_prefix_takes_advisory_lock() -> None:
    session = _Session("postgresql+asyncpg")
    tenant_id = uuid.uuid4()

    async with _media_persist_lock(session, tenant_id, 42):  # type: ignore[arg-type]
        pass

    assert len([statement for statement in session.executed if "pg_advisory_xact_lock" in statement]) == 1


def test_postgres_probe_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_probe(_session: object) -> bool:
        raise RuntimeError("dialect probe failed")

    monkeypatch.setattr(scan_service, "is_postgres", broken_probe, raising=False)

    with pytest.raises(RuntimeError, match="dialect probe failed"):
        scan_service._session_is_postgres(_Session())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_embeddings_are_generated_before_the_media_persist_lock() -> None:
    session = _Session()
    generator = _BlockingGenerator()
    service = ScanService(session=session, generator=generator)  # type: ignore[arg-type]
    tenant_id = uuid.uuid4()
    persist_task = asyncio.create_task(
        service._persist_identities(
            tenant_uuid=tenant_id,
            media_id=42,
            detections=[_unembedded_detection()],
        )
    )
    await asyncio.wait_for(generator.started.wait(), timeout=1)

    second_lock_acquired = False
    try:
        async with asyncio.timeout(0.1):
            async with _media_persist_lock(session, tenant_id, 42):  # type: ignore[arg-type]
                second_lock_acquired = True
    except TimeoutError:
        pass
    finally:
        generator.finish.set()
        await asyncio.wait_for(persist_task, timeout=1)

    assert second_lock_acquired, "embedding generation held the media persist lock"


@pytest.mark.asyncio
async def test_save_job_results_locks_media_in_stable_order(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    service = ScanService(session=session)  # type: ignore[arg-type]
    persisted_media: list[int] = []

    async def record_persist(**kwargs: object) -> ReconcileResult:
        persisted_media.append(int(kwargs["media_id"]))
        return ReconcileResult(detected=0, matched=0, new=0, skipped=0, mixed_model=False)

    monkeypatch.setattr(service, "_persist_identities", record_persist)
    monkeypatch.setattr(scan_service, "_emit_scan_media_reconciled", lambda **_kwargs: None)

    await service.save_job_results(
        job_id=uuid.uuid4(),
        tenant_id=str(uuid.uuid4()),
        media_ids=["22", "11"],
        media_sources=None,
        detections=[],
    )

    assert persisted_media == [11, 22]


@pytest.mark.asyncio
async def test_worker_installs_transaction_local_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = getattr(scan_worker, "_apply_worker_lock_timeout", None)
    install = getattr(scan_worker, "_install_worker_lock_timeout", None)
    assert callable(hook), "worker transaction lock-timeout hook is missing"
    assert callable(install), "worker transaction lock-timeout hook is not installed"

    statements: list[str] = []
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        exec_driver_sql=statements.append,
    )
    hook(connection)
    assert statements == ["SET LOCAL lock_timeout = '5s'"]

    engine = create_engine("sqlite://")
    try:
        install(engine)
        assert hook in engine.dispatch.begin
    finally:
        engine.dispose()

    async_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    installed_engines: list[object] = []
    install_original = install

    def record_install(engine_to_install: object) -> None:
        installed_engines.append(engine_to_install)
        install_original(engine_to_install)  # type: ignore[arg-type]

    monkeypatch.setattr(scan_worker, "_install_worker_lock_timeout", record_install)
    monkeypatch.setattr(scan_worker, "create_async_engine", lambda *_args, **_kwargs: async_engine)
    worker = scan_worker.ScanWorker(
        scan_worker.ScanWorkerConfig(
            postgres_dsn="postgresql+asyncpg://worker:worker@localhost/db",
            metrics_export_enabled=False,
        )
    )
    try:
        assert installed_engines == [async_engine.sync_engine]
        assert hook in async_engine.sync_engine.dispatch.begin
    finally:
        await worker._engine.dispose()


def test_lock_waiter_registry_release_uses_its_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ProbeGuard:
        entered = False

        def __enter__(self) -> _ProbeGuard:
            self.entered = True
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    _IN_PROCESS_PERSIST_LOCKS.clear()
    guard = _ProbeGuard()
    monkeypatch.setattr(scan_service, "_IN_PROCESS_PERSIST_LOCKS_GUARD", guard)
    tenant_id = uuid.uuid4()
    media_id = 42
    key = _persist_lock_key(tenant_id, media_id)
    _IN_PROCESS_PERSIST_LOCKS[key] = _InProcessPersistLockEntry(lock=asyncio.Lock(), waiters=1)

    _release_in_process_persist_waiter(tenant_id, media_id)

    assert guard.entered
    assert key not in _IN_PROCESS_PERSIST_LOCKS


@pytest.mark.asyncio
async def test_listener_removal_failures_are_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    engine = create_engine("sqlite://")
    session = _Session("sqlite")
    session.sync_session = Session(engine)

    def failed_remove(*_args: object) -> None:
        raise RuntimeError("listener removal failed")

    monkeypatch.setattr(scan_service.event, "remove", failed_remove)
    try:
        async with _media_persist_lock(session, uuid.uuid4(), 42):  # type: ignore[arg-type]
            pass
    finally:
        session.sync_session.close()
        engine.dispose()

    assert "Failed to remove persist-lock listener" in caplog.text
