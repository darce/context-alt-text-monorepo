"""Behavioral tests for tenant-scoped checkout attempt persistence."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import Table, UniqueConstraint, create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import recognition.infrastructure.repositories.checkout_attempt_repository as checkout_module
from db.base import Base
from db.models.portal_billing import BillingCheckoutAttempt, CheckoutAttemptStatus
from db.models.tenant import Tenant
from recognition.infrastructure.repositories.checkout_attempt_repository import (
    CheckoutAttemptActiveConflictError,
    CheckoutAttemptFingerprintConflictError,
    CheckoutAttemptRepository,
)


class _Result:
    def __init__(self, row: object | None = None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object | None:
        return self._row


class _SpySession:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def execute(self, _statement: object) -> _Result:
        self.events.append("execute")
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
async def checkout_session() -> AsyncGenerator[_AsyncSessionFacade, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        tables: list[Table] = [
            Table("tenants", Base.metadata),
            BillingCheckoutAttempt.__table__,
        ]
        Base.metadata.create_all(connection, tables=tables)

    session = _AsyncSessionFacade(Session(engine, expire_on_commit=False))
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


async def _create_tenant(session: _AsyncSessionFacade, suffix: str) -> Tenant:
    tenant = Tenant(site_url=f"https://checkout-{suffix}.example.test")
    session.add(tenant)
    await session.flush()
    return tenant


def _begin_kwargs(tenant_id: UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenant_id": tenant_id,
        "provider": "fake",
        "environment": "sandbox",
        "seller_account": "org_sandbox",
        "plan_code": "pro",
        "idempotency_key": "provider-key-1",
        "client_idempotency_key": "client-key-1",
        "request_fingerprint": "fp-tenant-plan-urls",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_begin_attempt_persists_tenant_scoped_fields(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "persist")
    repo = CheckoutAttemptRepository(checkout_session)

    result = await repo.begin_attempt(**_begin_kwargs(tenant.id))

    assert result.replayed is False
    row = result.attempt
    assert row.tenant_id == tenant.id
    assert row.provider == "fake"
    assert row.environment == "sandbox"
    assert row.seller_account == "org_sandbox"
    assert row.plan_code == "pro"
    assert row.idempotency_key == "provider-key-1"
    assert row.client_idempotency_key == "client-key-1"
    assert row.request_fingerprint == "fp-tenant-plan-urls"
    assert row.status == CheckoutAttemptStatus.CREATED.value
    assert row.provider_checkout_id is None
    assert row.checkout_url is None
    assert row.last_error_class == "none"
    loaded = await repo.get_attempt(tenant.id, row.id)
    assert loaded is not None
    assert loaded.id == row.id


@pytest.mark.asyncio
async def test_same_tenant_key_and_fingerprint_replays(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "replay")
    repo = CheckoutAttemptRepository(checkout_session)
    first = await repo.begin_attempt(**_begin_kwargs(tenant.id))
    await repo.record_provider_checkout(
        tenant.id,
        first.attempt.id,
        provider_checkout_id="chk_123",
        checkout_url="https://pay.example/chk_123",
    )

    second = await repo.begin_attempt(**_begin_kwargs(tenant.id, idempotency_key="provider-key-ignored"))

    assert second.replayed is True
    assert second.attempt.id == first.attempt.id
    assert second.attempt.checkout_url == "https://pay.example/chk_123"
    assert second.attempt.idempotency_key == "provider-key-1"


@pytest.mark.asyncio
async def test_fingerprint_mismatch_raises_typed_conflict(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "mismatch")
    repo = CheckoutAttemptRepository(checkout_session)
    await repo.begin_attempt(**_begin_kwargs(tenant.id))

    with pytest.raises(CheckoutAttemptFingerprintConflictError):
        await repo.begin_attempt(**_begin_kwargs(tenant.id, request_fingerprint="fp-different-urls"))


@pytest.mark.asyncio
async def test_foreign_tenant_cannot_see_or_collide_on_same_client_key(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant_a = await _create_tenant(checkout_session, "iso-a")
    tenant_b = await _create_tenant(checkout_session, "iso-b")
    repo = CheckoutAttemptRepository(checkout_session)
    created = await repo.begin_attempt(**_begin_kwargs(tenant_a.id))

    isolated = await repo.begin_attempt(
        **_begin_kwargs(
            tenant_b.id,
            idempotency_key="provider-key-tenant-b",
            request_fingerprint="fp-tenant-b",
        )
    )

    assert isolated.replayed is False
    assert isolated.attempt.id != created.attempt.id
    assert isolated.attempt.tenant_id == tenant_b.id
    assert await repo.get_attempt(tenant_b.id, created.attempt.id) is None
    assert await repo.get_attempt(tenant_a.id, isolated.attempt.id) is None


@pytest.mark.asyncio
async def test_one_active_attempt_per_tenant_namespace_is_atomic(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "active")
    repo = CheckoutAttemptRepository(checkout_session)
    await repo.begin_attempt(**_begin_kwargs(tenant.id))

    with pytest.raises(CheckoutAttemptActiveConflictError):
        await repo.begin_attempt(
            **_begin_kwargs(
                tenant.id,
                client_idempotency_key="client-key-2",
                idempotency_key="provider-key-2",
                request_fingerprint="fp-second-purchase",
            )
        )


@pytest.mark.asyncio
async def test_only_one_active_attempt_per_tenant_namespace_across_plans(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "cross-plan-active")
    repo = CheckoutAttemptRepository(checkout_session)
    await repo.begin_attempt(**_begin_kwargs(tenant.id))

    with pytest.raises(CheckoutAttemptActiveConflictError):
        await repo.begin_attempt(
            **_begin_kwargs(
                tenant.id,
                plan_code="enterprise",
                idempotency_key="provider-key-enterprise",
                client_idempotency_key="client-key-enterprise",
                request_fingerprint="fp-enterprise",
            )
        )


@pytest.mark.asyncio
async def test_terminal_purchase_requires_new_provider_key(
    checkout_session: _AsyncSessionFacade,
) -> None:
    tenant = await _create_tenant(checkout_session, "terminal")
    repo = CheckoutAttemptRepository(checkout_session)
    first = await repo.begin_attempt(**_begin_kwargs(tenant.id))
    expired = await repo.mark_terminal(
        tenant.id,
        first.attempt.id,
        status=CheckoutAttemptStatus.EXPIRED,
        last_error_class="expired",
    )
    assert expired.status == CheckoutAttemptStatus.EXPIRED.value

    with pytest.raises(Exception):
        await repo.begin_attempt(
            **_begin_kwargs(
                tenant.id,
                client_idempotency_key="client-key-2",
                request_fingerprint="fp-second-purchase",
            )
        )

    second = await repo.begin_attempt(
        **_begin_kwargs(
            tenant.id,
            client_idempotency_key="client-key-2",
            idempotency_key="provider-key-2",
            request_fingerprint="fp-second-purchase",
        )
    )
    assert second.replayed is False
    assert second.attempt.id != first.attempt.id
    assert second.attempt.idempotency_key == "provider-key-2"
    assert second.attempt.status == CheckoutAttemptStatus.CREATED.value


@pytest.mark.asyncio
async def test_begin_attempt_sets_and_clears_tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SpySession()
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")
    events: list[tuple[str, UUID | None]] = []

    async def set_context(_session: object, value: UUID) -> None:
        events.append(("set", value))

    async def clear_context(_session: object) -> None:
        events.append(("clear", None))

    monkeypatch.setattr(checkout_module, "set_tenant_context", set_context)
    monkeypatch.setattr(checkout_module, "clear_tenant_context", clear_context)
    monkeypatch.setattr(checkout_module, "_is_sqlite_session", lambda _session: False)

    class _LookupRepo(CheckoutAttemptRepository):
        async def _get_by_client_key(self, **_kwargs: object) -> None:  # type: ignore[override]
            return None

    repo = _LookupRepo(session)
    with pytest.raises(Exception):
        await repo.begin_attempt(**_begin_kwargs(tenant_id))

    assert events[0] == ("set", tenant_id)
    assert events[-1] == ("clear", None)


def test_checkout_uniques_distinguish_tenant_scoped_client_key_from_seller_wide_provider_key() -> None:
    unique_column_sets: dict[str, tuple[str, ...]] = {}
    for constraint in BillingCheckoutAttempt.__table__.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None:
            unique_column_sets[constraint.name] = tuple(column.name for column in constraint.columns)
    for index in BillingCheckoutAttempt.__table__.indexes:
        if index.unique and index.name is not None:
            unique_column_sets[index.name] = tuple(column.name for column in index.columns)

    provider_key = unique_column_sets["uq_billing_checkout_attempt_provider_key"]
    assert provider_key == ("provider", "environment", "seller_account", "idempotency_key")
    assert "tenant_id" not in provider_key

    client_key = unique_column_sets["uq_billing_checkout_attempt_client_key"]
    assert client_key[0] == "tenant_id"
    assert "client_idempotency_key" in client_key
    assert "idempotency_key" not in client_key

    active = unique_column_sets["uq_billing_checkout_attempt_one_active"]
    assert active == ("tenant_id", "provider", "environment", "seller_account")


def test_migration_authority_registers_checkout_attempt_upgrade() -> None:
    import importlib

    migration = importlib.import_module("db.migrations.versions.001_identity_schema")
    assert "billing_checkout_attempt" in migration.TENANT_TABLES
    assert "billing_checkout_attempt" in migration.EXPECTED_SCHEMA_TABLES
    assert "billing_checkout_attempt" in migration.DOWNGRADE_TABLE_ORDER
    assert any(
        table == "billing_checkout_attempt" and name == "uq_billing_checkout_attempt_provider_key"
        for table, name, _columns in migration.HEAL_UNIQUE_CONSTRAINTS
    )


@pytest.mark.asyncio
async def test_sqlite_schema_creates_partial_unique_indexes(checkout_session: _AsyncSessionFacade) -> None:
    inspector = inspect(checkout_session.bind)
    indexes = {index["name"]: index for index in inspector.get_indexes("billing_checkout_attempt")}
    assert indexes["uq_billing_checkout_attempt_one_active"]["unique"]
    assert indexes["uq_billing_checkout_attempt_client_key"]["unique"]
