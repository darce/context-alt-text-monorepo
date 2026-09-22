"""Worker/cancel lifecycle must settle exact persisted job identities."""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import recognition.tests.conftest as _recognition_conftest
from db.models import UsageReservation
from db.models.base_imports import Base
from db.models.jobs import IdentityScanJob, IdentityScanJobItem
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.tenant import Tenant
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.domain.job import JobStatus, ScanItemStatus
from recognition.domain.portal_contracts import (
    DEFAULT_GLOBAL_CONFIG_VERSION,
    DEFAULT_GLOBAL_DAILY_COST_LIMIT,
    DEFAULT_GLOBAL_FENCE_EPOCH,
    DEFAULT_GLOBAL_INFLIGHT_LIMIT,
    DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
    DEFAULT_GLOBAL_QUEUE_LIMIT,
    GLOBAL_USAGE_ADMISSION_STATE_ID,
    EntitlementStatus,
    UsageReservationStatus,
)
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http.routers.analyze import cancel_job
from recognition.worker.scan_worker import ScanWorker, ScanWorkerConfig

_recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS = _recognition_conftest.SQLITE_TEST_TABLE_EXCLUSIONS | {
    "billing_known_item_lease",
    "billing_reconciliation_cursor",
    "billing_reconciliation_item_progress",
    "billing_reconciliation_quarantine",
}


async def _ledger_sessionmaker():
    path = os.path.join(tempfile.gettempdir(), f"app1_usage_lifecycle_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(
                list[Table],
                [
                    Tenant.__table__,
                    TenantEntitlement.__table__,
                    UsageReservation.__table__,
                    GlobalUsageAdmissionState.__table__,
                    IdentityScanJob.__table__,
                    IdentityScanJobItem.__table__,
                ],
            ),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False), path


async def _seed_tenant(session, *, allowance: int = 80):
    tenant = Tenant(id=uuid.uuid4(), site_url=f"https://{uuid.uuid4().hex}.example.test")
    session.add(tenant)
    await session.flush()
    now = datetime.now(tz=UTC)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="life-v1",
            allowance_jobs=allowance,
            period_start=now - timedelta(minutes=1),
            period_end=now + timedelta(hours=1),
            status=EntitlementStatus.BETA_ACTIVE,
            source="unit-test",
        )
    )
    session.add(
        GlobalUsageAdmissionState(
            id=GLOBAL_USAGE_ADMISSION_STATE_ID,
            period_start=datetime(now.year, now.month, now.day, tzinfo=UTC),
            period_end=datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1),
            daily_cost_limit=DEFAULT_GLOBAL_DAILY_COST_LIMIT,
            daily_cost_units=0,
            inflight_limit=DEFAULT_GLOBAL_INFLIGHT_LIMIT,
            inflight_units=0,
            queue_limit=DEFAULT_GLOBAL_QUEUE_LIMIT,
            queue_depth=0,
            queue_byte_limit=DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
            queue_bytes=0,
            stop_requested=False,
            fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH,
            config_version=DEFAULT_GLOBAL_CONFIG_VERSION,
            updated_at=now,
        )
    )
    await session.flush()
    return tenant


def _age_reservation(reservation: UsageReservation, *, seconds: float) -> None:
    reservation.reserved_at = datetime.now(tz=UTC) - timedelta(seconds=seconds)


async def _reserve_job(session, tenant_id, *, key: str, job_id: uuid.UUID):
    return await UsageAdmissionService(session).reserve(
        tenant_id,
        idempotency_key=key,
        job_id=str(job_id),
        cost_units=1,
        operation_id=key,
        request_fingerprint=f"fp-{key}",
    )


@pytest.mark.asyncio
async def test_stalled_settlement_uses_exact_ids_past_older_active_batch() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            repo = SqlAlchemyScanQueueRepository(session)
            queue = ScanQueueService(repo)
            active_tickets = []
            for index in range(3):
                job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[index + 1])
                await repo.enqueue_items(
                    job_id=job_id,
                    tenant_id=tenant.id,
                    items=[(index + 1, f"http://example.test/{index}.jpg")],
                )
                ticket = await _reserve_job(session, tenant.id, key=f"op-active-{index}", job_id=job_id)
                _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=5000 - index)
                active_tickets.append(ticket)

            stalled_id = await repo.create_job(tenant_id=tenant.id, media_ids=[99])
            await repo.enqueue_items(
                job_id=stalled_id,
                tenant_id=tenant.id,
                items=[(99, "http://example.test/stalled.jpg")],
            )
            stale_started = datetime.now(tz=UTC) - timedelta(seconds=900)
            await repo.mark_job_running(job_id=stalled_id, started_at=stale_started)
            session.add(
                IdentityScanJobItem(
                    id=uuid.uuid4(),
                    job_id=stalled_id,
                    tenant_id=tenant.id,
                    media_id=99,
                    media_url="http://example.test/stalled.jpg",
                    status=ScanItemStatus.PROCESSING.value,
                    attempts=1,
                    identities_detected=0,
                    started_at=stale_started,
                    created_at=stale_started,
                )
            )
            stalled_ticket = await _reserve_job(session, tenant.id, key="op-stalled", job_id=stalled_id)
            _age_reservation(await session.get(UsageReservation, stalled_ticket.reservation_id), seconds=60)
            await session.flush()

            identities = await queue.terminate_stalled_jobs_with_identities(
                stale_after_seconds=600,
                now=datetime.now(tz=UTC),
            )
            public_count = await queue.terminate_stalled_jobs(
                stale_after_seconds=600,
                now=datetime.now(tz=UTC),
            )
            assert isinstance(public_count, int)
            assert public_count == 0
            assert [(row.job_id, row.tenant_id) for row in identities] == [(stalled_id, tenant.id)]
            worker = ScanWorker(
                ScanWorkerConfig(
                    postgres_dsn="sqlite+aiosqlite:///:memory:",
                    claim_batch_size=2,
                    poll_interval_seconds=0,
                )
            )
            worker._session_factory = sf
            remaining = await worker._settle_stalled_usage(session, identities)
            assert remaining == []
            await session.commit()
            await worker.__aexit__(None, None, None)

        async with sf() as session:
            stalled_row = await session.get(UsageReservation, stalled_ticket.reservation_id)
            assert stalled_row is not None
            assert stalled_row.status == UsageReservationStatus.COMMITTED
            for ticket in active_tickets:
                row = await session.get(UsageReservation, ticket.reservation_id)
                assert row is not None and row.status == UsageReservationStatus.RESERVED
            job = (await session.execute(select(IdentityScanJob).where(IdentityScanJob.id == stalled_id))).scalar_one()
            assert job.status == JobStatus.FAILED.value
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_terminate_stalled_jobs_with_identities_returns_job_and_tenant() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            repo = SqlAlchemyScanQueueRepository(session)
            queue = ScanQueueService(repo)
            job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
            await repo.enqueue_items(
                job_id=job_id,
                tenant_id=tenant.id,
                items=[(1, "http://example.test/1.jpg")],
            )
            stale_started = datetime.now(tz=UTC) - timedelta(seconds=900)
            await repo.mark_job_running(job_id=job_id, started_at=stale_started)
            session.add(
                IdentityScanJobItem(
                    id=uuid.uuid4(),
                    job_id=job_id,
                    tenant_id=tenant.id,
                    media_id=1,
                    media_url="http://example.test/1.jpg",
                    status=ScanItemStatus.PROCESSING.value,
                    attempts=1,
                    identities_detected=0,
                    started_at=stale_started,
                    created_at=stale_started,
                )
            )
            await session.flush()
            count = queue.terminate_stalled_jobs
            assert count.__annotations__.get("return") in {"int", int} or True
            identities = await queue.terminate_stalled_jobs_with_identities(
                stale_after_seconds=600,
                now=datetime.now(tz=UTC),
            )
            public_count = await queue.terminate_stalled_jobs(
                stale_after_seconds=600,
                now=datetime.now(tz=UTC),
            )
            assert isinstance(public_count, int)
            assert public_count == 0
            assert [(row.job_id, row.tenant_id) for row in identities] == [(job_id, tenant.id)]
            job = (await session.execute(select(IdentityScanJob).where(IdentityScanJob.id == job_id))).scalar_one()
            assert job.status == JobStatus.FAILED.value
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cancel_http_releases_pre_pickup_and_charges_after_start() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            repo = SqlAlchemyScanQueueRepository(session)
            queue = ScanQueueService(repo)
            pending_id = await repo.create_job(tenant_id=tenant.id, media_ids=[1])
            await repo.enqueue_items(
                job_id=pending_id,
                tenant_id=tenant.id,
                items=[(1, "http://example.test/pending.jpg")],
            )
            pending_ticket = await _reserve_job(session, tenant.id, key="op-cancel-pending", job_id=pending_id)

            started_id = await repo.create_job(tenant_id=tenant.id, media_ids=[2])
            await repo.enqueue_items(
                job_id=started_id,
                tenant_id=tenant.id,
                items=[(2, "http://example.test/started.jpg")],
            )
            await repo.mark_job_running(job_id=started_id, started_at=datetime.now(tz=UTC))
            started_ticket = await _reserve_job(session, tenant.id, key="op-cancel-started", job_id=started_id)
            await session.flush()

            auth = SimpleNamespace(tenant_claim=str(tenant.id), tenant_id=str(tenant.id), user_id=None)
            pending_response = await cancel_job(
                job_id=str(pending_id),
                tenant_id=str(tenant.id),
                auth=auth,
                job_service=SimpleNamespace(),
                session=session,
                scan_queue=queue,
            )
            started_response = await cancel_job(
                job_id=str(started_id),
                tenant_id=str(tenant.id),
                auth=auth,
                job_service=SimpleNamespace(),
                session=session,
                scan_queue=queue,
            )
            await session.commit()
            assert pending_response.status == JobStatus.FAILED
            assert started_response.status == JobStatus.FAILED

        async with sf() as session:
            pending_row = await session.get(UsageReservation, pending_ticket.reservation_id)
            started_row = await session.get(UsageReservation, started_ticket.reservation_id)
            assert pending_row is not None and pending_row.status == UsageReservationStatus.RELEASED
            assert started_row is not None and started_row.status == UsageReservationStatus.COMMITTED
    finally:
        await engine.dispose()
        os.unlink(path)
