"""Postgres proof for checkout-attempt schema upgrade and tenant isolation.

Skipped when Postgres is not available. Do not treat a skip as live-database
evidence.
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models.tenant import Tenant
from recognition.infrastructure.repositories.checkout_attempt_repository import (
    CheckoutAttemptRepository,
)

pytestmark = pytest.mark.pg

MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


def _async_url(engine) -> str:
    return (
        engine.url.render_as_string(hide_password=False)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _begin_kwargs(tenant_id, **overrides: object) -> dict[str, object]:
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
async def test_postgres_heal_and_rls_isolate_checkout_attempts(
    pg_empty_engine,
) -> None:
    with pg_empty_engine.begin() as conn:
        MIGRATION.heal(conn)

    inspector = inspect(pg_empty_engine)
    assert "billing_checkout_attempt" in inspector.get_table_names()
    indexes = {index["name"]: index for index in inspector.get_indexes("billing_checkout_attempt")}
    assert indexes["uq_billing_checkout_attempt_client_key"]["unique"] is True
    assert indexes["uq_billing_checkout_attempt_one_active"]["unique"] is True
    with pg_empty_engine.connect() as conn:
        flags = conn.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'billing_checkout_attempt'"
            )
        ).one()
    assert flags == (True, True)

    engine = create_async_engine(_async_url(pg_empty_engine), pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            tenant_a = Tenant(site_url="https://checkout-a.example.test")
            tenant_b = Tenant(site_url="https://checkout-b.example.test")
            session.add_all([tenant_a, tenant_b])
            await session.flush()
            repo = CheckoutAttemptRepository(session)
            created = await repo.begin_attempt(**_begin_kwargs(tenant_a.id))
            isolated = await repo.begin_attempt(**_begin_kwargs(tenant_b.id, request_fingerprint="fp-tenant-b"))
            await session.commit()
            assert isolated.attempt.id != created.attempt.id
            assert await repo.get_attempt(tenant_b.id, created.attempt.id) is None
    finally:
        await engine.dispose()
