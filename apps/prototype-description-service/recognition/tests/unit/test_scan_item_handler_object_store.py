"""ScanItemHandler must propagate object_store_factory + cleanup (BR-08).

The async-worker path is the production default; once the multipart route
queues a file:// item, the worker has to (a) read the bytes through the
same per-tenant ObjectStore the route wrote into, and (b) clean up the
per-job directory once every queued item for that job finishes. Without
both, multipart uploads silently fail (BR-08) and disk fills up (the BR-07
cleanup deferral hands the responsibility here).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from recognition.application.scan.service import ScanService
from recognition.application.storage import FilesystemObjectStore, ObjectStore
from recognition.worker.handlers.scan import ScanItemHandler


@pytest.fixture
def handler_with_factory(tmp_path: Path):
    blob_root = tmp_path / "blobs"
    factory_calls: list[str] = []

    def factory(t: str) -> ObjectStore:
        factory_calls.append(t)
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    handler = ScanItemHandler(
        session_factory=MagicMock(),
        detector=MagicMock(),
        generator=MagicMock(),
        max_attempts=3,
        max_concurrency=2,
        object_store_factory=factory,
    )
    return handler, factory, factory_calls, blob_root


def test_scan_item_handler_accepts_object_store_factory(
    handler_with_factory,
) -> None:
    handler, _factory, _calls, _root = handler_with_factory
    assert handler._object_store_factory is not None


def test_scan_item_handler_forwards_factory_to_scan_service(
    handler_with_factory,
) -> None:
    """_build_scan_service must thread the factory into ScanService so
    process_media_item resolves file:// sources via the same per-tenant
    ObjectStore the multipart route wrote into."""
    handler, factory, _calls, _root = handler_with_factory
    service = handler._build_scan_service(MagicMock())
    assert isinstance(service, ScanService)
    assert service._object_store_factory is factory


def test_scan_item_handler_without_factory_keeps_legacy_construction(
    tmp_path: Path,
) -> None:
    handler = ScanItemHandler(
        session_factory=MagicMock(),
        detector=MagicMock(),
        generator=MagicMock(),
        max_attempts=3,
        max_concurrency=2,
    )
    service = handler._build_scan_service(MagicMock())
    assert service._object_store_factory is None


# ---------------------------------------------------------------------------
# Worker-side cleanup after job completion (BR-07/BR-08)
# ---------------------------------------------------------------------------


class _FakeRepo:
    def __init__(self, tenant_id: uuid.UUID) -> None:
        self._tenant_id = tenant_id

    async def get_job_tenant_id(self, *, job_id):
        return self._tenant_id


class _FakeQueue:
    def __init__(self, completed: bool) -> None:
        self._completed = completed

    async def refresh_job_progress(self, *, job_id):
        return self._completed


class _FakeSession:
    def __init__(self, repo, queue) -> None:
        self._repo = repo
        self._queue = queue
        self.added: list[object] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


class _FakeSessionFactory:
    def __init__(self, repo, queue) -> None:
        self._repo = repo
        self._queue = queue

    def __call__(self):
        return _FakeSession(self._repo, self._queue)


@pytest.mark.asyncio
async def test_worker_cleans_up_blobs_when_job_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E15-11-BR-07/BR-08: once the worker drains the last queued item for
    a job (queue.refresh_job_progress(...) returns True), the per-job
    ObjectStore directory must be removed via the worker's factory."""
    from recognition.worker.handlers import scan as scan_module

    tenant_uuid = uuid.uuid4()
    job_uuid = uuid.uuid4()
    tenant_id = str(tenant_uuid)
    job_id = str(job_uuid)
    blob_root = tmp_path / "blobs"

    # Plant blobs for the job (as if the route had written them).
    store = FilesystemObjectStore(root=blob_root, tenant_id=tenant_id)
    store.put(job_id=job_id, media_id="1", data=b"x")
    store.put(job_id=job_id, media_id="2", data=b"y")
    job_dir = blob_root / tenant_id / job_id
    assert job_dir.is_dir()

    fake_session_factory = _FakeSessionFactory(_FakeRepo(tenant_uuid), _FakeQueue(completed=True))

    # Patch the SqlAlchemyScanQueueRepository + ScanQueueService + bypass
    # constructors used inside _refresh_job_progress so they read from the
    # fake session.
    fake_repo = _FakeRepo(tenant_uuid)
    fake_queue = _FakeQueue(completed=True)
    monkeypatch.setattr(scan_module, "SqlAlchemyScanQueueRepository", lambda _session: fake_repo)
    monkeypatch.setattr(scan_module, "ScanQueueService", lambda _repo: fake_queue)
    monkeypatch.setattr(scan_module, "enable_rls_bypass", _async_noop)
    monkeypatch.setattr(scan_module, "IdentityClusteringJob", lambda **_kwargs: object())

    def factory(t: str) -> ObjectStore:
        return FilesystemObjectStore(root=blob_root, tenant_id=t)

    handler = ScanItemHandler(
        session_factory=fake_session_factory,
        detector=MagicMock(),
        generator=MagicMock(),
        max_attempts=3,
        max_concurrency=2,
        object_store_factory=factory,
    )

    await handler._refresh_job_progress({job_uuid})

    assert not job_dir.exists(), "worker must clean up the per-job blob dir once the job completes"


# Helpers for the worker cleanup test ----------------------------------------


async def _async_noop(*_args, **_kwargs):
    return None


def session_queue_proxy(repo):
    """Return a queue-like object backed by the fake repo's queue attribute,
    matching the ScanQueueService surface _refresh_job_progress depends on."""

    class _Queue:
        async def refresh_job_progress(self, *, job_id):
            return await repo._queue.refresh_job_progress(job_id=job_id)

    return _Queue()
