"""Regression tests for bounded stale reclaim and race-safe stall termination."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

import recognition.tests.conftest as _recognition_conftest
from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.domain.job import JobStatus, ScanItemStatus
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.worker import scan_worker as scan_worker_module

_recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS = _recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS | {
    "billing_known_item_lease",
    "billing_reconciliation_cursor",
    "billing_reconciliation_item_progress",
    "billing_reconciliation_quarantine",
}


@pytest.mark.asyncio
async def test_stall_termination_preserves_job_completed_after_candidate_selection(db_session, tenant) -> None:
    now = datetime.now(tz=UTC)
    job_id = uuid.uuid4()
    stale_started_at = now - timedelta(minutes=20)
    db_session.add(
        IdentityScanJob(
            id=job_id,
            tenant_id=tenant.id,
            status=JobStatus.RUNNING.value,
            media_ids=[1],
            total_media=1,
            processed_media=0,
            identities_detected=0,
            started_at=stale_started_at,
        )
    )
    db_session.add(
        IdentityScanJobItem(
            id=uuid.uuid4(),
            job_id=job_id,
            tenant_id=tenant.id,
            media_id=1,
            media_url="http://example.test/1.jpg",
            status=ScanItemStatus.PENDING.value,
            attempts=0,
            identities_detected=0,
            created_at=stale_started_at,
        )
    )
    await db_session.flush()

    class CompletesBeforeFailureRepository(SqlAlchemyScanQueueRepository):
        async def fail_job_if_active(self, *, job_id, completed_at, error_message):  # noqa: ANN001
            await self.complete_job(job_id=job_id, completed_at=completed_at)
            return await super().fail_job_if_active(
                job_id=job_id,
                completed_at=completed_at,
                error_message=error_message,
            )

    queue = ScanQueueService(CompletesBeforeFailureRepository(db_session))

    identities = await queue.terminate_stalled_jobs_with_identities(stale_after_seconds=600, now=now)

    job = (await db_session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
    assert job.status == JobStatus.COMPLETED.value
    assert identities == []


@pytest.mark.asyncio
async def test_stall_identities_match_jobs_transitioned_after_candidate_set_changes(db_session, tenant) -> None:
    now = datetime.now(tz=UTC)
    stale_started_at = now - timedelta(minutes=20)
    job_ids = sorted((uuid.uuid4() for _ in range(101)), key=str)
    db_session.add_all(
        [
            IdentityScanJob(
                id=job_id,
                tenant_id=tenant.id,
                status=JobStatus.RUNNING.value,
                media_ids=[index],
                total_media=1,
                processed_media=0,
                identities_detected=0,
                started_at=stale_started_at,
            )
            for index, job_id in enumerate(job_ids)
        ]
    )
    db_session.add_all(
        [
            IdentityScanJobItem(
                id=uuid.uuid4(),
                job_id=job_id,
                tenant_id=tenant.id,
                media_id=index,
                media_url=f"http://example.test/{index}.jpg",
                status=ScanItemStatus.PENDING.value,
                attempts=0,
                identities_detected=0,
                created_at=stale_started_at,
            )
            for index, job_id in enumerate(job_ids)
        ]
    )
    await db_session.flush()

    class CompletesFirstCandidateRepository(SqlAlchemyScanQueueRepository):
        async def fail_stalled_running_jobs(self, *, stale_after_seconds, now):  # noqa: ANN001
            await self.complete_job(job_id=job_ids[0], completed_at=now)
            return await super().fail_stalled_running_jobs(stale_after_seconds=stale_after_seconds, now=now)

    queue = ScanQueueService(CompletesFirstCandidateRepository(db_session))

    identities = await queue.terminate_stalled_jobs_with_identities(stale_after_seconds=600, now=now)

    assert [identity.job_id for identity in identities] == job_ids[1:]
    transitioned = (
        (
            await db_session.execute(
                select(IdentityScanJob.id)
                .where(IdentityScanJob.status == JobStatus.FAILED.value)
                .order_by(IdentityScanJob.started_at, IdentityScanJob.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(transitioned) == set(job_ids[1:])


@pytest.mark.asyncio
async def test_reclaim_stale_items_updates_only_one_bounded_batch(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    now = datetime.now(tz=UTC)
    stale_started_at = now - timedelta(minutes=20)
    job_id = uuid.uuid4()
    db_session.add(
        IdentityScanJob(
            id=job_id,
            tenant_id=tenant.id,
            status=JobStatus.RUNNING.value,
            media_ids=list(range(105)),
            total_media=105,
            processed_media=0,
            identities_detected=0,
            started_at=stale_started_at,
        )
    )
    db_session.add_all(
        [
            IdentityScanJobItem(
                id=uuid.uuid4(),
                job_id=job_id,
                tenant_id=tenant.id,
                media_id=index,
                media_url=f"http://example.test/{index}.jpg",
                status=ScanItemStatus.PROCESSING.value,
                attempts=1,
                identities_detected=0,
                started_at=stale_started_at,
                created_at=stale_started_at,
            )
            for index in range(105)
        ]
    )
    await db_session.flush()

    reclaimed = await repo.reclaim_stale_items(stale_after_seconds=600, max_attempts=3, now=now)
    pending_count = await db_session.scalar(
        select(func.count())
        .select_from(IdentityScanJobItem)
        .where(
            IdentityScanJobItem.job_id == job_id,
            IdentityScanJobItem.status == ScanItemStatus.PENDING.value,
        )
    )
    processing_count = await db_session.scalar(
        select(func.count())
        .select_from(IdentityScanJobItem)
        .where(
            IdentityScanJobItem.job_id == job_id,
            IdentityScanJobItem.status == ScanItemStatus.PROCESSING.value,
        )
    )

    assert reclaimed == 100
    assert pending_count == 100
    assert processing_count == 5


@pytest.mark.asyncio
async def test_worker_commits_reclaim_before_stall_maintenance_and_claims(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:", poll_interval_seconds=0)
    )
    events: list[str] = []
    sessions = []

    class FakeRepo:
        def __init__(self, session) -> None:  # noqa: ANN001
            self.session = session

        def assert_bypass(self, operation: str) -> None:
            assert self.session.rls_bypass_enabled, f"{operation} ran without the RLS bypass"

        async def reclaim_stale_items(self, **_kwargs):  # noqa: ANN001
            self.assert_bypass("reclaim")
            events.append("reclaim")
            return 1

        async def claim_pending_items_any(self, **_kwargs):  # noqa: ANN001
            self.assert_bypass("claim")
            events.append("claim")
            return []

    class FakeQueue:
        def __init__(self, repo) -> None:  # noqa: ANN001
            self.repo = repo

        async def terminate_stalled_jobs_with_identities(self, **_kwargs):  # noqa: ANN001
            self.repo.assert_bypass("stall termination")
            events.append("stall")
            return ["stalled-job"]

    class FakeSession:
        def __init__(self) -> None:
            self.rls_bypass_enabled = False
            self.transaction_id = 0
            self.local_statements_by_transaction: dict[int, list[str]] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def commit(self):
            events.append("commit")
            self.rls_bypass_enabled = False
            self.transaction_id += 1

    async def no_op(*_args, **_kwargs):  # noqa: ANN001
        return None

    async def enable_fake_rls_bypass(session):  # noqa: ANN001
        statement = "SET LOCAL app.bypass_rls = 'true'"
        session.local_statements_by_transaction.setdefault(session.transaction_id, []).append(statement)
        session.rls_bypass_enabled = True
        events.append("bypass")

    async def no_clustering(*, session, now):  # noqa: ANN001
        assert session.rls_bypass_enabled, "clustering selection ran without the RLS bypass"
        events.append("clustering")
        return False

    async def settle_stalled_usage(session, jobs):  # noqa: ANN001
        assert session.rls_bypass_enabled, "stalled-usage settlement ran without the RLS bypass"
        assert jobs == ["stalled-job"]
        events.append("settle")
        return []

    async def stop_after_tick(_delay):  # noqa: ANN001
        raise asyncio.CancelledError()

    monkeypatch.setattr(worker, "_probe_and_publish_embedding_runtime_capability", no_op)
    monkeypatch.setattr(worker, "_sweep_stale_usage_reservations_if_due", no_op)
    monkeypatch.setattr(worker, "_refresh_mv_if_needed", no_op)
    monkeypatch.setattr(worker, "_process_pending_clustering_jobs", no_clustering)
    monkeypatch.setattr(worker, "_settle_stalled_usage", settle_stalled_usage)

    def make_session() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr(worker, "_session_factory", make_session)
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", enable_fake_rls_bypass)
    monkeypatch.setattr(scan_worker_module, "SqlAlchemyScanQueueRepository", FakeRepo)
    monkeypatch.setattr(scan_worker_module, "ScanQueueService", FakeQueue)
    monkeypatch.setattr(scan_worker_module.asyncio, "sleep", stop_after_tick)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    assert events.index("commit") < events.index("stall") < events.index("settle")
    assert events.index("settle") < events.index("clustering") < events.index("claim")
    assert sessions[0].local_statements_by_transaction == {
        0: ["SET LOCAL app.bypass_rls = 'true'"],
        1: ["SET LOCAL app.bypass_rls = 'true'"],
    }
    await worker.__aexit__(None, None, None)
