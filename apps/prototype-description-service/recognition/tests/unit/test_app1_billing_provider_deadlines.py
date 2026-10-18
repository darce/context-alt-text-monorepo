"""Caller-enforced deadlines for billing provider operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request, Response
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from db.base import Base
from db.models.portal_billing import (
    BillingCheckoutAttempt,
    CheckoutAttemptErrorClass,
    CheckoutAttemptStatus,
)
from db.models.tenant import Tenant
from recognition.application.services import checkout_service
from recognition.application.services.checkout_service import CheckoutAmbiguousError, CheckoutService
from recognition.domain.portal_contracts import PortalPrincipal
from recognition.infrastructure.repositories.checkout_attempt_repository import CheckoutAttemptRepository
from recognition.interface_adapters.http.routers import portal

_ALLOWED_ORIGIN = "https://app.altcontext.com"
_PUBLIC_ORIGIN = "https://app.altcontext.com"


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


class _HangingCheckoutProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.never_resolve = asyncio.Event()

    async def create_checkout_session(self, **kwargs: object) -> object:
        self.started.set()
        await self.never_resolve.wait()
        raise AssertionError("the test provider event is never set")


@pytest.mark.asyncio
async def test_checkout_provider_deadline_records_recoverable_ambiguous_attempt(
    checkout_session: _AsyncSessionFacade,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(checkout_service, "_BILLING_PROVIDER_TIMEOUT_S", 0.01, raising=False)
    tenant = Tenant(site_url="https://billing-deadline.example.test")
    checkout_session.add(tenant)
    await checkout_session.flush()

    provider = _HangingCheckoutProvider()
    service = CheckoutService(
        CheckoutAttemptRepository(checkout_session),
        provider,  # type: ignore[arg-type]
        payments_enabled=True,
        provider_name="fake",
        environment="sandbox",
        seller_account="org_sandbox",
        idempotency_key_factory=lambda: "provider-key-1",
    )

    with pytest.raises(CheckoutAmbiguousError) as exc_info:
        await asyncio.wait_for(
            service.create_checkout(
                tenant_id=tenant.id,
                plan_code="pro",
                success_url="https://app.altcontext.com/billing/return",
                cancel_url="https://app.altcontext.com/billing/cancel",
                client_idempotency_key="client-key-1",
            ),
            timeout=0.5,
        )

    assert provider.started.is_set()
    row = checkout_session._session.get(BillingCheckoutAttempt, exc_info.value.attempt_id)
    assert row is not None
    assert row.status == CheckoutAttemptStatus.AMBIGUOUS.value
    assert row.last_error_class == CheckoutAttemptErrorClass.AMBIGUOUS.value


class _HangingPortalProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.never_resolve = asyncio.Event()

    async def create_portal_session(self, *, tenant_id: UUID, return_url: str) -> str:
        self.started.set()
        await self.never_resolve.wait()
        raise AssertionError("the test provider event is never set")


class _MappedBillingRepository:
    async def get_projection(self, tenant_id: UUID) -> object:
        return SimpleNamespace(provider_customer_id="cus_mapped")


def _manage_request(app: FastAPI) -> Request:
    body = b"{}"
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope: dict[str, object] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/portal/billing/manage",
        "raw_path": b"/portal/billing/manage",
        "query_string": b"",
        "headers": [(b"origin", _ALLOWED_ORIGIN.encode()), (b"host", b"app.altcontext.com")],
        "client": ("testclient", 50000),
        "server": ("app.altcontext.com", 443),
        "app": app,
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_manage_provider_deadline_maps_to_billing_portal_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portal, "_BILLING_PROVIDER_TIMEOUT_S", 0.01, raising=False)
    app = FastAPI()
    app.state.app_allowed_origins = (_ALLOWED_ORIGIN,)
    app.state.portal_composition_config = SimpleNamespace(
        billing_payments_enabled=True,
        app_public_origin=_PUBLIC_ORIGIN,
        billing_allowed_return_origins=(_PUBLIC_ORIGIN,),
    )
    provider = _HangingPortalProvider()
    app.state.billing_provider = provider
    principal = PortalPrincipal(
        tenant_id=uuid4(),
        issuer="https://issuer.example.test",
        subject="subject-1",
        email="owner@example.test",
    )

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(
            portal.portal_billing_manage(
                _manage_request(app),
                Response(),
                principal,
                _MappedBillingRepository(),  # type: ignore[arg-type]
            ),
            timeout=0.5,
        )

    assert provider.started.is_set()
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"code": "billing_portal_unavailable"}
