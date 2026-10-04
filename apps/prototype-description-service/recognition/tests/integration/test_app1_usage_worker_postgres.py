"""PostgreSQL G3 worker lifecycle: binding, exact-once settle, sweeper fail-closed.

Skip is missing release evidence, not a passing result. pg_empty_engine refuses
privileged roles; IDENTITY_PG_REQUIRED=1 fails instead of skip.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import IdentityScanJob, UsageReservation
from db.models.portal_billing import TenantEntitlement
from db.models.scene import DescribeRun
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.usage_admission_service import (
    UsageAdmissionService,
    UsageFenceMismatchError,
)
from recognition.application.services.usage_settlement_service import (
    SettlementOutcome,
    UsageSettlementService,
    sweep_stale_reservations,
)
from recognition.domain.job import JobStatus
from recognition.domain.portal_contracts import (
    EntitlementStatus,
    UsageReservationStatus,
)
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeRunPhase, DescribeRunStatus, RunKind

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


async def _prepare_tenant(session: AsyncSession, *, site_url: str, allowance_jobs: int) -> Tenant:
    tenant = Tenant(site_url=site_url)
    session.add(tenant)
    await session.flush()
    await set_tenant_context(session, tenant.id)
    now = datetime.now(tz=UTC)
    session.add(
        TenantEntitlement(
            tenant_id=tenant.id,
            plan_code="beta",
            allowance_version="pg-g3",
            allowance_jobs=allowance_jobs,
            period_start=now - timedelta(minutes=1),
            period_end=now + timedelta(hours=1),
            status=EntitlementStatus.BETA_ACTIVE,
            source="pg-test",
        )
    )
    await session.flush()
    return tenant


@pytest.mark.asyncio
async def test_postgres_worker_usage_lifecycle(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_reservation'"
            )
        ).one()
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
    assert flags == (True, True)
    assert role[1] is False and role[2] is False

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _prepare_tenant(session, site_url="https://g3-a.example.test", allowance_jobs=20)
            await session.commit()
            tenant_id = tenant.id

        job_id = uuid4()
        operation_id = "pg-op-pending"
        fingerprint = "a" * 64
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            first = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key=operation_id,
                job_id=str(job_id),
                cost_units=1,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
            )
            run_id = await DescribeRunRepository(session).create_run(
                tenant_id=tenant_id,
                media_ids=[1],
                run_id=job_id,
                operation_id=operation_id,
                request_digest=fingerprint,
            )
            await session.commit()
            reservation_id = first.reservation_id
            captured_fence = first.fence_token
        assert run_id == job_id
        assert first.job_id == str(job_id)

        # Fresh session / restart: 202 stays RESERVED and replays the persisted job.
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            replayed = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key=operation_id,
                job_id=str(uuid4()),
                cost_units=1,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
            )
            run = await session.get(DescribeRun, job_id)
            row = await session.get(UsageReservation, reservation_id)
            assert replayed.reservation_id == reservation_id
            assert replayed.job_id == str(job_id)
            assert replayed.fence_token == captured_fence
            assert run is not None and run.id == job_id
            assert row is not None and row.status == UsageReservationStatus.RESERVED

        # Cancel before pickup releases.
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            cancelled = await DescribeRunRepository(session).request_cancel(tenant_id=tenant_id, run_id=job_id)
            assert cancelled is True
            result = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(job_id),
                fence_token=captured_fence,
            )
            await session.commit()
            assert result.outcome is SettlementOutcome.RELEASED
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = await session.get(UsageReservation, reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RELEASED

        # New operation: pickup then fail conservatively charges; exact-once.
        fail_id = uuid4()
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            fail_ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-op-fail",
                job_id=str(fail_id),
                cost_units=1,
                operation_id="pg-op-fail",
                request_fingerprint=fingerprint,
            )
            await DescribeRunRepository(session).create_run(
                tenant_id=tenant_id,
                media_ids=[2],
                run_id=fail_id,
                operation_id="pg-op-fail",
                request_digest=fingerprint,
            )
            await DescribeRunRepository(session).record_pickup(tenant_id=tenant_id, run_id=fail_id)
            await DescribeRunRepository(session).mark_run_failed(
                tenant_id=tenant_id, run_id=fail_id, error_message="adapter exploded"
            )
            with pytest.raises(UsageFenceMismatchError):
                await UsageAdmissionService(session).commit_fenced(fail_ticket, fence_token="stale-token")
            charged = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(fail_id),
                fence_token=fail_ticket.fence_token,
            )
            again = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(fail_id),
                fence_token=fail_ticket.fence_token,
            )
            await session.commit()
            assert charged.outcome is SettlementOutcome.COMMITTED
            assert again.outcome is SettlementOutcome.ALREADY_SETTLED
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            fail_row = await session.get(UsageReservation, fail_ticket.reservation_id)
            assert fail_row is not None and fail_row.status == UsageReservationStatus.COMMITTED

        # Wrong tenant cannot mutate the reservation.
        async with session_factory() as session:
            other = await _prepare_tenant(session, site_url="https://g3-b.example.test", allowance_jobs=5)
            rejected = await UsageSettlementService(session).settle_job(
                tenant_id=other.id,
                job_id=str(fail_id),
                fence_token=fail_ticket.fence_token,
            )
            await session.commit()
            assert rejected.outcome is SettlementOutcome.MISSING
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            fail_row = await session.get(UsageReservation, fail_ticket.reservation_id)
            assert fail_row is not None and fail_row.status == UsageReservationStatus.COMMITTED
            visible = (await session.execute(select(UsageReservation))).scalars().all()
            assert {row.tenant_id for row in visible} == {tenant_id}

        # Sweeper must not release an active running job even when the reservation is old.
        active_id = uuid4()
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            active_ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-op-active",
                job_id=str(active_id),
                cost_units=1,
                operation_id="pg-op-active",
                request_fingerprint=fingerprint,
            )
            session.add(
                DescribeRun(
                    id=active_id,
                    tenant_id=tenant_id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.RUNNING,
                    phase=DescribeRunPhase.DESCRIBING,
                    media_ids=[3],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                )
            )
            await session.flush()
            reservation = await session.get(UsageReservation, active_ticket.reservation_id)
            assert reservation is not None
            reservation.reserved_at = datetime.now(tz=UTC) - timedelta(hours=2)
            report = await sweep_stale_reservations(session, stale_after_seconds=60, max_batches=3, batch_size=20)
            await session.commit()
            assert report.released == 0
            assert report.skipped_active >= 1
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            active_row = await session.get(UsageReservation, active_ticket.reservation_id)
            assert active_row is not None and active_row.status == UsageReservationStatus.RESERVED

        # Scan job pending is also active work.
        scan_id = uuid4()
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            scan_ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-op-scan",
                job_id=str(scan_id),
                cost_units=1,
                operation_id="pg-op-scan",
                request_fingerprint=fingerprint,
            )
            session.add(
                IdentityScanJob(
                    id=scan_id,
                    tenant_id=tenant_id,
                    status=JobStatus.PENDING,
                    media_ids=[9],
                    total_media=1,
                )
            )
            await session.flush()
            reservation = await session.get(UsageReservation, scan_ticket.reservation_id)
            assert reservation is not None
            reservation.reserved_at = datetime.now(tz=UTC) - timedelta(hours=3)
            report = await sweep_stale_reservations(session, stale_after_seconds=30, max_batches=2, batch_size=20)
            await session.commit()
            assert report.released == 0
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            scan_row = await session.get(UsageReservation, scan_ticket.reservation_id)
            assert scan_row is not None and scan_row.status == UsageReservationStatus.RESERVED
    finally:
        await engine.dispose()
