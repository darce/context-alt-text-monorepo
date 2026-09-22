"""Behavioral tests for durable checkout attempt orchestration."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.portal_billing import BillingCheckoutAttempt, CheckoutAttemptErrorClass, CheckoutAttemptStatus
from db.models.tenant import Tenant
from recognition.application.services.checkout_service import (
    CheckoutActiveConflictError,
    CheckoutAmbiguousError,
    CheckoutFingerprintConflictError,
    CheckoutPaymentsDisabledError,
    CheckoutResult,
    CheckoutService,
)
from recognition.domain.portal_contracts import CheckoutSession
from recognition.infrastructure.billing.polar_provider import (
    CheckoutAmbiguityError,
    PolarBillingProvider,
    PolarRequestError,
)
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository


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
        self.events: list[str] = []

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
        self.events.append("commit")
        self._session.commit()

    async def close(self) -> None:
        self._session.close()


class FakeBillingProvider:
    """In-process provider: no live charges, records exact create_checkout_session kwargs."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        payments_enabled: bool = True,
        events: list[str] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.error = error
        self.payments_enabled = payments_enabled
        self.events = events

    async def create_checkout_session(
        self,
        *,
        tenant_id: UUID,
        plan_code: str,
        success_url: str,
        cancel_url: str,
        idempotency_key: str,
        attempt_id: UUID,
    ) -> CheckoutSession:
        if self.events is not None:
            self.events.append("provider")
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "plan_code": plan_code,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "idempotency_key": idempotency_key,
                "attempt_id": attempt_id,
            }
        )
        if self.error is not None:
            raise self.error
        return CheckoutSession(
            url=f"https://pay.example.test/{idempotency_key}",
            provider_checkout_id=f"chk-{attempt_id}",
        )


class _FakePolarResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload


class _FakePolarHttpClient:
    """Injected Polar transport: records POSTs, never opens a network socket."""

    def __init__(self, response: _FakePolarResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def post(self, url: str, **kwargs: object) -> _FakePolarResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


@pytest_asyncio.fixture
async def checkout_session() -> AsyncGenerator[_AsyncSessionFacade, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [Table("tenants", Base.metadata), BillingCheckoutAttempt.__table__]
        Base.metadata.create_all(connection, tables=tables)

    session = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


async def _create_tenant(session: _AsyncSessionFacade, suffix: str) -> Tenant:
    tenant = Tenant(site_url=f"https://checkout-svc-{suffix}.example.test")
    session.add(tenant)
    await session.flush()
    return tenant


def _service(
    session: _AsyncSessionFacade,
    provider: FakeBillingProvider,
    *,
    payments_enabled: bool = True,
    seller_account: str = "org_sandbox",
    environment: str = "sandbox",
    keys: list[str] | None = None,
) -> CheckoutService:
    remaining = iter(keys or ["provider-key-1", "provider-key-2", "provider-key-3"])
    if provider.events is None:
        provider.events = session.events
    return CheckoutService(
        CheckoutAttemptRepository(session),
        provider,
        payments_enabled=payments_enabled,
        provider_name="fake",
        environment=environment,
        seller_account=seller_account,
        idempotency_key_factory=lambda: next(remaining),
    )


def _polar_provider(client: _FakePolarHttpClient) -> PolarBillingProvider:
    return PolarBillingProvider(
        client=client,
        access_token="test-access-token",
        webhook_secret="whsec_checkout-service-test",
        product_ids={"pro": "product-pro"},
        base_url="https://sandbox.example.test",
        timeout=2.5,
        payments_enabled=True,
        environment="sandbox",
        seller_account="org_sandbox",
        allowed_return_origins={"https://app.example.test"},
    )


def _polar_service(
    session: _AsyncSessionFacade,
    client: _FakePolarHttpClient,
    *,
    keys: list[str] | None = None,
) -> CheckoutService:
    remaining = iter(keys or ["provider-key-1", "provider-key-2", "provider-key-3"])
    return CheckoutService(
        CheckoutAttemptRepository(session),
        _polar_provider(client),
        payments_enabled=True,
        provider_name="polar",
        environment="sandbox",
        seller_account="org_sandbox",
        idempotency_key_factory=lambda: next(remaining),
    )


def _create_kwargs(tenant_id: UUID, **overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "plan_code": "pro",
        "success_url": "https://app.example.test/billing/return",
        "cancel_url": "https://app.example.test/billing/cancel",
        "client_idempotency_key": "client-key-1",
    }
    payload.update(overrides)
    return payload


async def _load_attempt(session: _AsyncSessionFacade, attempt_id: UUID) -> BillingCheckoutAttempt:
    result = await session.execute(
        select(BillingCheckoutAttempt).where(BillingCheckoutAttempt.id == attempt_id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise AssertionError("checkout attempt was not persisted")
    return row


@pytest.mark.asyncio
async def test_payments_disabled_blocks_before_persist_or_provider(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "pay-off")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider, payments_enabled=False)

    with pytest.raises(CheckoutPaymentsDisabledError):
        await service.create_checkout(**_create_kwargs(tenant.id))

    assert provider.calls == []
    assert checkout_session.events == []
    rows = (await checkout_session.execute(select(BillingCheckoutAttempt))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_persists_and_commits_created_before_provider_call(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "order")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)

    result = await service.create_checkout(**_create_kwargs(tenant.id))

    assert checkout_session.events[0] == "commit"
    assert checkout_session.events.index("commit") < checkout_session.events.index("provider")
    assert result.replayed is False
    assert result.status is CheckoutAttemptStatus.PENDING
    assert result.checkout_url == "https://pay.example.test/provider-key-1"
    row = await _load_attempt(checkout_session, result.attempt_id)
    assert row.status == CheckoutAttemptStatus.PENDING.value
    assert row.idempotency_key == "provider-key-1"
    assert row.provider_checkout_id == f"chk-{result.attempt_id}"
    assert row.checkout_url == result.checkout_url
    assert provider.calls[0]["idempotency_key"] == "provider-key-1"
    assert provider.calls[0]["attempt_id"] == result.attempt_id
    assert provider.calls[0]["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_same_client_key_and_fingerprint_replays_without_second_vendor_call(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "replay")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)
    first = await service.create_checkout(**_create_kwargs(tenant.id))

    second = await service.create_checkout(**_create_kwargs(tenant.id))

    assert second.replayed is True
    assert second.attempt_id == first.attempt_id
    assert second.checkout_url == first.checkout_url
    assert second.status is CheckoutAttemptStatus.PENDING
    assert len(provider.calls) == 1
    assert [call["idempotency_key"] for call in provider.calls] == ["provider-key-1"]


@pytest.mark.asyncio
async def test_fingerprint_mismatch_raises_without_provider_call(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "mismatch")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)
    await service.create_checkout(**_create_kwargs(tenant.id))
    provider.calls.clear()

    with pytest.raises(CheckoutFingerprintConflictError):
        await service.create_checkout(**_create_kwargs(tenant.id, plan_code="starter_monthly"))

    assert provider.calls == []


@pytest.mark.asyncio
async def test_timeout_marks_ambiguous_and_retry_does_not_mutate_vendor(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "timeout")
    provider = FakeBillingProvider(error=CheckoutAmbiguityError("simulated timeout"))
    service = _service(checkout_session, provider)

    with pytest.raises(CheckoutAmbiguousError) as first:
        await service.create_checkout(**_create_kwargs(tenant.id))

    attempt_id = first.value.attempt_id
    row = await _load_attempt(checkout_session, attempt_id)
    assert row.status == CheckoutAttemptStatus.AMBIGUOUS.value
    assert row.last_error_class == CheckoutAttemptErrorClass.AMBIGUOUS.value
    assert row.provider_checkout_id is None
    assert len(provider.calls) == 1

    with pytest.raises(CheckoutAmbiguousError) as retry:
        await service.create_checkout(**_create_kwargs(tenant.id))

    assert retry.value.attempt_id == attempt_id
    assert len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {"url": "https://pay.example.test/session"},
        {"id": "chk-malformed"},
        ["not-an-object"],
    ),
    ids=("missing_id", "missing_url", "nonobject_body"),
)
async def test_polar_http_200_malformed_body_stays_ambiguous_and_retry_does_not_post(
    checkout_session: _AsyncSessionFacade,
    payload: object,
) -> None:
    tenant = await _create_tenant(checkout_session, "polar-malformed")
    client = _FakePolarHttpClient(_FakePolarResponse(payload))
    service = _polar_service(checkout_session, client)

    with pytest.raises(CheckoutAmbiguousError) as first:
        await service.create_checkout(**_create_kwargs(tenant.id))

    attempt_id = first.value.attempt_id
    row = await _load_attempt(checkout_session, attempt_id)
    assert row.status == CheckoutAttemptStatus.AMBIGUOUS.value
    assert row.last_error_class == CheckoutAttemptErrorClass.AMBIGUOUS.value
    assert row.provider_checkout_id is None
    assert row.checkout_url is None
    assert row.idempotency_key == "provider-key-1"
    assert len(client.calls) == 1
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Idempotency-Key"] == "provider-key-1"
    assert str(client.calls[0]["url"]).endswith("/v1/checkouts/")

    with pytest.raises(CheckoutAmbiguousError) as retry:
        await service.create_checkout(**_create_kwargs(tenant.id))

    assert retry.value.attempt_id == attempt_id
    assert len(client.calls) == 1
    retried = await _load_attempt(checkout_session, attempt_id)
    assert retried.idempotency_key == "provider-key-1"
    assert retried.status == CheckoutAttemptStatus.AMBIGUOUS.value


@pytest.mark.asyncio
async def test_provider_requested_without_url_refuses_new_vendor_mutation(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "inflight")
    provider = FakeBillingProvider()
    repo = CheckoutAttemptRepository(checkout_session)
    begun = await repo.begin_attempt(
        tenant_id=tenant.id,
        provider="fake",
        environment="sandbox",
        seller_account="org_sandbox",
        plan_code="pro",
        idempotency_key="provider-key-1",
        client_idempotency_key="client-key-1",
        request_fingerprint=CheckoutService.fingerprint(
            tenant_id=tenant.id,
            plan_code="pro",
            success_url="https://app.example.test/billing/return",
            cancel_url="https://app.example.test/billing/cancel",
            environment="sandbox",
            seller_account="org_sandbox",
        ),
    )
    await repo.mark_provider_requested(tenant.id, begun.attempt.id)
    await checkout_session.commit()
    checkout_session.events.clear()

    with pytest.raises(CheckoutAmbiguousError) as refused:
        await _service(checkout_session, provider).create_checkout(**_create_kwargs(tenant.id))

    assert refused.value.attempt_id == begun.attempt.id
    assert provider.calls == []


@pytest.mark.asyncio
async def test_expired_attempt_new_client_key_mints_new_provider_key(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "expired")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)
    first = await service.create_checkout(**_create_kwargs(tenant.id))
    repo = CheckoutAttemptRepository(checkout_session)
    await repo.mark_terminal(
        tenant.id,
        first.attempt_id,
        status=CheckoutAttemptStatus.EXPIRED,
        last_error_class=CheckoutAttemptErrorClass.EXPIRED,
    )
    await checkout_session.commit()

    second = await service.create_checkout(**_create_kwargs(tenant.id, client_idempotency_key="client-key-2"))

    assert second.replayed is False
    assert second.attempt_id != first.attempt_id
    assert [call["idempotency_key"] for call in provider.calls] == ["provider-key-1", "provider-key-2"]
    row = await _load_attempt(checkout_session, second.attempt_id)
    assert row.idempotency_key == "provider-key-2"
    assert row.client_idempotency_key == "client-key-2"


@pytest.mark.asyncio
async def test_foreign_tenant_same_client_key_is_isolated(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant_a = await _create_tenant(checkout_session, "iso-a")
    tenant_b = await _create_tenant(checkout_session, "iso-b")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)
    first = await service.create_checkout(**_create_kwargs(tenant_a.id))

    isolated = await service.create_checkout(**_create_kwargs(tenant_b.id))

    assert isolated.attempt_id != first.attempt_id
    assert isolated.replayed is False
    assert len(provider.calls) == 2
    assert {call["tenant_id"] for call in provider.calls} == {tenant_a.id, tenant_b.id}


@pytest.mark.asyncio
async def test_seller_and_environment_boundaries_do_not_replay_across_namespace(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "ns")
    sandbox_provider = FakeBillingProvider()
    sandbox = _service(checkout_session, sandbox_provider, seller_account="org_sandbox")
    first = await sandbox.create_checkout(**_create_kwargs(tenant.id))

    live_provider = FakeBillingProvider()
    live = _service(
        checkout_session,
        live_provider,
        seller_account="org_live",
        environment="live",
        keys=["live-key-1"],
    )
    second = await live.create_checkout(**_create_kwargs(tenant.id))

    assert second.attempt_id != first.attempt_id
    assert second.replayed is False
    assert len(sandbox_provider.calls) == 1
    assert len(live_provider.calls) == 1
    row = await _load_attempt(checkout_session, second.attempt_id)
    assert row.environment == "live"
    assert row.seller_account == "org_live"


@pytest.mark.asyncio
async def test_rejected_provider_response_marks_failed_without_checkout_url(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "reject")
    provider = FakeBillingProvider(error=PolarRequestError(400, "checkout"))
    service = _service(checkout_session, provider)

    with pytest.raises(PolarRequestError):
        await service.create_checkout(**_create_kwargs(tenant.id))

    rows = (await checkout_session.execute(select(BillingCheckoutAttempt))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == CheckoutAttemptStatus.FAILED.value
    assert rows[0].last_error_class == CheckoutAttemptErrorClass.REJECTED.value
    assert rows[0].checkout_url is None
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_open_attempt_for_same_plan_conflicts_without_second_vendor_call(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "active")
    provider = FakeBillingProvider()
    service = _service(checkout_session, provider)
    await service.create_checkout(**_create_kwargs(tenant.id))

    with pytest.raises(CheckoutActiveConflictError):
        await service.create_checkout(**_create_kwargs(tenant.id, client_idempotency_key="client-key-2"))

    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_created_crash_resume_reuses_attempt_owned_provider_key(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "resume")
    provider = FakeBillingProvider()
    repo = CheckoutAttemptRepository(checkout_session)
    fingerprint = CheckoutService.fingerprint(
        tenant_id=tenant.id,
        plan_code="pro",
        success_url="https://app.example.test/billing/return",
        cancel_url="https://app.example.test/billing/cancel",
        environment="sandbox",
        seller_account="org_sandbox",
    )
    begun = await repo.begin_attempt(
        tenant_id=tenant.id,
        provider="fake",
        environment="sandbox",
        seller_account="org_sandbox",
        plan_code="pro",
        idempotency_key="crash-key",
        client_idempotency_key="client-key-1",
        request_fingerprint=fingerprint,
    )
    await checkout_session.commit()

    result = await _service(checkout_session, provider).create_checkout(**_create_kwargs(tenant.id))

    assert result.attempt_id == begun.attempt.id
    assert result.replayed is True
    assert provider.calls[0]["idempotency_key"] == "crash-key"
    assert isinstance(result, CheckoutResult)
    row = await _load_attempt(checkout_session, result.attempt_id)
    assert row.status == CheckoutAttemptStatus.PENDING.value


def test_fingerprint_is_canonical_json_of_tenant_plan_urls_and_seller() -> None:
    tenant_id = uuid4()
    left = CheckoutService.fingerprint(
        tenant_id=tenant_id,
        plan_code="pro",
        success_url="https://app.example.test/a",
        cancel_url="https://app.example.test/b",
        environment="sandbox",
        seller_account="org_sandbox",
    )
    right = CheckoutService.fingerprint(
        tenant_id=tenant_id,
        plan_code="pro",
        success_url="https://app.example.test/a",
        cancel_url="https://app.example.test/b",
        environment="sandbox",
        seller_account="org_sandbox",
    )
    changed = CheckoutService.fingerprint(
        tenant_id=tenant_id,
        plan_code="pro",
        success_url="https://app.example.test/a",
        cancel_url="https://app.example.test/other",
        environment="sandbox",
        seller_account="org_sandbox",
    )
    assert left == right
    assert left != changed
    assert str(tenant_id) in left
    assert "org_sandbox" in left
