"""APP-1 S5 billing adapter and inbox behavior tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
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
    BillingState,
    BillingSubscriptionStatus,
    CheckoutSession,
    EnumerationObservationReason,
    EnumerationPage,
    WebhookInboxStatus,
)
from recognition.infrastructure.billing.polar_provider import (
    CheckoutAmbiguityError,
    PaymentsDisabledError,
    PolarBillingProvider,
    PolarEnumerationError,
)
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
    def __init__(self, response: FakeResponse, *, get_response: FakeResponse | None = None) -> None:
        self.response = response
        self.get_response = get_response or response
        self.calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.post_error: BaseException | None = None

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.post_error is not None:
            raise self.post_error
        return self.response

    async def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self.get_response


_WEBHOOK_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
_POLAR_HMAC_SECRET = "whsec_legacy-secret!"
_STANDARD_WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"standard-webhook-key").decode("ascii")
_SELLER_ACCOUNT = "org-altcontext-test"


def _provider(
    client: FakeHttpClient,
    *,
    secret: str = _POLAR_HMAC_SECRET,
    payments_enabled: bool = True,
    environment: str = "sandbox",
    seller_account: str | None = _SELLER_ACCOUNT,
    base_url: str = "https://sandbox.example.test",
) -> PolarBillingProvider:
    return PolarBillingProvider(
        client=client,
        access_token="test-access-token",
        webhook_secret=secret,
        product_ids={"pro": "product-pro"},
        base_url=base_url,
        timeout=2.5,
        payments_enabled=payments_enabled,
        environment=environment,
        seller_account=seller_account,
        allowed_return_origins={"https://app.example.test"},
        clock=lambda: _WEBHOOK_NOW,
    )


def _checkout_kwargs(
    tenant_id: object,
    *,
    idempotency_key: str = "attempt-key-1",
    attempt_id: object | None = None,
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "plan_code": "pro",
        "success_url": "https://app.example.test/success",
        "cancel_url": "https://app.example.test/cancel",
        "idempotency_key": idempotency_key,
        "attempt_id": attempt_id if attempt_id is not None else uuid4(),
    }


def _event_body(
    *,
    event_id: str | None = "evt-1",
    event_type: str = "subscription.active",
    timestamp: datetime = _WEBHOOK_NOW,
) -> bytes:
    payload: dict[str, object] = {
        "type": event_type,
        "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "data": {
            "id": "sub-1",
            "customer_id": "cus-1",
            "status": "active",
            "current_period_end": "2026-10-20T12:00:00Z",
        },
    }
    if event_id is not None:
        payload["id"] = event_id
    return json.dumps(
        payload,
        separators=(",", ":"),
    ).encode()


def _webhook_headers(
    body: bytes,
    secret: str,
    *,
    webhook_id: str = "msg-1",
    timestamp: datetime = _WEBHOOK_NOW,
    signing: str = "polar_hmac",
) -> dict[str, str]:
    ts = str(int(timestamp.timestamp()))
    signed_content = f"{webhook_id}.{ts}.{body.decode('utf-8')}".encode()
    if signing == "standard":
        remainder = secret.removeprefix("whsec_")
        key = base64.b64decode(remainder + "=" * (-len(remainder) % 4), validate=True)
    else:
        key = secret.encode("utf-8")
    signature = "v1," + base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode("ascii")
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": signature,
    }


@pytest.mark.asyncio
async def test_polar_provider_is_runtime_checkable_and_uses_timeout() -> None:
    client = FakeHttpClient(FakeResponse({"id": "chk-1", "url": "https://checkout.example.test/session"}))
    provider = _provider(client)
    tenant_id = uuid4()
    attempt_id = uuid4()

    assert isinstance(provider, BillingProvider)
    session = await provider.create_checkout_session(**_checkout_kwargs(tenant_id, attempt_id=attempt_id))

    assert isinstance(session, CheckoutSession)
    assert session.url == "https://checkout.example.test/session"
    assert session.provider_checkout_id == "chk-1"
    assert client.calls[0]["request_timeout"] == 2.5
    assert client.calls[0]["json"] == {
        "products": ["product-pro"],
        "external_customer_id": f"sandbox:{tenant_id}",
        "metadata": {
            "tenant_id": str(tenant_id),
            "environment": "sandbox",
            "seller_account": _SELLER_ACCOUNT,
            "attempt_id": str(attempt_id),
        },
        "success_url": "https://app.example.test/success",
        "return_url": "https://app.example.test/cancel",
    }
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Idempotency-Key"] == "attempt-key-1"


@pytest.mark.asyncio
async def test_h3_retrieve_state_returns_authoritative_billing_state() -> None:
    tenant_id = uuid4()
    client = FakeHttpClient(
        FakeResponse(
            {
                "id": "sub-1",
                "customer_id": "cus-1",
                "tenant_id": str(tenant_id),
                "status": "active",
                "current_period_end": "2026-10-20T12:00:00Z",
                "updated_at": "2026-09-20T12:00:00Z",
            }
        )
    )
    provider = _provider(client)

    state = await provider.retrieve_state(
        provider_customer_id="sandbox:cus-1",
        provider_subscription_id="sandbox:sub-1",
        request_timeout=1.75,
    )

    assert isinstance(state, BillingState)
    assert state.tenant_id == tenant_id
    assert state.status is BillingSubscriptionStatus.ACTIVE
    assert state.provider_customer_id == "sandbox:cus-1"
    assert state.provider_subscription_id == "sandbox:sub-1"
    assert state.event_position == _WEBHOOK_NOW
    assert client.get_calls == [
        {
            "url": "https://sandbox.example.test/v1/subscriptions/sub-1",
            "headers": {"Authorization": "Bearer test-access-token"},
            "request_timeout": 1.75,
        }
    ]


@pytest.mark.asyncio
async def test_h7_checkout_and_portal_refuse_when_payments_are_disabled() -> None:
    client = FakeHttpClient(FakeResponse({"id": "unused", "url": "https://unused.example.test/session"}))
    provider = _provider(client, payments_enabled=False)
    tenant_id = uuid4()

    with pytest.raises(PaymentsDisabledError, match="payments are disabled"):
        await provider.create_checkout_session(**_checkout_kwargs(tenant_id))
    with pytest.raises(PaymentsDisabledError, match="payments are disabled"):
        await provider.create_portal_session(tenant_id=tenant_id, return_url="https://app.example.test/return")

    assert client.calls == []


@pytest.mark.asyncio
async def test_h5_timed_out_checkout_does_not_retry_creation() -> None:
    client = FakeHttpClient(FakeResponse({"id": "unused", "url": "unused"}))
    client.post_error = TimeoutError("simulated timeout")
    provider = _provider(client)

    with pytest.raises(CheckoutAmbiguityError, match="outcome is ambiguous"):
        await provider.create_checkout_session(**_checkout_kwargs(uuid4(), idempotency_key="same-attempt-key"))

    assert len(client.calls) == 1
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Idempotency-Key"] == "same-attempt-key"


@pytest.mark.asyncio
async def test_h5_checkout_idempotency_key_is_caller_owned_not_url_hash() -> None:
    client = FakeHttpClient(FakeResponse({"id": "chk-1", "url": "https://checkout.example.test/session"}))
    provider = _provider(client)
    tenant_id = uuid4()
    same_urls = _checkout_kwargs(tenant_id, idempotency_key="attempt-a")
    retry = dict(same_urls)
    new_attempt = _checkout_kwargs(tenant_id, idempotency_key="attempt-b")

    await provider.create_checkout_session(**same_urls)
    await provider.create_checkout_session(**retry)
    await provider.create_checkout_session(**new_attempt)

    keys = [call["headers"]["Idempotency-Key"] for call in client.calls]
    assert keys == ["attempt-a", "attempt-a", "attempt-b"]
    assert not any(str(key).startswith("sandbox-") for key in keys)


@pytest.mark.asyncio
async def test_m11_replayed_or_skewed_webhook_is_rejected() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = _event_body()
    stale = _webhook_headers(body, _POLAR_HMAC_SECRET, timestamp=_WEBHOOK_NOW - timedelta(minutes=6))
    missing_id = _webhook_headers(body, _POLAR_HMAC_SECRET)
    missing_id.pop("webhook-id")
    missing_timestamp = _webhook_headers(body, _POLAR_HMAC_SECRET)
    missing_timestamp.pop("webhook-timestamp")

    assert await provider.verify_webhook(body, stale) is False
    assert await provider.verify_webhook(body, missing_id) is False
    assert await provider.verify_webhook(body, missing_timestamp) is False


@pytest.mark.asyncio
async def test_m18_non_allowlisted_return_url_is_rejected() -> None:
    client = FakeHttpClient(FakeResponse({"id": "chk-1", "url": "https://checkout.example.test/session"}))
    provider = _provider(client)
    tenant_id = uuid4()

    with pytest.raises(ValueError, match="not allowlisted"):
        await provider.create_checkout_session(
            **{
                **_checkout_kwargs(tenant_id),
                "success_url": "https://evil.example.test/success",
            }
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        await provider.create_portal_session(tenant_id=tenant_id, return_url="https://evil.example.test/return")
    assert client.calls == []


@pytest.mark.asyncio
async def test_verify_webhook_accepts_polar_hmac_and_standard_webhooks_keys() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    hmac_provider = _provider(client, secret=_POLAR_HMAC_SECRET)
    standard_provider = _provider(client, secret=_STANDARD_WEBHOOK_SECRET)
    body = _event_body()

    polar_headers = _webhook_headers(body, _POLAR_HMAC_SECRET, signing="polar_hmac")
    standard_headers = _webhook_headers(body, _STANDARD_WEBHOOK_SECRET, signing="standard")
    assert await hmac_provider.verify_webhook(body, polar_headers) is True
    assert await standard_provider.verify_webhook(body, standard_headers) is True


@pytest.mark.asyncio
async def test_verify_webhook_rejects_tamper_missing_headers_and_replay() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = _event_body()
    headers = _webhook_headers(body, _POLAR_HMAC_SECRET)

    assert await provider.verify_webhook(body, headers) is True
    assert await provider.verify_webhook(body + b" ", headers) is False
    assert await provider.verify_webhook(body, {**headers, "webhook-signature": "v1,not-a-signature"}) is False
    assert await provider.verify_webhook(body, {k: v for k, v in headers.items() if k != "webhook-signature"}) is False
    future = _webhook_headers(body, _POLAR_HMAC_SECRET, timestamp=_WEBHOOK_NOW + timedelta(minutes=6))
    assert await provider.verify_webhook(body, future) is False
    assert await provider.verify_webhook(body, None) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_parse_event_requires_verified_payload_and_does_not_add_metadata() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = _event_body()
    headers = _webhook_headers(body, _POLAR_HMAC_SECRET)

    with pytest.raises(ValueError, match="verified"):
        await provider.parse_event(body)

    assert await provider.verify_webhook(body, headers) is True
    parsed = await provider.parse_event(body)
    expected = json.loads(body)
    expected["id"] = "sandbox:evt-1"
    expected["data"]["id"] = "sandbox:sub-1"
    expected["data"]["customer_id"] = "sandbox:cus-1"
    assert parsed == expected
    assert "provider" not in parsed
    assert "signature_verified" not in parsed


@pytest.mark.asyncio
async def test_parse_event_rejects_unexpected_shape_after_header_verification() -> None:
    client = FakeHttpClient(FakeResponse({"url": "unused"}))
    provider = _provider(client)
    body = b'{"id":"evt-1","type":"subscription.active","timestamp":"2026-09-20T12:00:00Z","data":[]}'
    headers = _webhook_headers(body, _POLAR_HMAC_SECRET)

    assert await provider.verify_webhook(body, headers) is True
    with pytest.raises(ValueError, match="data"):
        await provider.parse_event(body)


@pytest.mark.asyncio
async def test_sandbox_environment_rejects_live_polar_host() -> None:
    client = FakeHttpClient(FakeResponse({"id": "chk-1", "url": "https://unused"}))
    with pytest.raises(ValueError, match="environment"):
        _provider(client, environment="sandbox", base_url="https://api.polar.sh")
    with pytest.raises(ValueError, match="environment"):
        _provider(client, environment="live", base_url="https://sandbox-api.polar.sh")


@pytest.mark.asyncio
async def test_retrieve_checkout_is_bounded_get() -> None:
    client = FakeHttpClient(
        FakeResponse({"id": "chk-1", "url": "https://checkout.example.test/session"}),
        get_response=FakeResponse({"id": "chk-1", "status": "open", "url": "https://checkout.example.test/session"}),
    )
    provider = _provider(client)

    payload = await provider.retrieve_checkout(provider_checkout_id="sandbox:chk-1", request_timeout=1.5)

    assert payload["id"] == "chk-1"
    assert client.get_calls == [
        {
            "url": "https://sandbox.example.test/v1/checkouts/chk-1",
            "headers": {"Authorization": "Bearer test-access-token"},
            "request_timeout": 1.5,
        }
    ]


@pytest.mark.asyncio
async def test_enumerate_subscriptions_uses_opaque_cursor_and_skips_untrusted_identity() -> None:
    tenant_id = uuid4()
    client = FakeHttpClient(
        FakeResponse({"url": "unused"}),
        get_response=FakeResponse(
            {
                "items": [
                    {
                        "id": "sub-ok",
                        "customer_id": "cus-ok",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-ok",
                            "external_id": f"sandbox:{tenant_id}",
                            "email": "ignored@example.test",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    },
                    {
                        "id": "sub-foreign-org",
                        "customer_id": "cus-foreign",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-foreign",
                            "external_id": f"sandbox:{uuid4()}",
                            "email": "attacker@example.test",
                            "organization_id": "org-other-seller",
                        },
                    },
                    {
                        "id": "sub-email-only",
                        "customer_id": "cus-email",
                        "status": "active",
                        "current_period_end": "2026-10-20T12:00:00Z",
                        "modified_at": "2026-09-20T12:00:00Z",
                        "customer": {
                            "id": "cus-email",
                            "email": str(tenant_id) + "@example.test",
                            "organization_id": _SELLER_ACCOUNT,
                        },
                    },
                ],
                "pagination": {"total_count": 3, "max_page": 2},
            }
        ),
    )
    provider = _provider(client)

    page = await provider.enumerate_subscriptions(cursor=None, limit=50, request_timeout=2.0)

    assert isinstance(page, EnumerationPage)
    assert page.next_cursor == "2"
    assert page.exhausted is False
    assert len(page.items) == 1
    assert page.items[0].tenant_id == tenant_id
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"
    reasons = {observation.reason for observation in page.observations}
    assert EnumerationObservationReason.SELLER_MISMATCH in reasons
    assert EnumerationObservationReason.EMAIL_IDENTITY_REJECTED in reasons
    assert all("@" not in observation.remote_id for observation in page.observations)
    assert client.get_calls[0]["url"] == (
        f"https://sandbox.example.test/v1/subscriptions/?page=1&limit=50&organization_id={_SELLER_ACCOUNT}"
    )


@pytest.mark.asyncio
async def test_enumerate_subscriptions_rejects_malformed_page_and_cursor() -> None:
    client = FakeHttpClient(
        FakeResponse({"url": "unused"}),
        get_response=FakeResponse({"items": "not-a-list", "pagination": {"total_count": 1, "max_page": 1}}),
    )
    provider = _provider(client)

    with pytest.raises(PolarEnumerationError):
        await provider.enumerate_subscriptions(cursor="1", limit=50, request_timeout=1.0)
    with pytest.raises(ValueError, match="cursor"):
        await provider.enumerate_subscriptions(cursor="1;drop", limit=50, request_timeout=1.0)
    with pytest.raises(ValueError, match="limit"):
        await provider.enumerate_subscriptions(cursor="1", limit=0, request_timeout=1.0)


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
    repo = BillingRepository(billing_session, environment="sandbox", seller_account=_SELLER_ACCOUNT)
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
    repo = BillingRepository(billing_session, environment="sandbox", seller_account=_SELLER_ACCOUNT)
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
    repo = BillingRepository(billing_session, environment="sandbox", seller_account=_SELLER_ACCOUNT)
    rows = await repo.list_pending_webhooks(limit=3)

    assert rows == []
    assert WebhookInboxStatus.RECEIVED.value == "received"
    assert BillingSubscriptionStatus.NONE.value == "none"
