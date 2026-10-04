"""PostgreSQL concurrency proof for G1 usage admission.

Skip is missing release evidence, not a passing result. The pg_empty_engine
fixture refuses privileged roles; IDENTITY_PG_REQUIRED=1 fails instead of skip.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    ReservationNotFoundError,
    UsageAdmissionService,
    UsageFenceMismatchError,
    UsageFingerprintConflictError,
)
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
            allowance_version="pg-v1",
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
async def test_postgres_concurrent_reservation_and_fingerprint_race(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_reservation'"
            )
        ).one()
        global_flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_admission_global_state'"
            )
        ).one()
        seeded = conn.execute(
            text("SELECT id, config_version FROM usage_admission_global_state WHERE id = :id"),
            {"id": GLOBAL_USAGE_ADMISSION_STATE_ID},
        ).one()

    assert flags == (True, True)
    assert global_flags[0] is False
    assert seeded == (GLOBAL_USAGE_ADMISSION_STATE_ID, DEFAULT_GLOBAL_CONFIG_VERSION)
    inspector = inspect(pg_empty_engine)
    columns = {column["name"] for column in inspector.get_columns("usage_reservation")}
    assert {"operation_id", "request_fingerprint", "fence_token", "job_id", "queue_bytes"} <= columns

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _prepare_tenant(session, site_url="https://usage-a.example.test", allowance_jobs=1)
            await session.commit()
            tenant_id = tenant.id

        async def attempt(index: int):
            async with session_factory() as session:
                await set_tenant_context(session, tenant_id)
                try:
                    ticket = await UsageAdmissionService(session).reserve(
                        tenant_id,
                        idempotency_key=f"concurrent-{index}",
                        job_id=f"job-{index}",
                        cost_units=1,
                        operation_id=f"concurrent-{index}",
                        request_fingerprint=f"fp-{index}",
                    )
                    await session.commit()
                    return ticket
                except AllowanceExceededError:
                    await session.rollback()
                    return None

        tickets = [ticket for ticket in await asyncio.gather(*(attempt(i) for i in range(6))) if ticket]
        assert len(tickets) == 1

        async with session_factory() as session:
            fp_tenant = await _prepare_tenant(session, site_url="https://usage-fp.example.test", allowance_jobs=1)
            first = await UsageAdmissionService(session).reserve(
                fp_tenant.id,
                idempotency_key="op-same",
                job_id="job-same",
                cost_units=1,
                operation_id="op-same",
                request_fingerprint="fp-a",
            )
            await session.commit()
            fp_tenant_id = fp_tenant.id

        async def conflicting():
            async with session_factory() as session:
                await set_tenant_context(session, fp_tenant_id)
                return await UsageAdmissionService(session).reserve(
                    fp_tenant_id,
                    idempotency_key="op-same",
                    job_id="job-b",
                    cost_units=1,
                    operation_id="op-same",
                    request_fingerprint="fp-b",
                )

        with pytest.raises(UsageFingerprintConflictError):
            await conflicting()

        async with session_factory() as session:
            await set_tenant_context(session, fp_tenant_id)
            replayed = await UsageAdmissionService(session).reserve(
                fp_tenant_id,
                idempotency_key="op-same",
                job_id="job-retry",
                cost_units=1,
                operation_id="op-same",
                request_fingerprint="fp-a",
            )
            assert replayed.reservation_id == first.reservation_id
            await session.commit()

        async with session_factory() as session:
            other = await _prepare_tenant(session, site_url="https://usage-b.example.test", allowance_jobs=1)
            isolated = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert isolated is not None
            assert isolated.daily_cost_limit == DEFAULT_GLOBAL_DAILY_COST_LIMIT
            assert isolated.inflight_limit == DEFAULT_GLOBAL_INFLIGHT_LIMIT
            assert isolated.queue_limit == DEFAULT_GLOBAL_QUEUE_LIMIT
            assert isolated.queue_byte_limit == DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT
            assert isolated.fence_epoch == DEFAULT_GLOBAL_FENCE_EPOCH
            other_ticket = await UsageAdmissionService(session).reserve(
                other.id,
                idempotency_key="op-same",
                job_id="job-other",
                cost_units=1,
                operation_id="op-same",
                request_fingerprint="fp-a",
            )
            assert other_ticket.reservation_id != first.reservation_id
            visible = (await session.execute(select(UsageReservation))).scalars().all()
            assert {row.tenant_id for row in visible} == {other.id}
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_stale_epoch_and_identity_cannot_settle(pg_empty_engine) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_size=8, max_overflow=4, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = await _prepare_tenant(session, site_url="https://usage-epoch.example.test", allowance_jobs=2)
            ticket = await UsageAdmissionService(session).reserve(
                tenant.id,
                idempotency_key="epoch-op",
                job_id="epoch-job",
                cost_units=1,
                operation_id="epoch-op",
                request_fingerprint="epoch-fp",
            )
            await session.commit()
            tenant_id = tenant.id

        epoch_text, token_uuid = ticket.fence_token.split(":", 1)
        assert int(epoch_text) == DEFAULT_GLOBAL_FENCE_EPOCH
        UUID(token_uuid)
        assert "legacy" not in ticket.fence_token

        async with session_factory() as session:
            await session.execute(
                update(GlobalUsageAdmissionState)
                .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
                .values(fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH + 1)
            )
            await session.commit()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            with pytest.raises(UsageFenceMismatchError):
                await UsageAdmissionService(session).commit_fenced(ticket, fence_token=ticket.fence_token)
            await session.rollback()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            crafted = f"{DEFAULT_GLOBAL_FENCE_EPOCH + 1}:{token_uuid}"
            with pytest.raises(UsageFenceMismatchError):
                await UsageAdmissionService(session).commit_fenced(ticket, fence_token=crafted)
            await session.rollback()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            row = await session.get(UsageReservation, ticket.reservation_id)
            assert row is not None
            assert row.status == UsageReservationStatus.RESERVED
            global_state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert global_state is not None
            assert global_state.inflight_units == 1
            assert global_state.daily_cost_units == 1
            assert global_state.queue_depth == 1

        async with session_factory() as session:
            await session.execute(
                update(GlobalUsageAdmissionState)
                .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
                .values(fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH)
            )
            await session.commit()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            with pytest.raises(ReservationNotFoundError):
                await UsageAdmissionService(session).commit(replace(ticket, operation_id="changed-op"))
            await session.rollback()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            await UsageAdmissionService(session).commit(ticket)
            await session.commit()

        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            settled = await session.get(UsageReservation, ticket.reservation_id)
            assert settled is not None
            assert settled.status == UsageReservationStatus.COMMITTED
    finally:
        await engine.dispose()
