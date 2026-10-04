"""Regressions for refreshing billing projections after acquiring a row lock."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from db.base import Base
from db.models import BillingSubscriptionProjection, Tenant
from recognition.domain.portal_contracts import BillingSubscriptionStatus
from recognition.infrastructure.repositories.billing_repository import BillingRepository


class _AsyncTransactionFacade:
    def __init__(self, transaction: object) -> None:
        self._transaction = transaction

    async def __aenter__(self) -> _AsyncTransactionFacade:
        self._transaction.__enter__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return bool(self._transaction.__exit__(exc_type, exc, traceback))  # type: ignore[attr-defined]


class _AsyncSessionFacade:
    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def bind(self) -> object:
        return self._session.bind

    def add(self, instance: object) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def execute(self, statement: object) -> object:
        return self._session.execute(statement)

    def begin_nested(self) -> _AsyncTransactionFacade:
        return _AsyncTransactionFacade(self._session.begin_nested())

    async def commit(self) -> None:
        self._session.commit()

    async def close(self) -> None:
        self._session.close()


_BillingSessions = tuple[_AsyncSessionFacade, _AsyncSessionFacade, UUID, Engine]


@pytest_asyncio.fixture
async def billing_sessions(
    tmp_path: Path,
) -> AsyncGenerator[_BillingSessions, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'billing.sqlite'}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        Base.metadata.create_all(
            connection,
            tables=[Table("tenants", Base.metadata), BillingSubscriptionProjection.__table__],
        )

    seed = Session(engine, expire_on_commit=False)
    tenant = Tenant(site_url="https://projection-lock.example.test")
    seed.add(tenant)
    seed.flush()
    seed.add(
        BillingSubscriptionProjection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-a",
            provider_subscription_id="sub-a",
            status=BillingSubscriptionStatus.ACTIVE.value,
            last_event_id="evt-10",
            updated_at=datetime(2026, 10, 1, 0, 10, tzinfo=UTC),
            environment="sandbox",
            seller_account="org-a",
        )
    )
    seed.commit()
    tenant_id = tenant.id
    seed.close()

    session_a = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    session_b = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session_a, session_b, tenant_id, engine
    finally:
        await session_a.close()
        await session_b.close()
        engine.dispose()


def _repo(session: _AsyncSessionFacade) -> BillingRepository:
    return BillingRepository(session, environment="sandbox", seller_account="org-a")


async def _upsert(
    repo: BillingRepository,
    tenant_id: UUID,
    *,
    status: BillingSubscriptionStatus,
    event_id: str,
    position: datetime,
) -> bool:
    return await repo.upsert_projection(
        tenant_id=tenant_id,
        provider="polar",
        provider_customer_id="cus-a",
        provider_subscription_id="sub-a",
        status=status,
        current_period_end=None,
        past_due_since=None,
        provider_event_id=event_id,
        event_position=position,
    )


async def _assert_canceled_at_30(engine: Engine, tenant_id: UUID) -> None:
    with Session(engine, expire_on_commit=False) as observer:
        projection = observer.execute(
            select(BillingSubscriptionProjection).where(BillingSubscriptionProjection.tenant_id == tenant_id)
        ).scalar_one()
        assert projection.status == BillingSubscriptionStatus.CANCELED.value
        assert projection.last_event_id == "evt-30"
        assert projection.updated_at.replace(tzinfo=UTC) == datetime(2026, 10, 1, 0, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_locked_upsert_rejects_event_older_than_concurrent_webhook(
    billing_sessions: _BillingSessions,
) -> None:
    session_a, session_b, tenant_id, engine = billing_sessions
    repo_a = _repo(session_a)
    retained = await repo_a.get_projection(tenant_id, provider="polar")
    assert retained is not None
    assert retained.last_event_id == "evt-10"

    assert await _upsert(
        _repo(session_b),
        tenant_id,
        status=BillingSubscriptionStatus.CANCELED,
        event_id="evt-30",
        position=datetime(2026, 10, 1, 0, 30, tzinfo=UTC),
    )
    await session_b.commit()

    applied = await _upsert(
        repo_a,
        tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        event_id="evt-20",
        position=datetime(2026, 10, 1, 0, 20, tzinfo=UTC),
    )

    assert applied is False
    await _assert_canceled_at_30(engine, tenant_id)


@pytest.mark.asyncio
async def test_locked_upsert_refreshes_projection_retained_across_lease_commit(
    billing_sessions: _BillingSessions,
) -> None:
    session_a, session_b, tenant_id, engine = billing_sessions
    repo_a = _repo(session_a)
    retained = await repo_a.get_projection(tenant_id, provider="polar")
    assert retained is not None
    assert retained.last_event_id == "evt-10"
    await session_a.commit()
    assert retained.last_event_id == "evt-10"

    assert await _upsert(
        _repo(session_b),
        tenant_id,
        status=BillingSubscriptionStatus.CANCELED,
        event_id="evt-30",
        position=datetime(2026, 10, 1, 0, 30, tzinfo=UTC),
    )
    await session_b.commit()

    applied = await _upsert(
        repo_a,
        tenant_id,
        status=BillingSubscriptionStatus.ACTIVE,
        event_id="evt-20",
        position=datetime(2026, 10, 1, 0, 20, tzinfo=UTC),
    )

    assert applied is False
    await _assert_canceled_at_30(engine, tenant_id)
