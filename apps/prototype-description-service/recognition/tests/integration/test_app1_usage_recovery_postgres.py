"""PostgreSQL proof for G3 trusted usage recovery after fence epoch advance.

Skip is missing release evidence, not a passing result. pg_empty_engine refuses
privileged roles; IDENTITY_PG_REQUIRED=1 fails instead of skip.
"""

from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
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
    recover_usage_job,
)
from recognition.domain.portal_contracts import (
    DEFAULT_GLOBAL_FENCE_EPOCH,
    GLOBAL_USAGE_ADMISSION_STATE_ID,
    EntitlementStatus,
    UsageReservationStatus,
)
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
            allowance_version="pg-g3-recovery",
            allowance_jobs=allowance_jobs,
            period_start=now - timedelta(minutes=1),
            period_end=now + timedelta(hours=1),
            status=EntitlementStatus.BETA_ACTIVE,
            source="pg-test",
        )
    )
    await session.flush()
    return tenant


async def _advance_epoch(session: AsyncSession, *, delta: int = 1) -> int:
    await session.execute(
        update(GlobalUsageAdmissionState)
        .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
        .values(fence_epoch=GlobalUsageAdmissionState.fence_epoch + delta)
    )
    await session.flush()
    state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
    assert state is not None
    return int(state.fence_epoch)


@pytest.mark.asyncio
async def test_postgres_epoch_advance_old_callback_rejects_and_recovery_settles_once(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        role = conn.execute(
            text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_reservation'"
            )
        ).one()
    assert role[1] is False and role[2] is False
    assert flags == (True, True)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _prepare_tenant(session, site_url="https://g3-recover.example.test", allowance_jobs=20)
            await session.commit()
            tenant_id = tenant.id

        job_id = uuid4()
        operation_id = "pg-recover-cwe"
        fingerprint = "b" * 64
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key=operation_id,
                job_id=str(job_id),
                cost_units=1,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant_id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[4],
                    total_items=1,
                )
            )
            await session.commit()
            captured = ticket.fence_token
            reservation_id = ticket.reservation_id

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            active_id = uuid4()
            active_ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-recover-active",
                job_id=str(active_id),
                cost_units=1,
                operation_id="pg-recover-active",
                request_fingerprint="c" * 64,
            )
            session.add(
                DescribeRun(
                    id=active_id,
                    tenant_id=tenant_id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.RUNNING,
                    phase=DescribeRunPhase.DESCRIBING,
                    media_ids=[6],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                )
            )
            new_epoch = await _advance_epoch(session)
            await session.commit()
            active_captured = active_ticket.fence_token
            active_reservation_id = active_ticket.reservation_id

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            active_reject = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(active_id),
                fence_token=active_captured,
            )
            terminal_reject = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(job_id),
                fence_token=captured,
            )
            with pytest.raises(UsageFenceMismatchError):
                await UsageAdmissionService(session).commit_fenced(ticket, fence_token=captured)
            await session.rollback()
            await set_tenant_context(session, tenant_id)
            assert active_reject.outcome is SettlementOutcome.REJECTED
            assert terminal_reject.outcome is SettlementOutcome.REJECTED

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            before = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert before is not None
            inflight_before = int(before.inflight_units)
            daily_before = int(before.daily_cost_units)
            first = await recover_usage_job(session, tenant_id=tenant_id, job_id=str(job_id))
            second = await recover_usage_job(session, tenant_id=tenant_id, job_id=str(job_id))
            stale_after = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(job_id),
                fence_token=captured,
            )
            active_skip = await UsageSettlementService(session).recover_job(
                tenant_id=tenant_id,
                job_id=str(active_id),
            )
            await session.commit()
            assert first.outcome is SettlementOutcome.RELEASED
            assert second.outcome is SettlementOutcome.ALREADY_SETTLED
            assert stale_after.outcome is SettlementOutcome.REJECTED
            assert active_skip.outcome is SettlementOutcome.SKIPPED_ACTIVE
            after = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert after is not None
            assert int(after.inflight_units) == inflight_before - 1
            assert int(after.daily_cost_units) == daily_before - 1
            assert int(after.fence_epoch) == new_epoch

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            recovered = await session.get(UsageReservation, reservation_id)
            active_row = await session.get(UsageReservation, active_reservation_id)
            assert recovered is not None and recovered.status == UsageReservationStatus.RELEASED
            assert recovered.fence_token != captured
            assert int(recovered.fence_token.split(":", 1)[0]) == new_epoch
            assert active_row is not None and active_row.status == UsageReservationStatus.RESERVED
            assert active_row.fence_token == active_captured
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_recovery_mismatch_concurrency_and_period_fail_closed(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _prepare_tenant(session, site_url="https://g3-recover-id.example.test", allowance_jobs=20)
            other = await _prepare_tenant(session, site_url="https://g3-recover-other.example.test", allowance_jobs=5)
            await session.commit()
            tenant_id = tenant.id
            other_id = other.id

        job_id = uuid4()
        started_id = uuid4()
        fingerprint = "d" * 64
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-id-cwe",
                job_id=str(job_id),
                cost_units=1,
                operation_id="pg-id-cwe",
                request_fingerprint=fingerprint,
            )
            started_ticket = await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="pg-id-started",
                job_id=str(started_id),
                cost_units=1,
                operation_id="pg-id-started",
                request_fingerprint="e" * 64,
            )
            session.add(
                DescribeRun(
                    id=job_id,
                    tenant_id=tenant_id,
                    run_kind=RunKind.SINGLE,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[7],
                    total_items=1,
                )
            )
            session.add(
                DescribeRun(
                    id=started_id,
                    tenant_id=tenant_id,
                    run_kind=RunKind.BULK,
                    status=DescribeRunStatus.COMPLETED_WITH_ERRORS,
                    phase=DescribeRunPhase.COMPLETE,
                    media_ids=[8],
                    total_items=1,
                    started_at=datetime.now(tz=UTC),
                    queue_ms=11.0,
                )
            )
            await _advance_epoch(session)
            await session.commit()
            captured = ticket.fence_token

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            wrong_op = await UsageSettlementService(session).recover_job(
                tenant_id=tenant_id,
                job_id=str(job_id),
                operation_id="not-the-operation",
            )
            wrong_fp = await UsageSettlementService(session).recover_job(
                tenant_id=tenant_id,
                job_id=str(job_id),
                request_fingerprint="f" * 64,
            )
            wrong_tenant = await recover_usage_job(session, tenant_id=other_id, job_id=str(job_id))
            await session.commit()
            assert wrong_op.outcome is SettlementOutcome.REJECTED
            assert wrong_fp.outcome is SettlementOutcome.REJECTED
            assert wrong_tenant.outcome is SettlementOutcome.MISSING

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None and row.status == UsageReservationStatus.RESERVED
            assert row.fence_token == captured

        async def recover_started():
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                result = await recover_usage_job(session, tenant_id=tenant_id, job_id=str(started_id))
                await session.commit()
                return result.outcome

        outcomes = await asyncio.gather(recover_started(), recover_started())
        assert SettlementOutcome.COMMITTED in outcomes
        assert outcomes.count(SettlementOutcome.COMMITTED) == 1
        assert set(outcomes) <= {
            SettlementOutcome.COMMITTED,
            SettlementOutcome.ALREADY_SETTLED,
        }

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            started_row = await session.get(UsageReservation, started_ticket.reservation_id)
            global_state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert started_row is not None and started_row.status == UsageReservationStatus.COMMITTED
            assert global_state is not None
            stale = await UsageSettlementService(session).settle_job(
                tenant_id=tenant_id,
                job_id=str(started_id),
                fence_token=started_ticket.fence_token,
            )
            assert stale.outcome is SettlementOutcome.REJECTED

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            await session.execute(
                update(GlobalUsageAdmissionState)
                .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
                .values(period_end=datetime.now(tz=UTC) - timedelta(seconds=5))
            )
            await session.commit()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            before = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert before is not None
            inflight_before = int(before.inflight_units)
            daily_before = int(before.daily_cost_units)
            rolled = await recover_usage_job(session, tenant_id=tenant_id, job_id=str(job_id))
            held = await session.get(UsageReservation, ticket.reservation_id)
            after = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            await session.commit()
            assert rolled.outcome is SettlementOutcome.FAIL_CLOSED
            assert held is not None and held.status == UsageReservationStatus.RESERVED
            assert after is not None
            assert int(after.inflight_units) == inflight_before
            assert int(after.daily_cost_units) == daily_before
            assert int(after.fence_epoch) >= DEFAULT_GLOBAL_FENCE_EPOCH
    finally:
        await engine.dispose()
