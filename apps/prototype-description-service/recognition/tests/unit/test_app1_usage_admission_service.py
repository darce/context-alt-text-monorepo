"""Unit coverage for atomic, idempotent usage admission."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from db.base import Base
from db.models import Tenant, TenantEntitlement, UsageReservation
from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    InvalidUsageRequestError,
    ReservationNotFoundError,
    UsageAdmissionService,
)
from recognition.domain.portal_contracts import EntitlementStatus, UsageReservationStatus, UsageTicket
from recognition.domain.portal_contracts import UsageAdmissionService as UsageAdmissionServiceProtocol
from recognition.infrastructure.repositories.usage_repository import SqlAlchemyUsageRepository


class _AsyncSessionAdapter:
    """Async-shaped adapter around SQLite's synchronous test session.

    The repository still exercises awaited ``execute``/``flush`` calls, while
    this suite avoids relying on the sandbox's unavailable aiosqlite worker.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, value: object) -> None:
        self._session.add(value)

    async def execute(self, statement):
        return self._session.execute(statement)

    async def flush(self) -> None:
        self._session.flush()

    async def commit(self) -> None:
        self._session.commit()

    async def rollback(self) -> None:
        self._session.rollback()

    async def close(self) -> None:
        self._session.close()

    async def __aenter__(self) -> _AsyncSessionAdapter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()


@pytest.fixture
def database() -> Iterator[tuple[Callable[[], _AsyncSessionAdapter], UUID, datetime]]:
    """Create only the tenant and usage tables needed by this unit suite."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Tenant.__table__, TenantEntitlement.__table__, UsageReservation.__table__],
    )

    tenant_id = uuid4()
    period_start = datetime.now(tz=UTC) - timedelta(minutes=1)
    with Session(engine) as setup_session:
        session = _AsyncSessionAdapter(setup_session)
        session.add(Tenant(id=tenant_id, site_url=f"https://{tenant_id}.example.test"))
        session.add(
            TenantEntitlement(
                tenant_id=tenant_id,
                plan_code="beta",
                allowance_version="test-v1",
                allowance_jobs=1,
                period_start=period_start,
                period_end=period_start + timedelta(hours=1),
                status=EntitlementStatus.BETA_ACTIVE,
                source="unit-test",
            )
        )
        setup_session.commit()

    def session_factory() -> _AsyncSessionAdapter:
        return _AsyncSessionAdapter(Session(engine))

    try:
        yield session_factory, tenant_id, period_start
    finally:
        engine.dispose()


async def _reservation(session: _AsyncSessionAdapter, reservation_id: UUID) -> UsageReservation:
    result = await session.execute(select(UsageReservation).where(UsageReservation.id == reservation_id).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        raise AssertionError("reservation was not persisted")
    return row


def test_service_satisfies_published_runtime_protocol() -> None:
    assert isinstance(UsageAdmissionService.__new__(UsageAdmissionService), UsageAdmissionServiceProtocol)


def test_reservation_path_locks_entitlement_before_check_and_insert() -> None:
    source = inspect.getsource(SqlAlchemyUsageRepository.reserve)
    assert "with_for_update" in source
    assert "UsageReservationStatus.RESERVED" in source
    assert "_CHARGEABLE_RESERVATION_STATUSES" in source


@pytest.mark.asyncio
async def test_reserve_returns_same_ticket_for_retry(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)

        first = await service.reserve(
            tenant_id,
            idempotency_key="request-1",
            job_id="job-1",
            cost_units=1,
        )
        second = await service.reserve(
            tenant_id,
            idempotency_key="request-1",
            job_id="different-job",
            cost_units=99,
        )

        assert first == second
        assert isinstance(first, UsageTicket)
        await session.commit()

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(UsageReservation).where(UsageReservation.tenant_id == tenant_id).limit(2)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].id == first.reservation_id


@pytest.mark.asyncio
async def test_reserve_rejects_when_remaining_allowance_is_zero(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        await service.reserve(tenant_id, idempotency_key="request-1", job_id=None, cost_units=1)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AllowanceExceededError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="request-2",
                job_id=None,
                cost_units=1,
            )


@pytest.mark.asyncio
async def test_missing_or_closed_entitlement_denies_by_default(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(
            update(TenantEntitlement)
            .where(TenantEntitlement.tenant_id == tenant_id)
            .values(status=EntitlementStatus.EXPIRED)
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AllowanceExceededError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="closed-entitlement",
                job_id=None,
                cost_units=1,
            )


@pytest.mark.asyncio
async def test_commit_is_idempotent_and_release_cannot_refund_committed_ticket(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(tenant_id, idempotency_key="request-1", job_id="job-1", cost_units=1)
        await service.commit(ticket)
        await service.commit(ticket)
        await service.release(ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.COMMITTED
        assert row.cost_units == ticket.cost_units


@pytest.mark.asyncio
async def test_release_is_idempotent_and_commit_cannot_revive_released_ticket(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(tenant_id, idempotency_key="request-1", job_id="job-1", cost_units=1)
        await service.release(ticket)
        await service.release(ticket)
        await service.commit(ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.RELEASED
        assert row.cost_units == ticket.cost_units


@pytest.mark.asyncio
async def test_terminal_operations_fail_safe_for_unknown_ticket(database) -> None:
    session_factory, tenant_id, _period_start = database
    unknown = UsageTicket(uuid4(), tenant_id, "missing", 1)
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(ReservationNotFoundError):
            await service.commit(unknown)
        with pytest.raises(ReservationNotFoundError):
            await service.release(unknown)


@pytest.mark.asyncio
async def test_reserve_validates_cost_and_idempotency_key(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(InvalidUsageRequestError):
            await service.reserve(tenant_id, idempotency_key=" ", job_id=None, cost_units=1)
        with pytest.raises(InvalidUsageRequestError):
            await service.reserve(tenant_id, idempotency_key="request-1", job_id=None, cost_units=0)


@pytest.mark.asyncio
async def test_concurrent_reservers_admit_at_most_remaining_allowance(database) -> None:
    session_factory, tenant_id, _period_start = database

    async def attempt(index: int) -> UsageTicket | None:
        async with session_factory() as session:
            try:
                ticket = await UsageAdmissionService(session).reserve(
                    tenant_id,
                    idempotency_key=f"concurrent-{index}",
                    job_id=f"job-{index}",
                    cost_units=1,
                )
                await session.commit()
                return ticket
            except AllowanceExceededError:
                await session.rollback()
                return None

    tickets = [ticket for ticket in await asyncio.gather(*(attempt(i) for i in range(8))) if ticket]
    assert len(tickets) == 1
