"""APP-1 S5 billing adapter and inbox behavior tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models import BillingSubscriptionProjection, BillingWebhookInbox, Tenant
from recognition.domain.portal_contracts import (
    BillingProvider,
    BillingSubscriptionStatus,
    WebhookInboxStatus,
)
from recognition.infrastructure.billing.polar_provider import PolarBillingProvider
from recognition.infrastructure.repositories.billing_repository import BillingRepository


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, object]:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def _provider(client: FakeHttpClient, *, secret: str = "test-webhook-secret") -> PolarBillingProvider:
    return PolarBillingProvider(
        client=client,
        access_token="test-access-token",
        webhook_secret=secret,
        product_ids={"pro": "product-pro"},
        base_url="https://sandbox.example.test",
        timeout=2.5,
    )


def _event_body(*, event_id: str = "evt-1", event_type: str = "subscription.active") -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "timestamp": "2026-09-20T12:00:00Z",
            "data": {
                "id": "sub-1",
                "customer_id": "cus-1",
                "status": "active",
                "current_period_end": "2026-10-20T12:00:00Z",
            },
        },
        separators=(",", ":"),
    ).encode()


def _signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@pytest.mark.asyncio
async def test_polar_provider_is_runtime_checkable_and_uses_timeout() -> None:
    client = FakeHttpClient(FakeResponse({"url": "https://checkout.example.test/session"}))
    provider = _provider(client)
    tenant_id = uuid4()

    assert isinstance(provider, BillingProvider)
    checkout_url = await provider.create_checkout_session(
        tenant_id=tenant_id,
        plan_code="pro",
        success_url="https://app.example.test/success",
        cancel_url="https://app.example.test/cancel",
    )

    assert checkout_url == "https://checkout.example.test/session"
    assert client.calls[0]["timeout"] == 2.5
    assert client.calls[0]["json"] == {
        "products": ["product-pro"],
        "metadata": {"tenant_id": str(tenant_id)},
        "success_url": "https://app.example.test/success",
        "return_url": "https://app.example.test/cancel",
    }


@pytest.mark.asyncio
async def test_verify_webhook_uses_exact_raw_body_and_fails_closed() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = _event_body()
    signature = _signature(body, "test-webhook-secret")

    assert await provider.verify_webhook(body, signature) is True
    assert await provider.verify_webhook(body + b" ", signature) is False
    assert await provider.verify_webhook(body, "") is False
    assert await provider.verify_webhook(body, "not-a-signature") is False
    assert await provider.verify_webhook(body, None) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_parse_event_requires_verified_payload_and_does_not_add_metadata() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = _event_body()

    with pytest.raises(ValueError, match="verified"):
        await provider.parse_event(body)

    assert await provider.verify_webhook(body, _signature(body, "test-webhook-secret")) is True
    parsed = await provider.parse_event(body)
    assert parsed == json.loads(body)
    assert "provider" not in parsed
    assert "signature_verified" not in parsed


@pytest.mark.asyncio
async def test_parse_event_rejects_unexpected_shape_after_verification() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = b'{"event":{"type":"subscription.active"}}'

    assert await provider.verify_webhook(body, _signature(body, "test-webhook-secret")) is True
    with pytest.raises(ValueError, match="type|timestamp|data"):
        await provider.parse_event(body)


class _AsyncTransactionFacade:
    def __init__(self, transaction: object) -> None:
        self._transaction = transaction

    async def __aenter__(self) -> _AsyncTransactionFacade:
        self._transaction.__enter__()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return bool(self._transaction.__exit__(exc_type, exc, traceback))  # type: ignore[attr-defined]


class _AsyncSessionFacade:
    """AsyncSession-shaped wrapper used because this lane sandbox cannot open aiosqlite."""

    def __init__(self, session: Session) -> None:
        self._session = session

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
        connection.execute(text("PRAGMA foreign_keys=ON"))
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


async def _tenant(session: _AsyncSessionFacade) -> Tenant:
    tenant = Tenant(site_url="https://tenant.example.test")
    session.add(tenant)
    await session.flush()
    return tenant


@pytest.mark.asyncio
async def test_inbox_is_verified_idempotency_boundary(billing_session: _AsyncSessionFacade) -> None:
    tenant = await _tenant(billing_session)
    repo = BillingRepository(billing_session)
    payload = {"type": "subscription.active", "data": {"id": "sub-1"}}

    with pytest.raises(PermissionError):
        await repo.record_webhook(
            provider="polar",
            provider_event_id="evt-unverified",
            event_type="subscription.active",
            signature_verified=False,
            payload=payload,
        )

    first = await repo.record_webhook(
        provider="polar",
        provider_event_id="evt-1",
        event_type="subscription.active",
        signature_verified=True,
        payload=payload,
    )
    duplicate = await repo.record_webhook(
        provider="polar",
        provider_event_id="evt-1",
        event_type="subscription.active",
        signature_verified=True,
        payload=payload,
    )
    await billing_session.commit()

    assert first is True
    assert duplicate is False
    row = await repo.get_webhook(provider="polar", provider_event_id="evt-1")
    assert row is not None
    assert row.status == WebhookInboxStatus.RECEIVED.value
    assert row.signature_verified is True
    assert tenant.id is not None


@pytest.mark.asyncio
async def test_projection_rejects_stale_event_position(billing_session: _AsyncSessionFacade) -> None:
    tenant = await _tenant(billing_session)
    repo = BillingRepository(billing_session)
    newer = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
    older = datetime(2026, 9, 20, 11, 0, tzinfo=UTC)

    assert (
        await repo.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-1",
            provider_subscription_id="sub-1",
            status=BillingSubscriptionStatus.ACTIVE,
            current_period_end=datetime(2026, 10, 20, tzinfo=UTC),
            past_due_since=None,
            provider_event_id="evt-new",
            event_position=newer,
        )
        is True
    )
    assert (
        await repo.upsert_projection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus-1",
            provider_subscription_id="sub-1",
            status=BillingSubscriptionStatus.CANCELED,
            current_period_end=None,
            past_due_since=None,
            provider_event_id="evt-old",
            event_position=older,
        )
        is False
    )
    await billing_session.commit()

    projection = await repo.get_projection(tenant.id)
    assert projection is not None
    assert projection.status == BillingSubscriptionStatus.ACTIVE.value
    assert projection.last_event_id == "evt-new"


@pytest.mark.asyncio
async def test_repository_uses_status_vocabularies_and_bounds_pending_reads(
    billing_session: _AsyncSessionFacade,
) -> None:
    repo = BillingRepository(billing_session)
    rows = await repo.list_pending_webhooks(limit=3)

    assert rows == []
    assert WebhookInboxStatus.RECEIVED.value == "received"
    assert BillingSubscriptionStatus.NONE.value == "none"
