"""Unit coverage for atomic, idempotent usage admission."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from db.base import Base
from db.models import Tenant, TenantEntitlement, UsageReservation
from db.models.portal_billing import GlobalUsageAdmissionState
from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    GlobalUsageLimitExceededError,
    InvalidUsageRequestError,
    ReservationNotFoundError,
    UsageAdmissionService,
    UsageAdmissionStoppedError,
    UsageAdmissionUnavailableError,
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
    UsageTicket,
)
from recognition.domain.portal_contracts import UsageAdmissionService as UsageAdmissionServiceProtocol
from recognition.infrastructure.repositories.tenant_entitlement_repository import (
    SqlAlchemyTenantEntitlementRepository,
)
from recognition.infrastructure.repositories.usage_repository import (
    ExpiredUsageReservationError,
    SqlAlchemyUsageRepository,
)


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

    @asynccontextmanager
    async def begin_nested(self):
        with self._session.begin_nested():
            yield self

    async def __aenter__(self) -> _AsyncSessionAdapter:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()


def _seed_global_state(session: Session, **overrides: object) -> None:
    now = datetime.now(tz=UTC)
    period_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    payload = {
        "id": GLOBAL_USAGE_ADMISSION_STATE_ID,
        "period_start": period_start,
        "period_end": period_start + timedelta(days=1),
        "daily_cost_limit": DEFAULT_GLOBAL_DAILY_COST_LIMIT,
        "daily_cost_units": 0,
        "inflight_limit": DEFAULT_GLOBAL_INFLIGHT_LIMIT,
        "inflight_units": 0,
        "queue_limit": DEFAULT_GLOBAL_QUEUE_LIMIT,
        "queue_depth": 0,
        "queue_byte_limit": DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
        "queue_bytes": 0,
        "stop_requested": False,
        "fence_epoch": DEFAULT_GLOBAL_FENCE_EPOCH,
        "config_version": DEFAULT_GLOBAL_CONFIG_VERSION,
        "updated_at": now,
    }
    payload.update(overrides)
    session.add(GlobalUsageAdmissionState(**payload))


@pytest.fixture
def database() -> Iterator[tuple[Callable[[], _AsyncSessionAdapter], UUID, datetime]]:
    """Create only the tenant and usage tables needed by this unit suite."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            TenantEntitlement.__table__,
            UsageReservation.__table__,
            GlobalUsageAdmissionState.__table__,
        ],
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
        _seed_global_state(setup_session)
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


async def _global_state(session: _AsyncSessionAdapter) -> GlobalUsageAdmissionState:
    result = await session.execute(
        select(GlobalUsageAdmissionState).where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AssertionError("global admission state was not persisted")
    return row


async def _sweep_abandoned_ticket(session: _AsyncSessionAdapter, ticket: UsageTicket) -> None:
    """Scan stale rows and use the sweeper's fenced release for known abandoned work."""
    repository = SqlAlchemyUsageRepository(session)
    rows = await repository.list_stale_reservations(30, limit=100)
    assert ticket.reservation_id in {row.id for row in rows}
    await UsageAdmissionService(session).release_fenced(ticket, fence_token=ticket.fence_token)
    await session.commit()


def test_service_satisfies_published_runtime_protocol() -> None:
    assert isinstance(UsageAdmissionService.__new__(UsageAdmissionService), UsageAdmissionServiceProtocol)


def test_g1_public_method_signatures_are_frozen() -> None:
    reserve = inspect.signature(UsageAdmissionService.reserve)
    assert list(reserve.parameters) == [
        "self",
        "tenant_id",
        "idempotency_key",
        "job_id",
        "cost_units",
        "operation_id",
        "request_fingerprint",
        "queue_bytes",
    ]
    commit_fenced = inspect.signature(UsageAdmissionService.commit_fenced)
    assert list(commit_fenced.parameters) == ["self", "ticket", "fence_token"]
    release_fenced = inspect.signature(UsageAdmissionService.release_fenced)
    assert list(release_fenced.parameters) == ["self", "ticket", "fence_token"]


def test_reservation_path_locks_global_then_entitlement_before_insert() -> None:
    source = inspect.getsource(SqlAlchemyUsageRepository.reserve)
    assert source.index("_lock_global_state") < source.index("lock tenant entitlement")
    assert "with_for_update" in source
    assert "UsageReservationStatus.RESERVED" in source
    assert "_CHARGEABLE_RESERVATION_STATUSES" in source


@pytest.mark.asyncio
async def test_reservation_path_locks_entitlement_before_check_and_insert() -> None:
    tenant_id = uuid4()
    period_start = datetime.now(tz=UTC)
    entitlement = SimpleNamespace(period_start=period_start, allowance_jobs=1)
    global_state = SimpleNamespace(
        period_start=period_start,
        period_end=period_start + timedelta(days=1),
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
        updated_at=period_start,
    )

    class _Result:
        def __init__(self, *, row=None, scalar=None, rowcount=None) -> None:
            self._row = row
            self._scalar = scalar
            self.rowcount = rowcount

        def scalar_one_or_none(self):
            return self._row

        def scalar_one(self):
            return self._scalar

    class _RecordingSession:
        def __init__(self) -> None:
            self.actions: list[str] = []
            self.entitlement_statement = None
            self.global_statement = None

        async def execute(self, statement):
            if isinstance(statement, Update):
                self.actions.append("expire stale")
                return _Result(rowcount=0)
            if statement.selected_columns[0].name == "coalesce":
                self.actions.append("usage check")
                return _Result(scalar=0)
            entity = statement.column_descriptions[0].get("entity")
            if entity is UsageReservation:
                self.actions.append("reservation lookup")
                return _Result(row=None)
            if entity is GlobalUsageAdmissionState:
                self.actions.append("global lock")
                self.global_statement = statement
                return _Result(row=global_state)
            if entity is TenantEntitlement:
                self.actions.append("entitlement lock")
                self.entitlement_statement = statement
                return _Result(row=entitlement)
            raise AssertionError(f"unexpected repository query: {statement!r}")

        def add(self, _reservation) -> None:
            self.actions.append("insert")

        async def flush(self) -> None:
            self.actions.append("flush")

        @asynccontextmanager
        async def begin_nested(self):
            yield self

    session = _RecordingSession()
    await SqlAlchemyUsageRepository(session).reserve(
        tenant_id,
        idempotency_key="request-1",
        job_id="job-1",
        cost_units=1,
    )

    assert session.actions == [
        "reservation lookup",
        "global lock",
        "reservation lookup",
        "reservation lookup",
        "entitlement lock",
        "reservation lookup",
        "reservation lookup",
        "usage check",
        "insert",
        "flush",
    ]
    assert session.actions.index("global lock") < session.actions.index("entitlement lock")
    assert session.actions.index("entitlement lock") < session.actions.index("usage check")
    assert session.actions.index("usage check") < session.actions.index("insert")
    assert session.global_statement is not None
    assert session.entitlement_statement is not None
    assert "FOR UPDATE" in str(session.global_statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in str(session.entitlement_statement.compile(dialect=postgresql.dialect())), (
        "the executed entitlement query must compile with FOR UPDATE"
    )


@pytest.mark.asyncio
async def test_reserve_returns_same_ticket_for_retry(database) -> None:
    session_factory, tenant_id, _period_start = database
    entitlement_period_start = datetime.now(tz=UTC) - timedelta(days=3)
    async with session_factory() as session:
        await session.execute(
            update(TenantEntitlement)
            .where(TenantEntitlement.tenant_id == tenant_id)
            .values(
                period_start=entitlement_period_start,
                period_end=entitlement_period_start + timedelta(days=30),
            )
        )
        await session.commit()

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

        assert first.reservation_id == second.reservation_id
        assert first.operation_id == "request-1"
        assert first.request_fingerprint == "request-1"
        assert first.job_id == "job-1"
        assert first.fence_token
        assert isinstance(first, UsageTicket)
        await session.commit()

    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageReservation).where(UsageReservation.tenant_id == tenant_id).limit(2)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == first.reservation_id
        assert rows[0].period_start.replace(tzinfo=UTC) == entitlement_period_start


@pytest.mark.asyncio
async def test_same_operation_changed_fingerprint_conflicts(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        first = await service.reserve(
            tenant_id,
            idempotency_key="op-1",
            job_id="job-1",
            cost_units=1,
            operation_id="op-1",
            request_fingerprint="fp-a",
        )
        with pytest.raises(UsageFingerprintConflictError):
            await service.reserve(
                tenant_id,
                idempotency_key="op-1",
                job_id="job-2",
                cost_units=1,
                operation_id="op-1",
                request_fingerprint="fp-b",
            )
        await session.commit()

    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageReservation).where(UsageReservation.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].id == first.reservation_id
        assert rows[0].request_fingerprint == "fp-a"


@pytest.mark.asyncio
async def test_new_operation_is_independently_chargeable(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(
            update(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).values(allowance_jobs=2)
        )
        await session.commit()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        first = await service.reserve(
            tenant_id,
            idempotency_key="op-1",
            job_id="job-1",
            cost_units=1,
            operation_id="op-1",
            request_fingerprint="fp-same",
        )
        second = await service.reserve(
            tenant_id,
            idempotency_key="op-2",
            job_id="job-2",
            cost_units=1,
            operation_id="op-2",
            request_fingerprint="fp-same",
        )
        assert first.reservation_id != second.reservation_id
        await session.commit()

    async with session_factory() as session:
        rows = (
            (await session.execute(select(UsageReservation).where(UsageReservation.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_released_operation_cannot_authorize_fresh_work(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id,
            idempotency_key="op-1",
            job_id="job-1",
            cost_units=1,
            operation_id="op-1",
            request_fingerprint="fp-1",
        )
        await service.release_fenced(ticket, fence_token=ticket.fence_token)
        replayed = await service.reserve(
            tenant_id,
            idempotency_key="op-1",
            job_id="job-new",
            cost_units=1,
            operation_id="op-1",
            request_fingerprint="fp-1",
        )
        assert replayed.reservation_id == ticket.reservation_id
        assert replayed.job_id == "job-1"
        await service.commit_fenced(replayed, fence_token=replayed.fence_token)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.RELEASED


@pytest.mark.asyncio
async def test_stale_fence_cannot_settle_reservation(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(tenant_id, idempotency_key="op-1", job_id="job-1", cost_units=1)
        with pytest.raises(UsageFenceMismatchError):
            await service.commit_fenced(ticket, fence_token="stale-fence")
        await service.commit_fenced(ticket, fence_token=ticket.fence_token)
        await service.commit_fenced(ticket, fence_token=ticket.fence_token)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.COMMITTED


@pytest.mark.asyncio
async def test_missing_global_state_fails_closed(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(delete(GlobalUsageAdmissionState))
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(UsageAdmissionUnavailableError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="closed-global",
                job_id=None,
                cost_units=1,
            )


@pytest.mark.asyncio
async def test_stop_requested_refuses_new_reservation(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(
            update(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .values(stop_requested=True)
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(UsageAdmissionStoppedError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="stopped",
                job_id=None,
                cost_units=1,
            )


@pytest.mark.asyncio
async def test_global_daily_cost_limit_is_enforced(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(
            update(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).values(allowance_jobs=8)
        )
        await session.execute(
            update(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .values(daily_cost_limit=1)
        )
        await session.commit()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        await service.reserve(tenant_id, idempotency_key="first", job_id=None, cost_units=1)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(GlobalUsageLimitExceededError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="second",
                job_id=None,
                cost_units=1,
            )


@pytest.mark.parametrize(
    ("global_limits", "first_queue_bytes", "second_queue_bytes"),
    [
        pytest.param(
            {"daily_cost_limit": 10, "inflight_limit": 1, "queue_limit": 10, "queue_byte_limit": 10},
            0,
            0,
            id="inflight-units",
        ),
        pytest.param(
            {"daily_cost_limit": 10, "inflight_limit": 10, "queue_limit": 1, "queue_byte_limit": 10},
            0,
            0,
            id="queue-depth",
        ),
        pytest.param(
            {"daily_cost_limit": 10, "inflight_limit": 10, "queue_limit": 10, "queue_byte_limit": 4},
            4,
            1,
            id="queue-bytes",
        ),
    ],
)
@pytest.mark.asyncio
async def test_global_inflight_and_queue_capacity_limits_are_enforced(
    database,
    global_limits: dict[str, int],
    first_queue_bytes: int,
    second_queue_bytes: int,
) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        await session.execute(
            update(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id).values(allowance_jobs=8)
        )
        await session.execute(
            update(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .values(**global_limits)
        )
        await session.commit()

    async with session_factory() as session:
        await UsageAdmissionService(session).reserve(
            tenant_id,
            idempotency_key="first",
            job_id=None,
            cost_units=1,
            queue_bytes=first_queue_bytes,
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(GlobalUsageLimitExceededError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="second",
                job_id=None,
                cost_units=1,
                queue_bytes=second_queue_bytes,
            )


@pytest.mark.asyncio
async def test_reserve_rejects_when_remaining_allowance_is_zero(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id, idempotency_key="request-1", job_id=None, cost_units=1, queue_bytes=7
        )
        await session.execute(
            update(UsageReservation)
            .where(UsageReservation.id == ticket.reservation_id)
            .values(reserved_at=datetime.now(tz=UTC) - timedelta(days=1))
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AllowanceExceededError):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="request-2",
                job_id=None,
                cost_units=1,
            )
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.RESERVED
        assert row.cost_units == 1
        state = await _global_state(session)
        assert int(state.daily_cost_units) == 1
        assert int(state.inflight_units) == 1
        assert int(state.queue_depth) == 1
        assert int(state.queue_bytes) == 7


@pytest.mark.asyncio
async def test_expired_reservation_is_reclaimed_and_late_commit_is_ignored(database) -> None:
    session_factory, tenant_id, period_start = database
    stale_id = uuid4()
    fence_token = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}"
    stale_ticket = UsageTicket(
        stale_id,
        tenant_id,
        "stale-request",
        1,
        operation_id="stale-request",
        request_fingerprint="stale-request",
        job_id="stale-job",
        fence_token=fence_token,
    )
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=stale_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key=stale_ticket.idempotency_key,
                operation_id=stale_ticket.operation_id,
                request_fingerprint=stale_ticket.request_fingerprint,
                job_id="stale-job",
                fence_token=fence_token,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        await _sweep_abandoned_ticket(session, stale_ticket)

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(tenant_id, idempotency_key="new-request", job_id=None, cost_units=1)
        await service.commit(stale_ticket)
        await session.commit()
        assert ticket.tenant_id == tenant_id

    async with session_factory() as session:
        row = await _reservation(session, stale_id)
        assert row.status == UsageReservationStatus.EXPIRED
        assert row.settled_at is not None


@pytest.mark.asyncio
async def test_stale_reservation_commit_without_sweep_remains_chargeable(database) -> None:
    session_factory, tenant_id, period_start = database
    stale_id = uuid4()
    fence_token = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}"
    stale_ticket = UsageTicket(
        stale_id,
        tenant_id,
        "stale-direct-commit",
        1,
        operation_id="stale-direct-commit",
        request_fingerprint="stale-direct-commit",
        job_id="stale-job",
        fence_token=fence_token,
    )
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=stale_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key=stale_ticket.idempotency_key,
                operation_id=stale_ticket.operation_id,
                request_fingerprint=stale_ticket.request_fingerprint,
                job_id="stale-job",
                fence_token=fence_token,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        await UsageAdmissionService(session).commit(stale_ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, stale_id)
        assert row.status == UsageReservationStatus.COMMITTED
        assert row.settled_at is not None
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 1})
        assert await repository.used_jobs(tenant_id, period_start) == 1


@pytest.mark.asyncio
async def test_stale_reservation_release_without_sweep_expires_and_is_not_counted(database) -> None:
    session_factory, tenant_id, period_start = database
    stale_id = uuid4()
    fence_token = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}"
    stale_ticket = UsageTicket(
        stale_id,
        tenant_id,
        "stale-direct-release",
        1,
        operation_id="stale-direct-release",
        request_fingerprint="stale-direct-release",
        job_id="stale-job",
        fence_token=fence_token,
    )
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=stale_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key=stale_ticket.idempotency_key,
                operation_id=stale_ticket.operation_id,
                request_fingerprint=stale_ticket.request_fingerprint,
                job_id="stale-job",
                fence_token=fence_token,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        await UsageAdmissionService(session).release(stale_ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, stale_id)
        assert row.status == UsageReservationStatus.EXPIRED
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 1})
        assert await repository.used_jobs(tenant_id, period_start) == 0


@pytest.mark.asyncio
async def test_fresh_reservation_commit_remains_chargeable(database) -> None:
    session_factory, tenant_id, period_start = database
    async with session_factory() as session:
        ticket = await UsageAdmissionService(session).reserve(
            tenant_id,
            idempotency_key="fresh-direct-commit",
            job_id="fresh-job",
            cost_units=1,
        )
        await UsageAdmissionService(session).commit(ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.COMMITTED
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 1})
        assert await repository.used_jobs(tenant_id, period_start) == 1


@pytest.mark.asyncio
async def test_stale_same_key_retry_cannot_charge_expired_ticket(database) -> None:
    session_factory, tenant_id, period_start = database
    stale_id = uuid4()
    fence_token = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}"
    stale_ticket = UsageTicket(
        stale_id,
        tenant_id,
        "stale-retry",
        1,
        operation_id="stale-retry",
        request_fingerprint="stale-retry",
        job_id="stale-job",
        fence_token=fence_token,
    )
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=stale_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key=stale_ticket.idempotency_key,
                operation_id=stale_ticket.operation_id,
                request_fingerprint=stale_ticket.request_fingerprint,
                job_id="stale-job",
                fence_token=fence_token,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        retry = await UsageAdmissionService(session).reserve(
            tenant_id,
            idempotency_key=stale_ticket.idempotency_key,
            job_id="retry-job",
            cost_units=1,
        )
        assert retry.reservation_id == stale_id
        await _sweep_abandoned_ticket(session, stale_ticket)
        await UsageAdmissionService(session).commit(retry)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, stale_id)
        assert row.status == UsageReservationStatus.EXPIRED
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 1})
        assert await repository.used_jobs(tenant_id, period_start) == 0


@pytest.mark.asyncio
async def test_expired_same_key_retry_is_rejected_after_sweep(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        first_ticket = await UsageAdmissionService(session).reserve(
            tenant_id,
            idempotency_key="swept-retry",
            job_id="original-job",
            cost_units=1,
        )
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            update(UsageReservation)
            .where(UsageReservation.id == first_ticket.reservation_id)
            .values(reserved_at=datetime.now(tz=UTC) - timedelta(days=1))
        )
        await session.commit()

    async with session_factory() as session:
        await _sweep_abandoned_ticket(session, first_ticket)
        await UsageAdmissionService(session).reserve(
            tenant_id,
            idempotency_key="sweeping-request",
            job_id="replacement-job",
            cost_units=1,
        )
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, first_ticket.reservation_id)
        assert row.status == UsageReservationStatus.EXPIRED

    async with session_factory() as session:
        with pytest.raises(InvalidUsageRequestError, match="expired"):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key=first_ticket.idempotency_key,
                job_id="retry-job",
                cost_units=1,
            )


@pytest.mark.asyncio
async def test_expired_operation_id_retry_with_fresh_key_is_rejected(database) -> None:
    session_factory, tenant_id, period_start = database
    operation_id = "expired-operation"
    fingerprint = "expired-operation-fingerprint"
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=uuid4(),
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key="original-idempotency-key",
                operation_id=operation_id,
                request_fingerprint=fingerprint,
                job_id="original-job",
                fence_token=f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}",
                queue_bytes=0,
                status=UsageReservationStatus.EXPIRED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(ExpiredUsageReservationError, match="expired"):
            await UsageAdmissionService(session).reserve(
                tenant_id,
                idempotency_key="fresh-idempotency-key",
                job_id="replacement-job",
                cost_units=1,
                operation_id=operation_id,
                request_fingerprint=fingerprint,
            )


@pytest.mark.asyncio
async def test_used_jobs_keeps_stale_reserved_reservations_chargeable(database) -> None:
    session_factory, tenant_id, period_start = database
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=uuid4(),
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key="stale-read-request",
                operation_id="stale-read-request",
                request_fingerprint="stale-read-request",
                job_id="stale-read-job",
                fence_token=f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{uuid4()}",
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
                reserved_at=datetime.now(tz=UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = SqlAlchemyTenantEntitlementRepository(session, plan_allowances={"paid": 1})
        assert await repository.used_jobs(tenant_id, period_start) == 1


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
        global_state = await _global_state(session)
        assert global_state.inflight_units == 0
        assert global_state.daily_cost_units == 1


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
        global_state = await _global_state(session)
        assert global_state.inflight_units == 0
        assert global_state.daily_cost_units == 0


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


def _assert_modern_fence(token: str, *, epoch: int) -> UUID:
    prefix, separator, remainder = token.partition(":")
    assert separator == ":"
    assert prefix == str(epoch)
    assert "legacy" not in token
    return UUID(remainder)


@pytest.mark.asyncio
async def test_reserve_fence_token_carries_current_positive_epoch(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id,
            idempotency_key="epoch-token",
            job_id="job-epoch",
            cost_units=1,
            operation_id="epoch-token",
            request_fingerprint="fp-epoch",
        )
        token_uuid = _assert_modern_fence(ticket.fence_token, epoch=DEFAULT_GLOBAL_FENCE_EPOCH)
        assert ticket.fence_token == f"{DEFAULT_GLOBAL_FENCE_EPOCH}:{token_uuid}"
        replayed = await service.reserve(
            tenant_id,
            idempotency_key="epoch-token",
            job_id="job-epoch",
            cost_units=1,
            operation_id="epoch-token",
            request_fingerprint="fp-epoch",
        )
        assert replayed.fence_token == ticket.fence_token
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.fence_token == ticket.fence_token


def test_settle_checks_locked_epoch_before_status_or_counter_mutation() -> None:
    source = inspect.getsource(SqlAlchemyUsageRepository._settle)
    assert source.index("_lock_global_state") < source.index("_assert_fence_current")
    assert source.index("_assert_fence_current") < source.index("status=settled_status")
    assert source.index("_assert_fence_current") < source.index("_apply_settle_counters")


@pytest.mark.asyncio
async def test_stale_epoch_is_rejected_before_status_or_counter_mutation(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id,
            idempotency_key="stale-epoch",
            job_id="job-stale",
            cost_units=1,
            operation_id="stale-epoch",
            request_fingerprint="fp-stale",
        )
        stored_token = ticket.fence_token
        token_uuid = _assert_modern_fence(stored_token, epoch=DEFAULT_GLOBAL_FENCE_EPOCH)
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            update(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .values(fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH + 1)
        )
        await session.commit()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(UsageFenceMismatchError):
            await service.commit_fenced(ticket, fence_token=stored_token)
        await session.rollback()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        crafted = f"{DEFAULT_GLOBAL_FENCE_EPOCH + 1}:{token_uuid}"
        with pytest.raises(UsageFenceMismatchError):
            await service.commit_fenced(ticket, fence_token=crafted)
        await session.rollback()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.RESERVED
        assert row.fence_token == stored_token
        global_state = await _global_state(session)
        assert global_state.inflight_units == 1
        assert global_state.daily_cost_units == 1
        assert global_state.queue_depth == 1


@pytest.mark.asyncio
async def test_settlement_requires_exact_operation_fingerprint_and_job(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id,
            idempotency_key="bind-op",
            job_id="job-bind",
            cost_units=1,
            operation_id="bind-op",
            request_fingerprint="fp-bind",
        )
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, operation_id="bind-other"))
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, request_fingerprint="fp-other"))
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, job_id="job-other"))
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, operation_id="", request_fingerprint=""))
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, operation_id=""))
        with pytest.raises(ReservationNotFoundError):
            await service.commit(replace(ticket, request_fingerprint=""))
        await service.commit(ticket)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.COMMITTED


@pytest.mark.asyncio
async def test_modern_row_is_not_legacy_just_because_operation_equals_key(database) -> None:
    session_factory, tenant_id, _period_start = database
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        ticket = await service.reserve(
            tenant_id,
            idempotency_key="same-as-operation",
            job_id="job-modern",
            cost_units=1,
        )
        _assert_modern_fence(ticket.fence_token, epoch=DEFAULT_GLOBAL_FENCE_EPOCH)
        assert ticket.operation_id == "same-as-operation"
        assert ticket.request_fingerprint == "same-as-operation"
        await session.commit()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(ReservationNotFoundError):
            await service.commit(
                replace(ticket, operation_id="", request_fingerprint=""),
            )
        await session.rollback()

    async with session_factory() as session:
        row = await _reservation(session, ticket.reservation_id)
        assert row.status == UsageReservationStatus.RESERVED
        assert row.operation_id == "same-as-operation"
        assert row.request_fingerprint == "same-as-operation"


@pytest.mark.asyncio
async def test_explicit_legacy_marker_allows_blank_identity_when_tuple_matches(database) -> None:
    session_factory, tenant_id, period_start = database
    reservation_id = uuid4()
    key = "legacy-key"
    fence = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:legacy:{reservation_id}"
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=reservation_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key=key,
                operation_id=key,
                request_fingerprint=key,
                job_id="legacy-job",
                fence_token=fence,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
            )
        )
        await session.execute(
            update(GlobalUsageAdmissionState)
            .where(GlobalUsageAdmissionState.id == GLOBAL_USAGE_ADMISSION_STATE_ID)
            .values(inflight_units=1, queue_depth=1, daily_cost_units=1)
        )
        await session.commit()

    blank = UsageTicket(
        reservation_id,
        tenant_id,
        key,
        1,
        operation_id="",
        request_fingerprint="",
        job_id="legacy-job",
        fence_token=fence,
    )
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        await service.commit(blank)
        await session.commit()

    async with session_factory() as session:
        row = await _reservation(session, reservation_id)
        assert row.status == UsageReservationStatus.COMMITTED
        assert row.operation_id == key
        assert row.request_fingerprint == key
        assert row.fence_token == fence


@pytest.mark.asyncio
async def test_legacy_blank_identity_requires_matching_tuple(database) -> None:
    session_factory, tenant_id, period_start = database
    reservation_id = uuid4()
    fence = f"{DEFAULT_GLOBAL_FENCE_EPOCH}:legacy:{reservation_id}"
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=reservation_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key="legacy-key",
                operation_id="not-the-key",
                request_fingerprint="legacy-key",
                job_id="legacy-job",
                fence_token=fence,
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
            )
        )
        await session.commit()

    blank = UsageTicket(
        reservation_id,
        tenant_id,
        "legacy-key",
        1,
        operation_id="",
        request_fingerprint="",
        job_id="legacy-job",
        fence_token=fence,
    )
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(ReservationNotFoundError):
            await service.commit(blank)
        await session.rollback()

    async with session_factory() as session:
        row = await _reservation(session, reservation_id)
        assert row.status == UsageReservationStatus.RESERVED


@pytest.mark.asyncio
async def test_malformed_fence_marker_and_epoch_fail_closed(database) -> None:
    session_factory, tenant_id, period_start = database
    reservation_id = uuid4()
    async with session_factory() as session:
        session.add(
            UsageReservation(
                id=reservation_id,
                tenant_id=tenant_id,
                period_start=period_start,
                idempotency_key="bad-fence",
                operation_id="bad-fence",
                request_fingerprint="bad-fence",
                job_id="job-bad",
                fence_token=f"{DEFAULT_GLOBAL_FENCE_EPOCH}:notlegacy:{reservation_id}",
                queue_bytes=0,
                status=UsageReservationStatus.RESERVED,
                cost_units=1,
            )
        )
        await session.commit()

    ticket = UsageTicket(
        reservation_id,
        tenant_id,
        "bad-fence",
        1,
        operation_id="bad-fence",
        request_fingerprint="bad-fence",
        job_id="job-bad",
        fence_token=f"{DEFAULT_GLOBAL_FENCE_EPOCH}:notlegacy:{reservation_id}",
    )
    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(UsageFenceMismatchError):
            await service.commit(ticket)
        await session.rollback()

    zero_epoch = UsageTicket(
        reservation_id,
        tenant_id,
        "bad-fence",
        1,
        operation_id="bad-fence",
        request_fingerprint="bad-fence",
        job_id="job-bad",
        fence_token=f"0:{reservation_id}",
    )
    async with session_factory() as session:
        await session.execute(
            update(UsageReservation)
            .where(UsageReservation.id == reservation_id)
            .values(fence_token=f"0:{reservation_id}")
        )
        await session.commit()

    async with session_factory() as session:
        service = UsageAdmissionService(session)
        with pytest.raises(UsageFenceMismatchError):
            await service.commit(zero_epoch)
        await session.rollback()

    async with session_factory() as session:
        row = await _reservation(session, reservation_id)
        assert row.status == UsageReservationStatus.RESERVED
