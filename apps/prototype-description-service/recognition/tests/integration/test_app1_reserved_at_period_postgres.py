"""PostgreSQL proof that reservation time identifies the period charged."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
from db.models.tenant import Tenant
from db.tenant_context import set_tenant_context
from recognition.application.services.usage_admission_service import UsageAdmissionService
from recognition.application.services.usage_settlement_service import UsageSettlementService
from recognition.domain.portal_contracts import (
    EntitlementStatus,
    GLOBAL_USAGE_ADMISSION_STATE_ID,
    UsageReservationStatus,
)
import recognition.infrastructure.repositories.usage_repository as usage_repository

pytestmark = pytest.mark.pg

ADMISSION_AT = datetime(2031, 3, 2, 0, 0, 0, 250000, tzinfo=UTC)
PRIOR_DAY = datetime(2031, 3, 1, tzinfo=UTC)
ROLLED_PERIOD_START = datetime(2031, 3, 2, tzinfo=UTC)


class _MutableDateTime(datetime):
    current = ADMISSION_AT

    @classmethod
    def now(cls, tz=None):
        return cls.current if tz is not None else cls.current.replace(tzinfo=None)


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


@pytest.mark.asyncio
async def test_postgres_reserved_at_tracks_rolled_period_for_release_and_sweep(
    pg_migrated_engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(usage_repository, "datetime", _MutableDateTime)
    engine = create_async_engine(_async_url(pg_migrated_engine), pool_size=4, max_overflow=2, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant = Tenant(site_url=f"https://reserved-at-{uuid4()}.example.test")
            session.add(tenant)
            await session.flush()
            await set_tenant_context(session, tenant.id)
            session.add(
                TenantEntitlement(
                    tenant_id=tenant.id,
                    plan_code="beta",
                    allowance_version="app1-reserved-at-period",
                    allowance_jobs=20,
                    period_start=ADMISSION_AT - timedelta(days=1),
                    period_end=ADMISSION_AT + timedelta(days=30),
                    status=EntitlementStatus.BETA_ACTIVE,
                    source="pg-test",
                )
            )

            global_state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            assert global_state is not None
            global_state.period_start = PRIOR_DAY
            global_state.period_end = ROLLED_PERIOD_START
            global_state.daily_cost_units = 0
            global_state.inflight_units = 0
            global_state.queue_depth = 0
            global_state.queue_bytes = 0
            await session.flush()

            database_transaction_now = await session.scalar(text("SELECT now()"))
            assert database_transaction_now != ADMISSION_AT

            admission = UsageAdmissionService(session)
            released_ticket = await admission.reserve(
                tenant.id,
                idempotency_key="reserved-at-release",
                job_id="reserved-at-release-job",
                cost_units=2,
                operation_id="reserved-at-release",
                request_fingerprint="release-fingerprint",
            )
            persisted_release_time = await session.scalar(
                select(UsageReservation.reserved_at).where(UsageReservation.id == released_ticket.reservation_id)
            )
            assert persisted_release_time == ADMISSION_AT
            assert global_state.period_start == ROLLED_PERIOD_START
            assert global_state.period_end == ROLLED_PERIOD_START + timedelta(days=1)
            assert global_state.daily_cost_units == 2

            await admission.release(released_ticket)
            assert global_state.daily_cost_units == 0

            swept_ticket = await admission.reserve(
                tenant.id,
                idempotency_key="reserved-at-sweeper",
                job_id="reserved-at-sweeper-job",
                cost_units=3,
                operation_id="reserved-at-sweeper",
                request_fingerprint="sweeper-fingerprint",
            )
            persisted_sweeper_time = await session.scalar(
                select(UsageReservation.reserved_at).where(UsageReservation.id == swept_ticket.reservation_id)
            )
            assert persisted_sweeper_time == ADMISSION_AT
            assert global_state.daily_cost_units == 3

            _MutableDateTime.current = ADMISSION_AT + timedelta(minutes=31)
            report = await UsageSettlementService(session).sweep_stale_reservations(
                stale_after_seconds=30 * 60,
                max_batches=1,
                batch_size=10,
            )
            assert report.stale_seen == 1
            assert report.released == 1
            assert report.exit_code == 0
            assert global_state.daily_cost_units == 0

            swept_reservation = await session.get(UsageReservation, swept_ticket.reservation_id)
            assert swept_reservation is not None
            assert swept_reservation.status == UsageReservationStatus.RELEASED
            assert persisted_sweeper_time == swept_reservation.reserved_at
    finally:
        await engine.dispose()
