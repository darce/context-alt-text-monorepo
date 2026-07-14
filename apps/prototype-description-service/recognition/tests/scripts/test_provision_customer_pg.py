"""Postgres-backed guard for AP-7 concierge provisioning (review LOW finding).

The SQLite unit substrate no-ops RLS (``enable_rls_bypass`` / ``set_tenant_context``
early-return on sqlite), so the load-bearing behavior added by the fix commit —
the CLI bypassing RLS so the RLS-forced ``audit_events`` INSERT lands — is
invisible there. A regression that drops the bypass would pass the sqlite tests.
These ``-m pg`` tests exercise the real policy: with bypass the audit row lands;
without it the provision is rejected, proving the bypass is required.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.tenant_context import enable_rls_bypass
from recognition.application.services.customer_provision_service import provision_customer

pytestmark = pytest.mark.pg


def _async_sessionmaker(pg_migrated_engine):
    async_url = str(pg_migrated_engine.url).replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_provision_writes_audit_under_rls_bypass(pg_migrated_engine) -> None:
    engine, session_factory = _async_sessionmaker(pg_migrated_engine)
    try:
        async with session_factory() as session:
            await enable_rls_bypass(session)
            result = await provision_customer(session, email="pg-guard@example.com", plan="pro", label="PG Guard")
        assert result.status == "created"
        assert result.raw_key is not None

        async with session_factory() as session:
            await enable_rls_bypass(session)  # audit_events is RLS-forced; bypass to read
            count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_events WHERE tenant_id = :t AND event_type = 'customer.provision'"
                    ),
                    {"t": result.tenant_id},
                )
            ).scalar_one()
        assert count == 1, "audit row must land under the RLS bypass the CLI sets"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_provision_without_bypass_is_rejected_by_rls(pg_migrated_engine) -> None:
    engine, session_factory = _async_sessionmaker(pg_migrated_engine)
    try:
        async with session_factory() as session:
            # No enable_rls_bypass: the RLS-forced audit_events INSERT (no tenant
            # context set) must fail — this is the bug the fix commit closed.
            with pytest.raises(Exception):
                await provision_customer(session, email="pg-noguard@example.com", plan="pro")
    finally:
        await engine.dispose()
