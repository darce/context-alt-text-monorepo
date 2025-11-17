"""Tenant context helpers for row-level security enforcement."""

from __future__ import annotations

from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session_factory, engine


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Set app.current_tenant for the current session/transaction."""
    tenant_value = str(tenant_id).replace("'", "''")
    # asyncpg rejects placeholders in SET LOCAL, so interpolate a literal UUID.
    await session.execute(
        text(f"SET LOCAL app.current_tenant = '{tenant_value}'")
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """Reset the tenant context so pooled connections don’t leak state."""
    await session.execute(text("RESET app.current_tenant"))


async def get_tenant_aware_session(
    session: AsyncSession, tenant_id: UUID
) -> AsyncIterator[AsyncSession]:
    """Dependency that yields a session with tenant context set."""
    await set_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        await clear_tenant_context(session)


@event.listens_for(engine.sync_engine, "checkout")
def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy) -> None:  # pragma: no cover
    cursor = dbapi_conn.cursor()
    cursor.execute("RESET app.current_tenant")
    cursor.close()
