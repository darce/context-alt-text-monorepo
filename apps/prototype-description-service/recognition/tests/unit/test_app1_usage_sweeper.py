"""APP-1 G3 sweeper: bounded scan, never release active work."""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import UsageReservation
from db.models.base_imports import Base
from db.models.jobs import IdentityScanJob, IdentityScanJobItem
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.application.services.usage_settlement_service import (
    MISSING_GENERATION_FENCE_CONTRACT,
    SettlementOutcome,
    UsageSettlementService,
    sweep_stale_reservations,
)
from recognition.domain.job import JobStatus
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
from scene.domain.describe_run import DescribeRunPhase, DescribeRunStatus, RunKind


async def _ledger_sessionmaker():
    path = os.path.join(tempfile.gettempdir(), f"app1_usage_sweep_{uuid.uuid4().hex}.db")
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
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                    IdentityScanJob.__table__,
                    IdentityScanJobItem.__table__,
                ],
            ),
        )
    return engine, async_sessionmaker(engine, expire_on_commit=False), path


async def _seed_tenant(session, *, allowance: int = 20):
    tenant = Tenant(id=uuid.uuid4(), site_url=f"https://{uuid.uuid4().hex}.example.test")
    session.add(tenant)
    await session.flush()
    now = datetime.now(tz=UTC)
    period_start = now - timedelta(minutes=1)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="sweep-v1",
            allowance_jobs=allowance,
            period_start=period_start,
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


@pytest.mark.asyncio
async def test_sweeper_does_not_release_active_describe_or_scan_work() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            service = UsageAdmissionService(session)
            running_job = uuid.uuid4()
            pending_scan = uuid.uuid4()
            running_ticket = await service.reserve(
                tenant.id,
                idempotency_key="op-running",
                job_id=str(running_job),
                cost_units=1,
                operation_id="op-running",
                request_fingerprint="fp-running",
            )
            scan_ticket = await service.reserve(
                tenant.id,
                idempotency_key="op-scan",
                job_id=str(pending_scan),
                cost_units=1,
                operation_id="op-scan",
                request_fingerprint="fp-scan",
            )
            session.add(
                DescribeRun(
                    id=running_job,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.RUNNING,
                    phase=DescribeRunPhase.DESCRIBING,
                    media_ids=[1],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                )
            )
            session.add(
                IdentityScanJob(
                    id=pending_scan,
                    tenant_id=tenant.id,
                    status=JobStatus.PENDING,
                    media_ids=[1],
                    total_media=1,
                )
            )
            await session.flush()
            _age_reservation(await session.get(UsageReservation, running_ticket.reservation_id), seconds=3600)
            _age_reservation(await session.get(UsageReservation, scan_ticket.reservation_id), seconds=3600)
            report = await sweep_stale_reservations(session, stale_after_seconds=60, max_batches=3, batch_size=10)
            await session.commit()

        async with sf() as session:
            running_row = await session.get(UsageReservation, running_ticket.reservation_id)
            scan_row = await session.get(UsageReservation, scan_ticket.reservation_id)
            assert running_row is not None and running_row.status == UsageReservationStatus.RESERVED
            assert scan_row is not None and scan_row.status == UsageReservationStatus.RESERVED
            assert report.skipped_active >= 2
            assert report.released == 0
            assert report.exit_code == 0
            assert MISSING_GENERATION_FENCE_CONTRACT in report.notes
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_sweeper_releases_stale_reservation_when_job_never_persisted() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-missing",
                job_id=str(uuid.uuid4()),
                cost_units=1,
                operation_id="op-missing",
                request_fingerprint="fp-missing",
            )
            _age_reservation(await session.get(UsageReservation, ticket.reservation_id), seconds=120)
            report = await sweep_stale_reservations(session, stale_after_seconds=30, max_batches=2, batch_size=5)
            await session.commit()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED
            assert report.released == 1
            assert report.exit_code == 0
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_cancel_before_pickup_releases_and_stale_fence_is_rejected() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-cancel",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-cancel",
                request_fingerprint="fp-cancel",
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.CANCELLED,
                    phase=DescribeRunPhase.CANCELLED,
                    media_ids=[1],
                    total_items=1,
                )
            )
            await session.flush()
            settlement = UsageSettlementService(session)
            released = await settlement.settle_job(
                tenant_id=tenant.id, job_id=str(job_id), fence_token=ticket.fence_token
            )
            assert released.outcome is SettlementOutcome.RELEASED
            stale = await settlement.settle_ticket(ticket, action=SettlementOutcome.COMMITTED, fence_token="old-fence")
            assert stale.outcome is SettlementOutcome.REJECTED
            wrong_tenant = await settlement.settle_job(
                tenant_id=uuid.uuid4(),
                job_id=str(job_id),
                fence_token=ticket.fence_token,
            )
            assert wrong_tenant.outcome is SettlementOutcome.MISSING
            await session.commit()
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED
    finally:
        await engine.dispose()
        os.unlink(path)


@pytest.mark.asyncio
async def test_after_pickup_failure_is_conservatively_charged() -> None:
    engine, sf, path = await _ledger_sessionmaker()
    try:
        async with sf() as session:
            tenant = await _seed_tenant(session)
            job_id = uuid.uuid4()
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="op-fail",
                job_id=str(job_id),
                cost_units=1,
                operation_id="op-fail",
                request_fingerprint="fp-fail",
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant.id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.FAILED,
                    phase=DescribeRunPhase.FAILED,
                    media_ids=[1],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                    queue_ms=12.0,
                )
            )
            await session.flush()
            captured = ticket.fence_token
            result = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            again = await UsageSettlementService(session).settle_job(
                tenant_id=tenant.id,
                job_id=str(job_id),
                fence_token=captured,
            )
            await session.commit()
            assert result.outcome is SettlementOutcome.COMMITTED
            assert again.outcome is SettlementOutcome.ALREADY_SETTLED
        async with sf() as session:
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.COMMITTED
    finally:
        await engine.dispose()
        os.unlink(path)
