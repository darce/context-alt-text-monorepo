"""Tenant context helpers for row-level security enforcement."""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator
from uuid import UUID

from asyncpg.exceptions import InFailedSQLTransactionError
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import engine


def _is_sqlite(session: AsyncSession) -> bool:
    """Check if the session is using SQLite (no RLS support)."""
    bind = getattr(session, "bind", None)
    if bind is None:
        return False
    dialect = getattr(bind, "dialect", None)
    if dialect is None:
        return False
    return getattr(dialect, "name", "") == "sqlite"


async def ensure_tenant_exists(session: AsyncSession, tenant_id: UUID, site_url: str | None = None) -> None:
    """Create tenant record if it doesn't exist (first-use auto-provisioning).

    Args:
        session: Database session
        tenant_id: UUID of the tenant to ensure exists
        site_url: Optional site URL; defaults to placeholder if not provided

    This enables "just-in-time" tenant creation for new WordPress installations
    that haven't been explicitly registered. The tenant is created with minimal
    metadata that can be updated later via admin endpoints.
    """
    from db.models import Tenant  # Import here to avoid circular dependency

    # Check if tenant exists
    result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
    existing = result.scalar_one_or_none()

    if existing is None:
        # Auto-provision with placeholder site_url
        placeholder_url = site_url or f"auto-provisioned-{str(tenant_id)[:8]}"
        tenant = Tenant(id=tenant_id, site_url=placeholder_url)
        session.add(tenant)
        await session.flush()


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Set app.current_tenant for the current session/transaction."""
    # SQLite doesn't support RLS or session variables - skip for test environments
    if _is_sqlite(session):
        return

    tenant_value = str(tenant_id).replace("'", "''")
    try:
        await session.execute(text("RESET app.bypass_rls"))
        await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_value}'"))
    except DBAPIError as e:
        # Only rollback if transaction is actually aborted
        if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
            await session.rollback()
            await session.execute(text("RESET app.bypass_rls"))
            await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_value}'"))
        else:
            raise
    if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "1":
        try:
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        except DBAPIError as e:
            # Only rollback if transaction is actually aborted
            if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
                await session.rollback()
                await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
            else:
                raise


async def clear_tenant_context(session: AsyncSession) -> None:
    """Reset the tenant context so pooled connections don't leak state.

    Note: We do NOT rollback here - the caller is responsible for managing
    the transaction (commit or rollback). We only reset the session-level
    RLS variables.
    """
    # SQLite doesn't support RLS or session variables - skip for test environments
    if _is_sqlite(session):
        return
    with contextlib.suppress(Exception):
        await session.execute(text("RESET app.current_tenant"))
        await session.execute(text("RESET app.bypass_rls"))


async def enable_rls_bypass(session: AsyncSession) -> None:
    """Temporarily disable RLS policies for maintenance operations."""
    # SQLite doesn't support RLS - skip for test environments
    if _is_sqlite(session):
        return

    try:
        await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
    except DBAPIError as e:
        # Only rollback if transaction is actually aborted
        if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
            await session.rollback()
            await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
        else:
            raise


async def disable_rls_bypass(session: AsyncSession) -> None:
    """Reset RLS bypass flag."""
    # SQLite doesn't support RLS - skip for test environments
    if _is_sqlite(session):
        return

    try:
        await session.execute(text("RESET app.bypass_rls"))
    except DBAPIError as e:
        # Only rollback if transaction is actually aborted
        if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
            await session.rollback()
            await session.execute(text("RESET app.bypass_rls"))
        else:
            raise


async def get_tenant_aware_session(session: AsyncSession, tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Dependency that yields a session with tenant context set."""
    await set_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        await clear_tenant_context(session)


def _register_checkout_listener() -> None:  # pragma: no cover
    """Register pool checkout listener - only for production, not tests."""

    @event.listens_for(engine.sync_engine, "checkout")
    def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("RESET app.current_tenant")
        cursor.execute("RESET app.bypass_rls")
        cursor.close()


# Only register the listener if not in test mode (avoids asyncpg engine init during tests)
if os.getenv("PYTEST_CURRENT_TEST") is None:
    _register_checkout_listener()
