"""A retry recovers the commit/dispatch gap without duplicating queue work."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan import service as scan_service_module
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.scan.service import ScanService
from recognition.domain.job import JobStatus
from recognition.interface_adapters.http.routers import analyze
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest


@pytest.mark.asyncio
async def test_save_job_results_refreshes_retained_job_after_external_failure(
    monkeypatch,
):
    # Real ORM identity maps, using synchronous SQLite to avoid threaded drivers.
    engine = create_engine("sqlite:///:memory:")
    IdentityScanJob.metadata.create_all(
        engine,
        tables=[IdentityScanJob.__table__, IdentityScanJobItem.__table__],
    )
    tenant_id = uuid.uuid4()
    job_id = uuid.uuid4()
    retained_job = IdentityScanJob(
        id=job_id,
        tenant_id=tenant_id,
        status=JobStatus.RUNNING,
        media_ids=[1],
        total_media=1,
        processed_media=0,
        identities_detected=0,
        error_message="inline:retained-owner",
    )
    with Session(engine, expire_on_commit=False) as orm_session:
        orm_session.add(retained_job)
        orm_session.commit()
        with Session(engine) as other_session:
            job = other_session.get(IdentityScanJob, job_id)
            job.status = JobStatus.FAILED
            job.error_message = "stalled job"
            other_session.commit()

        assert retained_job.status == JobStatus.RUNNING
        session = MagicMock()
        session.scalar = AsyncMock(side_effect=orm_session.scalar)
        session.commit = AsyncMock(side_effect=orm_session.commit)
        service = ScanService(session=session)
        persist = AsyncMock(return_value=SimpleNamespace(total=1))
        monkeypatch.setattr(service, "_persist_identities", persist)
        emit = MagicMock()
        monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", emit)
        result = await service.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant_id),
            media_ids=["1"],
            media_sources=None,
            detections=[],
        )

        assert result is retained_job
        assert retained_job.status == JobStatus.FAILED
        assert retained_job.error_message == "stalled job"
        assert retained_job.completed_at is None
        assert retained_job.processed_media == 0
        assert retained_job.identities_detected == 0
        persist.assert_not_awaited()
        emit.assert_not_called()
        session.commit.assert_not_awaited()
        assert session.scalar.await_args.args[0]._for_update_arg is not None
    with Session(engine) as verification_session:
        persisted = verification_session.get(IdentityScanJob, job_id)
        assert persisted.status == JobStatus.FAILED
        assert persisted.completed_at is None
    engine.dispose()


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
            state.jobs.append(SimpleNamespace(id=kwargs["job_id"], status=JobStatus.PENDING, started_at=None))
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
        [(222222, "22222222-2222-2222-2222-222222222222")] if job_status == JobStatus.RUNNING else []
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


@pytest.mark.asyncio
async def test_active_inline_replay_renews_lease_without_starting_a_second_processor(persisted_queue, monkeypatch):
    state, session, tenant = persisted_queue
    job_id = "44444444-4444-4444-4444-444444444444"
    await analyze.ScanQueueService().create_scan_job_record(tenant_id=tenant.id, total=1, job_id=job_id)
    state.items.append((444444, job_id))
    monkeypatch.setattr(analyze, "INLINE_PROCESSING_LEASE", timedelta(milliseconds=50))
    monkeypatch.setattr(analyze, "INLINE_PROCESSING_HEARTBEAT_INTERVAL", timedelta(milliseconds=5))

    processor_started = asyncio.Event()
    finish_processor = asyncio.Event()
    heartbeat_renewed = asyncio.Event()
    process_calls = 0

    async def slow_processor(**kwargs):
        nonlocal process_calls
        process_calls += 1
        processor_started.set()
        await finish_processor.wait()

    renew_lease = analyze._renew_inline_processing_lease

    async def observe_heartbeat(**kwargs):
        renewed = await renew_lease(**kwargs)
        if renewed:
            heartbeat_renewed.set()
        return renewed

    monkeypatch.setattr(analyze, "process_scan_job_inline", slow_processor)
    monkeypatch.setattr(analyze, "_renew_inline_processing_lease", observe_heartbeat)
    kwargs = dispatch_kwargs(state, session, tenant)
    original_dispatch = asyncio.create_task(analyze._dispatch_persisted_analysis(**kwargs))
    await asyncio.wait_for(processor_started.wait(), timeout=1)
    first_started_at = state.jobs[0].started_at
    await asyncio.wait_for(heartbeat_renewed.wait(), timeout=1)
    await asyncio.sleep(0.08)

    assert state.jobs[0].started_at > first_started_at
    await analyze._dispatch_persisted_analysis(**kwargs)
    assert process_calls == 1

    finish_processor.set()
    await original_dispatch
    assert state.jobs[0].error_message is None


@pytest.mark.asyncio
async def test_fenced_inline_processor_cannot_renew_reclaimed_lease(persisted_queue):
    state, session, tenant = persisted_queue
    job_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
    await analyze.ScanQueueService().create_scan_job_record(tenant_id=tenant.id, total=1, job_id=str(job_id))
    job = state.jobs[0]
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(tz=UTC) - analyze.INLINE_PROCESSING_LEASE - timedelta(seconds=1)
    job.error_message = "inline:new-owner"
    stale_lease = job.started_at

    renewed = await analyze._renew_inline_processing_lease(
        session_factory=lambda: session,
        tenant_id=uuid.UUID(str(tenant.id)),
        job_id=job_id,
        owner_token="inline:old-owner",
    )

    assert renewed is False
    assert job.started_at == stale_lease
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_inline_lease_cancels_processor_before_persistence(monkeypatch):
    monkeypatch.setattr(analyze, "INLINE_PROCESSING_HEARTBEAT_INTERVAL", timedelta(milliseconds=1))
    processor_started = asyncio.Event()
    renewal_attempted = asyncio.Event()
    processor_cancelled = asyncio.Event()
    persistence_steps = []
    processor_tasks = []

    async def blocked_processor(**kwargs):
        processor_tasks.append(asyncio.current_task())
        processor_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            processor_cancelled.set()
            raise
        persistence_steps.append("persisted")

    async def terminal_renewal(**kwargs):
        renewal_attempted.set()
        return None

    monkeypatch.setattr(analyze, "process_scan_job_inline", blocked_processor)
    monkeypatch.setattr(analyze, "_renew_inline_processing_lease", terminal_renewal)
    monkeypatch.setattr(analyze, "_clear_inline_processing_owner", AsyncMock())
    kwargs = {
        "session_factory": object(),
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "job_id": "22222222-2222-2222-2222-222222222222",
        "media_ids": [],
        "media_sources": [],
        "adapter_provider": None,
    }

    processing = asyncio.create_task(
        analyze._process_inline_with_lease(kwargs=kwargs, owner_token="inline:terminal-test")
    )
    await asyncio.wait_for(processor_started.wait(), timeout=1)
    await asyncio.wait_for(renewal_attempted.wait(), timeout=1)
    await asyncio.wait_for(processing, timeout=0.5)

    await asyncio.wait_for(processor_cancelled.wait(), timeout=1)
    assert processor_tasks[0].cancelled()
    assert persistence_steps == []


@pytest.mark.asyncio
async def test_save_job_results_preserves_failed_job_without_persisting(monkeypatch):
    job_id = uuid.uuid4()
    tenant_id = "11111111-1111-1111-1111-111111111111"
    job = SimpleNamespace(
        id=job_id,
        status=JobStatus.FAILED,
        completed_at=None,
        processed_media=0,
        identities_detected=0,
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=job)
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()
    service = ScanService(session=session)
    persist_identities = AsyncMock(return_value=SimpleNamespace(total=1))
    monkeypatch.setattr(service, "_persist_identities", persist_identities)
    emit_reconciled = MagicMock()
    monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", emit_reconciled)

    result = await service.save_job_results(
        job_id=job_id,
        tenant_id=tenant_id,
        media_ids=["22222222-2222-2222-2222-222222222222"],
        media_sources=None,
        detections=[],
    )

    assert result is job
    assert job.status == JobStatus.FAILED
    assert job.completed_at is None
    session.scalar.assert_awaited_once()
    assert session.scalar.await_args.args[0]._for_update_arg is not None
    persist_identities.assert_not_awaited()
    session.commit.assert_not_awaited()
    emit_reconciled.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_heartbeat_preserves_post_commit_reconcile_events(monkeypatch):
    monkeypatch.setattr(analyze, "INLINE_PROCESSING_HEARTBEAT_INTERVAL", timedelta(milliseconds=1))
    committed = asyncio.Event()
    resume_commit = asyncio.Event()
    job_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    job = SimpleNamespace(status=JobStatus.RUNNING, error_message="inline:commit-test")
    session = MagicMock()
    session.scalar = AsyncMock(return_value=job)

    async def commit():
        # Model the database exposing COMPLETED before commit() returns to Python.
        committed.set()
        await resume_commit.wait()

    session.commit = AsyncMock(side_effect=commit)
    service = ScanService(session=session)
    monkeypatch.setattr(service, "_persist_identities", AsyncMock(return_value=SimpleNamespace(total=0)))
    emit_reconciled = MagicMock()
    monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", emit_reconciled)

    async def processor(**kwargs):
        await service.save_job_results(
            job_id=job_id,
            tenant_id=tenant_id,
            media_ids=["1", "2"],
            media_sources=None,
            detections=[],
        )

    async def renewal(**kwargs):
        await committed.wait()
        assert job.status == JobStatus.COMPLETED
        # Resume only after the heartbeat has cancelled the processor.
        asyncio.get_running_loop().call_later(0.01, resume_commit.set)
        return None

    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)
    monkeypatch.setattr(analyze, "_renew_inline_processing_lease", renewal)
    cleanup = AsyncMock()
    monkeypatch.setattr(analyze, "_clear_inline_processing_owner", cleanup)
    await asyncio.wait_for(
        analyze._process_inline_with_lease(
            kwargs={
                "session_factory": object(),
                "tenant_id": tenant_id,
                "job_id": str(job_id),
                "media_ids": ["1", "2"],
                "media_sources": [],
                "adapter_provider": None,
            },
            owner_token="inline:commit-test",
        ),
        timeout=1,
    )

    assert emit_reconciled.call_count == 2
    assert [call.kwargs["media_id"] for call in emit_reconciled.call_args_list] == [1, 2]
    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_heartbeat_and_shutdown_preserve_reconcile_events(monkeypatch):
    monkeypatch.setattr(analyze, "INLINE_PROCESSING_HEARTBEAT_INTERVAL", timedelta(milliseconds=1))
    committed = asyncio.Event()
    resume_commit = asyncio.Event()
    commit_finished = asyncio.Event()
    heartbeat_cancelled = asyncio.Event()
    shutdown_cancelled = asyncio.Event()
    original_shield = asyncio.shield

    def observe_shield(task):
        future = original_shield(task)

        def signal_cancellation(done):
            if done.cancelled():
                if heartbeat_cancelled.is_set():
                    shutdown_cancelled.set()
                else:
                    heartbeat_cancelled.set()

        future.add_done_callback(signal_cancellation)
        return future

    monkeypatch.setattr(asyncio, "shield", observe_shield)
    job_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    job = SimpleNamespace(status=JobStatus.RUNNING, error_message="inline:shutdown-test")
    session = MagicMock()
    session.scalar = AsyncMock(return_value=job)

    async def commit():
        committed.set()
        await resume_commit.wait()
        commit_finished.set()

    session.commit = AsyncMock(side_effect=commit)
    service = ScanService(session=session)
    monkeypatch.setattr(service, "_persist_identities", AsyncMock(return_value=SimpleNamespace(total=0)))
    emit_reconciled = MagicMock()
    monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", emit_reconciled)
    processor_tasks = []

    async def processor(**kwargs):
        processor_tasks.append(asyncio.current_task())
        await service.save_job_results(
            job_id=job_id,
            tenant_id=tenant_id,
            media_ids=["1", "2"],
            media_sources=None,
            detections=[],
        )

    async def renewal(**kwargs):
        await committed.wait()
        assert job.status == JobStatus.COMPLETED
        return None

    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)
    monkeypatch.setattr(analyze, "_renew_inline_processing_lease", renewal)
    cleanup = AsyncMock()
    monkeypatch.setattr(analyze, "_clear_inline_processing_owner", cleanup)
    processing = asyncio.create_task(
        analyze._process_inline_with_lease(
            kwargs={
                "session_factory": object(),
                "tenant_id": tenant_id,
                "job_id": str(job_id),
                "media_ids": ["1", "2"],
                "media_sources": [],
                "adapter_provider": None,
            },
            owner_token="inline:shutdown-test",
        )
    )

    await asyncio.wait_for(heartbeat_cancelled.wait(), timeout=1)
    processing.cancel()
    await asyncio.wait_for(shutdown_cancelled.wait(), timeout=1)
    resume_commit.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(processing, timeout=1)

    assert processor_tasks[0].cancelling() >= 2
    assert processor_tasks[0].cancelled()
    session.commit.assert_awaited_once()
    assert commit_finished.is_set()
    assert [call.kwargs["media_id"] for call in emit_reconciled.call_args_list] == [1, 2]
    cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_reclaimed_inline_owner_cannot_persist_running_job(monkeypatch):
    job_id = uuid.uuid4()
    tenant_id = str(uuid.uuid4())
    job = SimpleNamespace(status=JobStatus.RUNNING, error_message="inline:new-owner", completed_at=None)
    session = MagicMock()
    session.scalar = AsyncMock(return_value=job)
    session.commit = AsyncMock()
    service = ScanService(session=session)
    persist_identities = AsyncMock(return_value=SimpleNamespace(total=0))
    monkeypatch.setattr(service, "_persist_identities", persist_identities)
    emit_reconciled = MagicMock()
    monkeypatch.setattr(scan_service_module, "_emit_scan_media_reconciled", emit_reconciled)

    async def processor(**kwargs):
        assert (
            await service.save_job_results(
                job_id=job_id,
                tenant_id=tenant_id,
                media_ids=["1"],
                media_sources=None,
                detections=[],
            )
            is job
        )

    monkeypatch.setattr(analyze, "process_scan_job_inline", processor)
    monkeypatch.setattr(analyze, "_clear_inline_processing_owner", AsyncMock())
    await analyze._process_inline_with_lease(
        kwargs={
            "session_factory": object(),
            "tenant_id": tenant_id,
            "job_id": str(job_id),
            "media_ids": ["1"],
            "media_sources": [],
            "adapter_provider": None,
        },
        owner_token="inline:old-owner",
    )

    assert job.status == JobStatus.RUNNING
    assert job.completed_at is None
    persist_identities.assert_not_awaited()
    session.commit.assert_not_awaited()
    emit_reconciled.assert_not_called()
