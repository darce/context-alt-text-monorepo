"""
Database session management dependencies for recognition HTTP API.

This module provides FastAPI dependencies for database session lifecycle.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session as _get_session
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.interface_adapters.http.deps.tenant import get_tenant_id_optional

logger = logging.getLogger(__name__)


async def get_session(tenant_id: str | None = Depends(get_tenant_id_optional)) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session; set tenant context when provided."""
    async with aclosing(_get_session()) as session_iter:
        async for session in session_iter:
            try:
                if tenant_id:
                    await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                yield session
                commit = getattr(session, "commit", None)
                if callable(commit):
                    await commit()
            except Exception:
                rollback = getattr(session, "rollback", None)
                if callable(rollback):
                    await rollback()
                raise
            finally:
                if tenant_id:
                    await clear_tenant_context(session)


async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    """Best-effort session provider; returns None when the database is unavailable."""
    async with aclosing(_get_session()) as session_iter:
        async for session in session_iter:
            try:
                try:
                    await session.execute(text("SELECT 1"))
                    if tenant_id:
                        await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                except Exception:
                    yield None
                    return
                try:
                    yield session
                    commit = getattr(session, "commit", None)
                    if callable(commit):
                        await commit()
                except Exception as exc:
                    logger.error("get_optional_session: exception during yield/commit: %s", exc)
                    rollback = getattr(session, "rollback", None)
                    if callable(rollback):
                        await rollback()
                    raise
            finally:
                if tenant_id:
                    await clear_tenant_context(session)


async def get_observability_session() -> AsyncIterator[AsyncSession | None]:
    """Session provider without tenant validation for diagnostics."""
    async with aclosing(_get_session()) as session_iter:
        async for session in session_iter:
            try:
                await session.execute(text("SELECT 1"))
            except Exception:
                yield None
                return
            try:
                yield session
                commit = getattr(session, "commit", None)
                if callable(commit):
                    await commit()
            except Exception:
                rollback = getattr(session, "rollback", None)
                if callable(rollback):
                    await rollback()
                raise
            return


__all__ = [
    "get_session",
    "get_optional_session",
    "get_observability_session",
]
