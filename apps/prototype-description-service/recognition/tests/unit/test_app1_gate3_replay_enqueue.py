"""A retry recovers the commit/dispatch gap without duplicating queue work."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.domain.job import JobStatus
from recognition.interface_adapters.http.routers import analyze
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest


class Admission:
    def __init__(self):
        self.ticket = None
        self.release = AsyncMock()
        self.commit = AsyncMock()

    async def reserve(self, tenant_id, **kwargs):
        if self.ticket is None:
            self.ticket = SimpleNamespace(job_id=kwargs["job_id"])
        return self.ticket


async def submit(tenant, session, admission, tasks):
    payload = {"tenant_id": str(tenant.id), "media_ids": ["22222222-2222-2222-2222-222222222222"]}

    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode()}

    return await analyze.analyze_media(
        request=AnalyzeRequest(**payload),
        background_tasks=tasks,
        http_request=Request({"type": "http"}, receive),
        idempotency_key="recover-commit-gap",
        auth=None,
        session=session,
        scan_queue=analyze.ScanQueueService(),
        usage_admission_service=admission,
    )


@pytest.fixture
def persisted_queue(monkeypatch):
    # Keep this unit test independent of threaded SQLite drivers and services.
    # The real dispatch helper still decides whether/when to populate work.
    state = SimpleNamespace(jobs=[], items=[])
    session = MagicMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    async def scalar(statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is IdentityScanJob:
            assert statement._for_update_arg is not None
            return state.jobs[0] if state.jobs else None
        assert entity is IdentityScanJobItem
        return state.items[0] if state.items else None

    session.scalar = AsyncMock(side_effect=scalar)

    class Queue(ScanQueueService):
        def __init__(self, repository=None):
            pass

        async def create_scan_job_record(self, **kwargs):
            state.jobs.append(
                SimpleNamespace(id=kwargs["job_id"], status=JobStatus.PENDING, started_at=None)
            )
            return kwargs["job_id"]

        async def populate_scan_job_items(self, **kwargs):
            assert kwargs["job_id"] == state.jobs[0].id
            state.items.extend(kwargs["media_items"])
            return len(kwargs["media_items"])

    monkeypatch.setattr(analyze, "ScanQueueService", Queue)
    monkeypatch.setattr(analyze, "async_sessionmaker", lambda **kwargs: lambda: session)
    monkeypatch.setattr(analyze, "is_postgres", lambda session: False)
    monkeypatch.setattr("db.tenant_context.set_tenant_context", AsyncMock())
    tenant = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
    return state, session, tenant


def dispatch_kwargs(state, session, tenant):
    job = state.jobs[0]
    return {
        "tenant_id": str(tenant.id),
        "job_id": str(job.id),
        "media_items": [(222222, "22222222-2222-2222-2222-222222222222")],
        "media_ids": ["22222222-2222-2222-2222-222222222222"],
        "media_sources": ["22222222-2222-2222-2222-222222222222"],
        "session_factory": lambda: session,
        "inline_processing": True,
        "adapter_provider": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("inline", [False, True])
async def test_replay_recovers_committed_job_and_dispatches_once(persisted_queue, monkeypatch, inline):
    state, session, tenant = persisted_queue
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", str(int(inline)))
    processor = AsyncMock()
    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)
    admission = Admission()
    original_tasks = BackgroundTasks()
    original = await submit(tenant, session, admission, original_tasks)
    # Simulate process exit after commit: do not run the original tasks.
    session.commit.assert_awaited_once()
    assert len(state.jobs) == 1
    assert state.items == []

    retries = [BackgroundTasks(), BackgroundTasks()]
    for tasks in retries:
        replay = await submit(tenant, session, admission, tasks)
        assert replay.id == original.id
        assert len(tasks.tasks) == 1
    # The retry must actually populate the queue, not just return 202.
    await retries[0]()
    assert state.items == [(222222, "22222222-2222-2222-2222-222222222222")]
    await retries[1]()
    # Also cover the original dispatch arriving late, after the recovery task.
    await original_tasks()
    assert len(state.jobs) == 1
    assert state.items == [(222222, "22222222-2222-2222-2222-222222222222")]
    assert processor.await_count == int(inline)
    admission.release.assert_not_awaited()
    admission.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("job_status", [JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED])
async def test_replay_does_not_restart_progressed_job(persisted_queue, monkeypatch, job_status):
    state, session, tenant = persisted_queue
    monkeypatch.setenv("RECOGNITION_ASYNC_ANALYZE_INLINE", "1")
    processor = AsyncMock()
    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)
    admission = Admission()
    await submit(tenant, session, admission, BackgroundTasks())
    state.jobs[0].status = job_status
    if job_status == JobStatus.RUNNING:
        state.jobs[0].started_at = datetime.now(tz=UTC)
        state.items.append((222222, "22222222-2222-2222-2222-222222222222"))
    tasks = BackgroundTasks()
    await submit(tenant, session, admission, tasks)
    await tasks()
    assert state.items == (
        [(222222, "22222222-2222-2222-2222-222222222222")]
        if job_status == JobStatus.RUNNING
        else []
    )
    processor.assert_not_awaited()


@pytest.mark.asyncio
async def test_replay_claims_populated_pending_job_once(persisted_queue, monkeypatch):
    state, session, tenant = persisted_queue
    job_id = "22222222-2222-2222-2222-222222222222"
    await analyze.ScanQueueService().create_scan_job_record(tenant_id=tenant.id, total=1, job_id=job_id)
    state.items.append((222222, job_id))
    processor = AsyncMock()
    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)

    await analyze._dispatch_persisted_analysis(**dispatch_kwargs(state, session, tenant))
    assert state.jobs[0].status == JobStatus.RUNNING
    processor.assert_awaited_once()

    await analyze._dispatch_persisted_analysis(**dispatch_kwargs(state, session, tenant))
    processor.assert_awaited_once()
    assert state.items == [(222222, job_id)]


@pytest.mark.asyncio
async def test_replay_reclaims_expired_inline_lease(persisted_queue, monkeypatch):
    state, session, tenant = persisted_queue
    job_id = "33333333-3333-3333-3333-333333333333"
    await analyze.ScanQueueService().create_scan_job_record(tenant_id=tenant.id, total=1, job_id=job_id)
    state.items.append((333333, job_id))
    state.jobs[0].status = JobStatus.RUNNING
    state.jobs[0].started_at = datetime.now(tz=UTC) - analyze.INLINE_PROCESSING_LEASE - timedelta(seconds=1)
    processor = AsyncMock()
    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)

    await analyze._dispatch_persisted_analysis(**dispatch_kwargs(state, session, tenant))

    processor.assert_awaited_once()
    assert state.jobs[0].started_at > datetime.now(tz=UTC) - timedelta(seconds=5)
