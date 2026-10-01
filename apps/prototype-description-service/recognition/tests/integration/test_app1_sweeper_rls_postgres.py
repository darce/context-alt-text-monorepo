"""Postgres proof that the background sweeper crosses tenants under forced RLS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Tenant, UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.application.services.usage_settlement_service import (
    SettlementOutcome,
    UsageSettlementService,
)
from recognition.domain.portal_contracts import EntitlementStatus, UsageReservationStatus

pytestmark = pytest.mark.pg

QUEUE_BYTES_PER_RESERVATION = 7


@dataclass(frozen=True, slots=True)
class SeededReservation:
    tenant_id: UUID
    reservation_id: UUID
    job_id: str


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _assert_forced_rls_nonprivileged(engine) -> None:
    with engine.connect() as conn:
        role = conn.execute(
            text("SELECT r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user")
        ).one()
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'usage_reservation'"
            )
        ).one()
    assert role == (False, False), "the pg test role must be subject to row-level security"
    assert flags == (True, True), "usage_reservation must have enabled and forced row-level security"


async def _prepare_tenants(session_factory: async_sessionmaker[AsyncSession], count: int = 2) -> list[UUID]:
    tenant_ids: list[UUID] = []
    async with session_factory() as session:
        for _ in range(count):
            tenant = Tenant(site_url=f"https://sweeper-{uuid4().hex}.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            now = datetime.now(tz=UTC)
            session.add(
                TenantEntitlement(
                    tenant_id=tenant.id,
                    plan_code="beta",
                    allowance_version="app1-sweeper-postgres",
                    allowance_jobs=100,
                    period_start=now - timedelta(minutes=1),
                    period_end=now + timedelta(hours=1),
                    status=EntitlementStatus.BETA_ACTIVE,
                    source="pg-test",
                )
            )
            await session.flush()
            tenant_ids.append(tenant.id)
        await session.commit()
    return tenant_ids


async def _seed_stale_reservations(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_ids: list[UUID],
    counts: list[int],
    *,
    label: str,
) -> list[SeededReservation]:
    assert len(tenant_ids) == len(counts)
    seeded: list[SeededReservation] = []
    reserved_at = datetime.now(tz=UTC) - timedelta(minutes=10)
    ordinal = 0
    for tenant_id, count in zip(tenant_ids, counts, strict=True):
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            admission = UsageAdmissionService(session)
            for item in range(count):
                operation_id = f"{label}-{tenant_id.hex}-{item}-{uuid4().hex}"
                job_id = str(uuid4())
                ticket = await admission.reserve(
                    tenant_id,
                    idempotency_key=operation_id,
                    job_id=job_id,
                    cost_units=1,
                    operation_id=operation_id,
                    request_fingerprint=uuid4().hex,
                    queue_bytes=QUEUE_BYTES_PER_RESERVATION,
                )
                reservation = await session.get(UsageReservation, ticket.reservation_id)
                assert reservation is not None
                reservation.reserved_at = reserved_at + timedelta(seconds=ordinal)
                await session.flush()
                seeded.append(SeededReservation(tenant_id, ticket.reservation_id, job_id))
                ordinal += 1
            await session.commit()
    return seeded


async def _read_global_counters(session_factory: async_sessionmaker[AsyncSession]) -> tuple[int, int, int, int]:
    async with session_factory() as session:
        await enable_rls_bypass(session)
        row = (
            await session.execute(
                select(
                    GlobalUsageAdmissionState.daily_cost_units,
                    GlobalUsageAdmissionState.inflight_units,
                    GlobalUsageAdmissionState.queue_depth,
                    GlobalUsageAdmissionState.queue_bytes,
                )
            )
        ).one()
        return tuple(int(value) for value in row)


async def _session_settings(session: AsyncSession) -> tuple[str | None, str | None]:
    row = (
        await session.execute(
            text(
                "SELECT current_setting('app.current_tenant', true), "
                "current_setting('app.bypass_rls', true)"
            )
        )
    ).one()
    return row[0], row[1]


def _assert_unset(value: str | None, *, name: str) -> None:
    assert value in (None, "", "false"), f"{name} leaked on the session: {value!r}"


async def _release_seeded_reservations(
    session_factory: async_sessionmaker[AsyncSession],
    seeded: list[SeededReservation],
) -> None:
    tenant_ids = dict.fromkeys(row.tenant_id for row in seeded)
    for tenant_id in tenant_ids:
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            for row in seeded:
                if row.tenant_id != tenant_id:
                    continue
                result = await UsageSettlementService(session).recover_job(
                    tenant_id=row.tenant_id,
                    job_id=row.job_id,
                    allow_missing_job_release=True,
                )
                assert result.outcome is SettlementOutcome.RELEASED, result
            await session.commit()


def _counter_delta(
    before: tuple[int, int, int, int],
    *,
    reservations: int,
    queue_bytes: int,
) -> tuple[int, int, int, int]:
    return (
        before[0] + reservations,
        before[1] + reservations,
        before[2] + reservations,
        before[3] + queue_bytes,
    )


async def _assert_tenant_rows(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_ids: list[UUID],
    seeded: list[SeededReservation],
    *,
    expected_status: UsageReservationStatus,
) -> None:
    all_ids = {row.reservation_id for row in seeded}
    for tenant_id in tenant_ids:
        expected_ids = {row.reservation_id for row in seeded if row.tenant_id == tenant_id}
        foreign_ids = all_ids - expected_ids
        async with session_factory() as session:
            await set_tenant_context(session, tenant_id)
            visible = list((await session.execute(select(UsageReservation))).scalars().all())
            assert {row.id for row in visible} == expected_ids, "tenant context exposed another tenant's rows"
            assert all(row.tenant_id == tenant_id for row in visible)
            assert all(row.status == expected_status for row in visible)
            foreign = list(
                (
                    await session.execute(
                        select(UsageReservation.id).where(UsageReservation.id.in_(foreign_ids))
                    )
                )
                .scalars()
                .all()
            )
            assert foreign == [], "tenant context returned a reservation owned by another tenant"


@pytest.mark.asyncio
async def test_background_sweep_recovers_across_tenants_and_commits_under_forced_rls(
    pg_isolated_migrated_engine,
) -> None:
    _assert_forced_rls_nonprivileged(pg_isolated_migrated_engine)
    engine = create_async_engine(_async_url(pg_isolated_migrated_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        counters_before = await _read_global_counters(session_factory)
        tenant_ids = await _prepare_tenants(session_factory)
        seeded = await _seed_stale_reservations(session_factory, tenant_ids, [3, 2], label="complete-sweep")
        count = len(seeded)
        assert count == 5
        assert await _read_global_counters(session_factory) == _counter_delta(
            counters_before,
            reservations=count,
            queue_bytes=count * QUEUE_BYTES_PER_RESERVATION,
        )

        async with session_factory() as session:
            tenant_setting, bypass_setting = await _session_settings(session)
            _assert_unset(tenant_setting, name="app.current_tenant before background sweep")
            _assert_unset(bypass_setting, name="app.bypass_rls before background sweep")
            report = await UsageSettlementService(session).sweep_stale_reservations(
                stale_after_seconds=60,
                max_batches=5,
                batch_size=2,
            )
            tenant_setting, bypass_setting = await _session_settings(session)
            _assert_unset(tenant_setting, name="app.current_tenant after background sweep")
            _assert_unset(bypass_setting, name="app.bypass_rls after background sweep")
            assert report.stale_seen == count
            assert report.released == count
            assert report.committed == report.missing == report.fail_closed == 0
            assert report.batches >= 3, "the proof must span more than one reservation batch"
            assert report.exit_code == 0
            await session.commit()
            tenant_setting, bypass_setting = await _session_settings(session)
            _assert_unset(tenant_setting, name="app.current_tenant after caller commit")
            _assert_unset(bypass_setting, name="app.bypass_rls after caller commit")

        await _assert_tenant_rows(
            session_factory,
            tenant_ids,
            seeded,
            expected_status=UsageReservationStatus.RELEASED,
        )
        assert await _read_global_counters(session_factory) == counters_before
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sweep_failure_resets_bypass_and_caller_rollback_discards_prior_settlements(
    pg_isolated_migrated_engine,
    monkeypatch,
) -> None:
    _assert_forced_rls_nonprivileged(pg_isolated_migrated_engine)
    engine = create_async_engine(_async_url(pg_isolated_migrated_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        counters_before = await _read_global_counters(session_factory)
        tenant_ids = await _prepare_tenants(session_factory)
        seeded = await _seed_stale_reservations(session_factory, tenant_ids, [3, 1], label="failing-sweep")
        count = len(seeded)
        counters_reserved = _counter_delta(
            counters_before,
            reservations=count,
            queue_bytes=count * QUEUE_BYTES_PER_RESERVATION,
        )
        assert await _read_global_counters(session_factory) == counters_reserved
        first, failing = seeded[:2]
        successfully_settled: list[tuple[str, SettlementOutcome]] = []

        async with session_factory() as session:
            tenant_setting, bypass_setting = await _session_settings(session)
            _assert_unset(tenant_setting, name="app.current_tenant before failing background sweep")
            _assert_unset(bypass_setting, name="app.bypass_rls before failing background sweep")
            service = UsageSettlementService(session)
            original_recover = service.recover_job

            async def fail_on_selected_reservation(**kwargs):
                if kwargs["job_id"] == failing.job_id:
                    raise RuntimeError("injected settlement failure")
                result = await original_recover(**kwargs)
                successfully_settled.append((kwargs["job_id"], result.outcome))
                return result

            monkeypatch.setattr(service, "recover_job", fail_on_selected_reservation)
            with pytest.raises(RuntimeError, match="injected settlement failure"):
                await service.sweep_stale_reservations(
                    stale_after_seconds=60,
                    max_batches=5,
                    batch_size=4,
                )
            assert successfully_settled == [(first.job_id, SettlementOutcome.RELEASED)]
            tenant_setting, bypass_setting = await _session_settings(session)
            _assert_unset(tenant_setting, name="app.current_tenant after failed background sweep")
            _assert_unset(bypass_setting, name="app.bypass_rls after failed background sweep")
            # The worker owns the transaction and rolls it back after a failed sweep.
            await session.rollback()

        await _assert_tenant_rows(
            session_factory,
            tenant_ids,
            seeded,
            expected_status=UsageReservationStatus.RESERVED,
        )
        assert await _read_global_counters(session_factory) == counters_reserved
        await _release_seeded_reservations(session_factory, seeded)
        await _assert_tenant_rows(
            session_factory,
            tenant_ids,
            seeded,
            expected_status=UsageReservationStatus.RELEASED,
        )
        assert await _read_global_counters(session_factory) == counters_before
    finally:
        await engine.dispose()
