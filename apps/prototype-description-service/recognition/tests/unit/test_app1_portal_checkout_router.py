"""HTTP contract tests for POST /portal/billing/checkout and /manage."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.portal_billing import BillingCheckoutAttempt, BillingSubscriptionProjection, CheckoutAttemptStatus
from db.models.tenant import Tenant
from recognition.application.services.checkout_service import CheckoutService
from recognition.domain.portal_contracts import CheckoutSession, PortalPrincipal
from recognition.infrastructure.billing.polar_provider import CheckoutAmbiguityError
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository
from recognition.interface_adapters.http.deps.portal_auth import PortalAuthSettings, require_portal_principal
from recognition.interface_adapters.http.deps.portal_composition import (
    BillingRepositoryFactory,
    CheckoutServiceFactory,
    PortalCompositionConfig,
)
from recognition.interface_adapters.http.routers import portal

ALLOWED_ORIGIN = "https://app.altcontext.com"
PUBLIC_ORIGIN = "https://app.altcontext.com"
ISSUER = "https://issuer.example.test"
SUBJECT = "subject-1"
EMAIL = "owner@example.test"
PLAN_CODE = "starter_monthly"
SELLER_ACCOUNT = "org_sandbox"
IDEM_KEY = "client-idempotency-key:" + ("a" * 41)


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

    async def rollback(self) -> None:
        self.events.append("rollback")
        self._session.rollback()

    async def close(self) -> None:
        self.events.append("close")
        self._session.close()


class FakeBillingProvider:
    """In-process Polar stand-in: records kwargs and never opens a network socket."""

    def __init__(self, *, error: BaseException | None = None, portal_url: str = "https://polar.test/portal") -> None:
        self.checkout_calls: list[dict[str, object]] = []
        self.portal_calls: list[dict[str, object]] = []
        self.customer_calls: list[object] = []
        self.subscription_calls: list[object] = []
        self.error = error
        self.payments_enabled = True
        self.portal_url = portal_url

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
        self.checkout_calls.append(
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
        return CheckoutSession(url=f"https://pay.example.test/{attempt_id}", provider_checkout_id=f"chk-{attempt_id}")

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        self.portal_calls.append({"tenant_id": tenant_id, "return_url": return_url})
        if self.error is not None:
            raise self.error
        return self.portal_url

    async def create_customer(self, **kwargs: object) -> None:
        self.customer_calls.append(kwargs)
        raise AssertionError("manage/checkout must not create customers")

    async def create_subscription(self, **kwargs: object) -> None:
        self.subscription_calls.append(kwargs)
        raise AssertionError("manage/checkout must not create subscriptions")


def _engine_session() -> tuple[object, _AsyncSessionFacade]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            BillingCheckoutAttempt.__table__,
            BillingSubscriptionProjection.__table__,
        ]
        Base.metadata.create_all(connection, tables=tables)
    return engine, _AsyncSessionFacade(Session(engine, expire_on_commit=False))


def _add_tenant(session: _AsyncSessionFacade, suffix: str) -> Tenant:
    tenant = Tenant(site_url=f"https://portal-co-{suffix}.example.test")
    session.add(tenant)
    session._session.flush()
    return tenant


def _principal(tenant_id: UUID) -> PortalPrincipal:
    return PortalPrincipal(tenant_id=tenant_id, issuer=ISSUER, subject=SUBJECT, email=EMAIL)


def _config(*, payments_enabled: bool, seller_account: str | None = SELLER_ACCOUNT) -> PortalCompositionConfig:
    return PortalCompositionConfig(
        portal_auth=PortalAuthSettings(
            issuer=ISSUER,
            jwks_url="https://issuer.example.test/.well-known/jwks.json",
            audience="aud",
            authorized_parties=(ALLOWED_ORIGIN,),
        ),
        billing_webhook_secret="whsec_test",
        billing_product_ids={PLAN_CODE: "prod_starter"},
        billing_payments_enabled=payments_enabled,
        billing_environment="sandbox",
        billing_allowed_return_origins=(PUBLIC_ORIGIN,),
        billing_seller_account=seller_account,
        app_public_origin=PUBLIC_ORIGIN,
        app_allowed_origins=(ALLOWED_ORIGIN,),
    )


def _app(
    session: _AsyncSessionFacade,
    principal: PortalPrincipal,
    provider: FakeBillingProvider,
    *,
    config: PortalCompositionConfig | None = None,
    install_factory: bool = True,
) -> FastAPI:
    application = FastAPI()
    application.include_router(portal.router)
    resolved = config or _config(payments_enabled=True)
    application.state.portal_composition_config = resolved
    application.state.app_allowed_origins = resolved.app_allowed_origins
    application.state.billing_provider = provider
    application.state.billing_repository = BillingRepositoryFactory()
    if install_factory and resolved.billing_seller_account:
        application.state.checkout_service = CheckoutServiceFactory(
            provider=provider,
            seller_account=resolved.billing_seller_account,
            payments_enabled=resolved.billing_payments_enabled,
            provider_name="fake",
            environment=resolved.billing_environment,
        )

    async def override_principal() -> PortalPrincipal:
        return principal

    async def override_session() -> Iterator[_AsyncSessionFacade]:
        yield session

    application.dependency_overrides[require_portal_principal] = override_principal
    application.dependency_overrides[portal.get_portal_session] = override_session
    return application


def _headers(*, origin: str | None = ALLOWED_ORIGIN, idempotency: str | None = IDEM_KEY) -> dict[str, str]:
    headers = {"Authorization": "Bearer token"}
    if origin is not None:
        headers["Origin"] = origin
    if idempotency is not None:
        headers["Idempotency-Key"] = idempotency
    return headers


def _post_checkout(
    client: TestClient,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    return client.post(
        "/portal/billing/checkout",
        json={"plan_code": PLAN_CODE} if body is None else body,
        headers=_headers() if headers is None else headers,
        params=params,
    )


def _post_manage(
    client: TestClient,
    *,
    body: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    request_headers = _headers(idempotency=None)
    if headers:
        request_headers.update(headers)
        if "Idempotency-Key" not in headers:
            request_headers.pop("Idempotency-Key", None)
    return client.post("/portal/billing/manage", json={} if body is None else body, headers=request_headers)


def _code(response: Any) -> str | None:
    payload = response.json().get("detail")
    if isinstance(payload, dict):
        code = payload.get("code")
        return str(code) if code is not None else None
    return None


@pytest.fixture
def harness() -> Iterator[tuple[_AsyncSessionFacade, Tenant, FakeBillingProvider, FastAPI]]:
    engine, session = _engine_session()
    tenant = _add_tenant(session, "one")
    provider = FakeBillingProvider()
    application = _app(session, _principal(tenant.id), provider)
    try:
        yield session, tenant, provider, application
    finally:
        engine.dispose()


def test_checkout_service_factory_binds_the_request_session_not_a_global() -> None:
    engine, session = _engine_session()
    other_engine, other_session = _engine_session()
    try:
        provider = FakeBillingProvider()
        factory = CheckoutServiceFactory(
            provider=provider,
            seller_account=SELLER_ACCOUNT,
            payments_enabled=True,
            provider_name="fake",
            environment="sandbox",
        )
        first = factory(session)
        second = factory(other_session)
        assert isinstance(first, CheckoutService)
        assert isinstance(first._repository, CheckoutAttemptRepository)
        assert first._repository.session is session
        assert second._repository.session is other_session
        assert first._repository.session is not second._repository.session
        assert first._seller_account == SELLER_ACCOUNT
        assert first._provider is provider
    finally:
        engine.dispose()
        other_engine.dispose()


def test_first_checkout_persists_before_provider_and_returns_pending(harness: tuple) -> None:
    session, tenant, provider, application = harness

    with TestClient(application) as client:
        response = _post_checkout(client)

    assert response.status_code == 200
    payload = response.json()
    assert payload["replayed"] is False
    assert payload["status"] == CheckoutAttemptStatus.PENDING.value
    assert payload["checkout_url"] == f"https://pay.example.test/{payload['attempt_id']}"
    assert response.headers["cache-control"] == "no-store"
    assert provider.checkout_calls[0]["tenant_id"] == tenant.id
    assert provider.checkout_calls[0]["plan_code"] == PLAN_CODE
    assert provider.checkout_calls[0]["success_url"] == f"{PUBLIC_ORIGIN}/billing/return"
    assert provider.checkout_calls[0]["cancel_url"] == f"{PUBLIC_ORIGIN}/billing/cancel"
    assert session.events[0] == "commit"
    assert session.events.index("commit") == 0
    assert provider.customer_calls == []
    assert provider.subscription_calls == []


def test_idempotent_replay_does_not_call_provider_again(harness: tuple) -> None:
    _session, _tenant, provider, application = harness

    with TestClient(application) as client:
        first = _post_checkout(client)
        second = _post_checkout(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["attempt_id"] == first.json()["attempt_id"]
    assert second.json()["checkout_url"] == first.json()["checkout_url"]
    assert len(provider.checkout_calls) == 1


def test_succeeded_replay_does_not_grant_entitlement(harness: tuple) -> None:
    session, tenant, provider, application = harness

    with TestClient(application) as client:
        created = _post_checkout(client)
        attempt_id = UUID(created.json()["attempt_id"])
        row = session._session.get(BillingCheckoutAttempt, attempt_id)
        assert row is not None
        row.status = CheckoutAttemptStatus.SUCCEEDED.value
        session._session.commit()
        replay = _post_checkout(client)

    assert replay.status_code == 200
    assert replay.json() == {
        "attempt_id": str(attempt_id),
        "checkout_url": None,
        "status": CheckoutAttemptStatus.SUCCEEDED.value,
        "replayed": True,
    }
    assert len(provider.checkout_calls) == 1
    assert provider.customer_calls == []
    assert provider.subscription_calls == []


def test_payments_disabled_is_403_before_provider_or_persist() -> None:
    engine, session = _engine_session()
    tenant = _add_tenant(session, "off")
    provider = FakeBillingProvider()
    application = _app(
        session,
        _principal(tenant.id),
        provider,
        config=_config(payments_enabled=False),
    )
    try:
        with TestClient(application) as client:
            response = _post_checkout(client)
        assert response.status_code == 403
        assert _code(response) == "payments_disabled"
        assert provider.checkout_calls == []
        assert session.events == []
    finally:
        engine.dispose()


def test_unconfigured_mode_is_403_without_provider_calls() -> None:
    engine, session = _engine_session()
    tenant = _add_tenant(session, "none")
    provider = FakeBillingProvider()
    application = FastAPI()
    application.include_router(portal.router)
    application.state.billing_provider = provider
    application.state.app_allowed_origins = (ALLOWED_ORIGIN,)

    async def override_principal() -> PortalPrincipal:
        return _principal(tenant.id)

    async def override_session() -> Iterator[_AsyncSessionFacade]:
        yield session

    application.dependency_overrides[require_portal_principal] = override_principal
    application.dependency_overrides[portal.get_portal_session] = override_session
    try:
        with TestClient(application) as client:
            response = _post_checkout(client)
        assert response.status_code == 403
        assert _code(response) == "payments_disabled"
        assert provider.checkout_calls == []
    finally:
        engine.dispose()


def test_missing_and_mismatched_origin_are_csrf_denied(harness: tuple) -> None:
    _session, _tenant, provider, application = harness

    with TestClient(application) as client:
        missing = _post_checkout(client, headers=_headers(origin=""))
        referer_only = client.post(
            "/portal/billing/checkout",
            json={"plan_code": PLAN_CODE},
            headers={"Authorization": "Bearer token", "Referer": ALLOWED_ORIGIN, "Idempotency-Key": IDEM_KEY},
        )
        mismatched = _post_checkout(client, headers=_headers(origin="https://evil.example"))

    assert missing.status_code == 403
    assert _code(missing) == "csrf_origin_denied"
    assert referer_only.status_code == 403
    assert _code(referer_only) == "csrf_origin_denied"
    assert mismatched.status_code == 403
    assert _code(mismatched) == "csrf_origin_denied"
    assert provider.checkout_calls == []


def test_tenant_selection_and_vendor_fields_are_rejected(harness: tuple) -> None:
    _session, _tenant, provider, application = harness
    foreign = str(uuid4())

    with TestClient(application) as client:
        body_tenant = _post_checkout(client, body={"plan_code": PLAN_CODE, "tenant_id": foreign})
        query_tenant = _post_checkout(client, params={"tenant_id": foreign})
        extra = _post_checkout(
            client,
            body={
                "plan_code": PLAN_CODE,
                "product_id": "prod_client",
                "success_url": "https://evil.example/ok",
            },
        )

    assert body_tenant.status_code == 403
    assert _code(body_tenant) == "tenant_header_forbidden"
    assert query_tenant.status_code == 403
    assert _code(query_tenant) == "tenant_header_forbidden"
    assert extra.status_code == 422
    assert provider.checkout_calls == []


def test_unknown_plan_and_malformed_return_path_are_422(harness: tuple) -> None:
    _session, _tenant, provider, application = harness

    with TestClient(application) as client:
        unknown = _post_checkout(client, body={"plan_code": "enterprise_yearly"})
        scheme = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "https://evil.example/x"})
        slash = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "/billing//return"})
        dots = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "/billing/../secret"})
        backslash = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "/billing\\return"})

    assert unknown.status_code == 422
    assert _code(unknown) == "unknown_plan_code"
    for response in (scheme, slash, dots, backslash):
        assert response.status_code == 422
        assert _code(response) == "invalid_return_path"
    assert provider.checkout_calls == []


def test_foreign_tenant_does_not_replay_another_tenant_attempt() -> None:
    engine, session = _engine_session()
    tenant_a = _add_tenant(session, "a")
    tenant_b = _add_tenant(session, "b")
    provider = FakeBillingProvider()
    app_a = _app(session, _principal(tenant_a.id), provider)
    app_b = _app(session, _principal(tenant_b.id), provider)
    try:
        with TestClient(app_a) as client_a:
            first = _post_checkout(client_a)
        with TestClient(app_b) as client_b:
            isolated = _post_checkout(client_b)
        assert first.status_code == 200
        assert isolated.status_code == 200
        assert isolated.json()["attempt_id"] != first.json()["attempt_id"]
        assert isolated.json()["replayed"] is False
        assert {call["tenant_id"] for call in provider.checkout_calls} == {tenant_a.id, tenant_b.id}
    finally:
        engine.dispose()


def test_fresh_ambiguity_is_503_retry_after_1_and_existing_is_409(harness: tuple) -> None:
    _session, _tenant, provider, application = harness
    provider.error = CheckoutAmbiguityError("timeout after persist")

    with TestClient(application, raise_server_exceptions=False) as client:
        fresh = _post_checkout(client)
        retry = _post_checkout(client)

    assert fresh.status_code == 503
    assert _code(fresh) == "checkout_ambiguous"
    assert fresh.headers.get("retry-after") == "1"
    assert UUID(fresh.json()["detail"]["attempt_id"])
    assert retry.status_code == 409
    assert _code(retry) == "checkout_ambiguous"
    assert retry.json()["detail"]["attempt_id"] == fresh.json()["detail"]["attempt_id"]
    assert len(provider.checkout_calls) == 1


def test_fingerprint_mismatch_is_422_idempotency_key_reuse(harness: tuple) -> None:
    _session, _tenant, provider, application = harness

    with TestClient(application) as client:
        first = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "/billing/return"})
        mismatch = _post_checkout(client, body={"plan_code": PLAN_CODE, "return_path": "/billing/other"})

    assert first.status_code == 200
    assert mismatch.status_code == 422
    assert _code(mismatch) == "idempotency_key_reuse"
    assert len(provider.checkout_calls) == 1


def test_manage_requires_mapping_then_calls_create_portal_session(harness: tuple) -> None:
    session, tenant, provider, application = harness
    session.add(
        BillingSubscriptionProjection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus_mapped",
            status="active",
        )
    )
    session._session.commit()

    with TestClient(application) as client:
        missing_app_engine, missing_session = _engine_session()
        missing_tenant = _add_tenant(missing_session, "nomap")
        missing_provider = FakeBillingProvider()
        missing_app = _app(missing_session, _principal(missing_tenant.id), missing_provider)
        with TestClient(missing_app) as missing_client:
            missing = _post_manage(missing_client)
        mapped = _post_manage(client, body={"return_path": "/billing"})

    assert missing.status_code == 409
    assert _code(missing) == "billing_customer_missing"
    assert missing_provider.portal_calls == []
    assert missing_provider.customer_calls == []
    assert mapped.status_code == 200
    assert mapped.json() == {"portal_url": "https://polar.test/portal"}
    assert mapped.headers["cache-control"] == "no-store"
    assert provider.portal_calls == [{"tenant_id": tenant.id, "return_url": f"{PUBLIC_ORIGIN}/billing"}]
    assert provider.customer_calls == []
    assert provider.subscription_calls == []
    missing_app_engine.dispose()


def test_manage_payments_disabled_and_origin_and_extra_fields() -> None:
    engine, session = _engine_session()
    tenant = _add_tenant(session, "manage-off")
    session.add(
        BillingSubscriptionProjection(
            tenant_id=tenant.id,
            provider="polar",
            provider_customer_id="cus_mapped",
            status="active",
        )
    )
    session._session.commit()
    provider = FakeBillingProvider()
    disabled = _app(session, _principal(tenant.id), provider, config=_config(payments_enabled=False))
    enabled = _app(session, _principal(tenant.id), provider)
    try:
        with TestClient(disabled) as client:
            off = _post_manage(client)
        with TestClient(enabled) as client:
            csrf = _post_manage(client, headers={"Origin": "https://evil.example"})
            extra = _post_manage(client, body={"return_path": "/billing", "customer_id": "cus_client"})
            tenant_body = _post_manage(client, body={"tenant_id": str(uuid4())})
        assert off.status_code == 403
        assert _code(off) == "payments_disabled"
        assert csrf.status_code == 403
        assert _code(csrf) == "csrf_origin_denied"
        assert extra.status_code == 422
        assert tenant_body.status_code == 403
        assert _code(tenant_body) == "tenant_header_forbidden"
        assert provider.portal_calls == []
        assert provider.customer_calls == []
    finally:
        engine.dispose()
