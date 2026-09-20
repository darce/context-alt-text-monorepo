"""Focused APP-1 billing repository regression tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import recognition.infrastructure.repositories.billing_repository as billing_module
from db.base import Base
from db.models import BillingSubscriptionProjection, BillingWebhookInbox, Tenant
from recognition.domain.portal_contracts import BillingSubscriptionStatus, WebhookInboxStatus
from recognition.infrastructure.repositories.billing_repository import BillingRepository


class _Result:
    def __init__(self, row: object | None = None, rows: list[object] | None = None) -> None:
        self._row = row
        self._rows = [] if rows is None else rows

    def scalar_one_or_none(self) -> object | None:
        return self._row

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: self._rows)


class _SpySession:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self.events: list[str] = []
        self.fail_execute = fail_execute

    async def execute(self, _statement: object) -> _Result:
        self.events.append("execute")
        if self.fail_execute:
            raise RuntimeError("scan failed")
        return _Result()


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


@pytest_asyncio.fixture
async def billing_session() -> AsyncGenerator[_AsyncSessionFacade, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            BillingSubscriptionProjection.__table__,
            BillingWebhookInbox.__table__,
        ]
        Base.metadata.create_all(connection, tables=tables)

    session = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


async def _create_inbox_row(session: _AsyncSessionFacade, event_id: str) -> BillingWebhookInbox:
    row = BillingWebhookInbox(
        provider="polar",
        provider_event_id=event_id,
        event_type="subscription.active",
        signature_verified=True,
        payload={"data": {"id": event_id}},
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_projection_read_sets_and_clears_tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SpySession()
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    events: list[tuple[str, UUID | None]] = []

    async def set_context(_session: object, value: UUID) -> None:
        events.append(("set", value))

    async def clear_context(_session: object) -> None:
        events.append(("clear", None))

    monkeypatch.setattr(billing_module, "set_tenant_context", set_context)
    monkeypatch.setattr(billing_module, "clear_tenant_context", clear_context)

    assert await BillingRepository(session).get_projection(tenant_id) is None
    assert events == [("set", tenant_id), ("clear", None)]
    assert session.events == ["execute"]


@pytest.mark.asyncio
async def test_pending_scan_releases_maintenance_bypass_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SpySession(fail_execute=True)
    events: list[str] = []

    async def enable(_session: object) -> None:
        events.append("enable")

    async def disable(_session: object) -> None:
        events.append("disable")

    monkeypatch.setattr(billing_module, "enable_rls_bypass", enable)
    monkeypatch.setattr(billing_module, "disable_rls_bypass", disable)

    with pytest.raises(RuntimeError, match="scan failed"):
        await BillingRepository(session).list_pending_webhooks()

    assert events == ["enable", "disable"]
    assert session.events == ["execute"]


@pytest.mark.asyncio
async def test_failed_inbox_rows_back_off_and_quarantine_at_ceiling(
    billing_session: _AsyncSessionFacade,
) -> None:
    backoff_row = await _create_inbox_row(billing_session, "evt-backoff")
    quarantine_row = await _create_inbox_row(billing_session, "evt-quarantine")
    backoff_repo = BillingRepository(
        billing_session,
        max_attempts=20,
        retry_backoff_base_s=2,
        retry_backoff_max_s=5,
    )
    quarantine_repo = BillingRepository(billing_session, max_attempts=2, retry_backoff_base_s=2, retry_backoff_max_s=5)
    now = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    for attempt, expected_delay in enumerate((2, 4, 5, 5), start=1):
        backoff_row.next_attempt_at = now
        assert (
            await backoff_repo.mark_webhook_processed(
                provider="polar",
                provider_event_id="evt-backoff",
                status=WebhookInboxStatus.FAILED,
                processed_at=now,
            )
            is True
        )
        assert backoff_row.attempts == attempt
        assert backoff_row.next_attempt_at == now + timedelta(seconds=expected_delay)
        assert backoff_row.next_attempt_at - now <= timedelta(seconds=5)

    quarantine_row.next_attempt_at = now
    await quarantine_repo.mark_webhook_processed(
        provider="polar",
        provider_event_id="evt-quarantine",
        status=WebhookInboxStatus.FAILED,
        processed_at=now,
    )
    quarantine_row.next_attempt_at = now
    await quarantine_repo.mark_webhook_processed(
        provider="polar",
        provider_event_id="evt-quarantine",
        status=WebhookInboxStatus.FAILED,
        processed_at=now + timedelta(seconds=1),
    )
    await billing_session.commit()

    assert quarantine_row.status == WebhookInboxStatus.DISCARDED.value
    assert quarantine_row.quarantined_at == now + timedelta(seconds=1)
    assert quarantine_row.next_attempt_at is None
    pending = await backoff_repo.list_pending_webhooks(limit=10)
    assert quarantine_row not in pending


@pytest.mark.asyncio
async def test_duplicate_projection_race_uses_savepoint_and_reports_discard(
    billing_session: _AsyncSessionFacade,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = BillingRepository(billing_session)
    first_tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    second_tenant_id = UUID("00000000-0000-0000-0000-000000000002")
    event_position = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

    assert (
        await repo.upsert_projection(
            tenant_id=first_tenant_id,
            provider="polar",
            provider_customer_id="cus-1",
            provider_subscription_id="sub-1",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-1",
            event_position=event_position,
        )
        is True
    )

    original_execute = billing_session.execute
    race_query = True

    async def hide_winner(statement: object) -> object:
        nonlocal race_query
        if race_query:
            race_query = False
            return _Result()
        return await original_execute(statement)

    monkeypatch.setattr(billing_session, "execute", hide_winner)
    assert (
        await repo.upsert_projection(
            tenant_id=first_tenant_id,
            provider="polar",
            provider_customer_id="cus-1",
            provider_subscription_id="sub-1",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-1",
            event_position=event_position,
        )
        is False
    )

    monkeypatch.setattr(billing_session, "execute", original_execute)
    assert (
        await repo.upsert_projection(
            tenant_id=second_tenant_id,
            provider="polar",
            provider_customer_id="cus-2",
            provider_subscription_id="sub-2",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-2",
            event_position=event_position,
        )
        is True
    )
    await billing_session.commit()

    first_projection = await repo.get_projection(first_tenant_id)
    second_projection = await repo.get_projection(second_tenant_id)
    assert first_projection is not None
    assert first_projection.last_event_id == "evt-1"
    assert second_projection is not None
    assert second_projection.last_event_id == "evt-2"
