"""
Database session management dependencies for recognition HTTP API.

This module provides FastAPI dependencies for database session lifecycle.
"""

from __future__ import annotations

import logging
import time as _time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import cast

from fastapi import Depends
from fastapi.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session as _get_session
from db.tenant_context import clear_tenant_context, set_tenant_context
from recognition.interface_adapters.http.deps.tenant_common import get_tenant_id_optional

logger = logging.getLogger(__name__)


def _log_session_dependency_timing(
    dependency_name: str,
    *,
    started_at: float,
    available: bool,
    tenant_id: str | None,
    probe_ms: float | None = None,
    tenant_context_ms: float | None = None,
) -> None:
    """Emit structured timing for session dependencies to support later latency aggregation."""
    logger.info(
        "session_dependency_timing dependency=%s available=%s tenant_id=%s total_ms=%.2f probe_ms=%s tenant_context_ms=%s",
        dependency_name,
        available,
        tenant_id or "",
        (_time.perf_counter() - started_at) * 1000,
        f"{probe_ms:.2f}" if probe_ms is not None else "n/a",
        f"{tenant_context_ms:.2f}" if tenant_context_ms is not None else "n/a",
    )


async def get_session(tenant_id: str | None = Depends(get_tenant_id_optional)) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session; set tenant context when provided."""
    started_at = _time.perf_counter()
    session_iter = cast(AsyncGenerator[AsyncSession, None], _get_session())
    try:
        async for session in session_iter:
            tenant_context_ms: float | None = None
            try:
                if tenant_id:
                    tenant_context_started_at = _time.perf_counter()
                    await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                    tenant_context_ms = (_time.perf_counter() - tenant_context_started_at) * 1000
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
                _log_session_dependency_timing(
                    "get_session",
                    started_at=started_at,
                    available=True,
                    tenant_id=tenant_id,
                    tenant_context_ms=tenant_context_ms,
                )
                if tenant_id:
                    await clear_tenant_context(session)
    finally:
        await session_iter.aclose()


async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    """Best-effort session provider; returns None when the database is unavailable."""
    started_at = _time.perf_counter()
    session_iter = cast(AsyncGenerator[AsyncSession, None], _get_session())
    try:
        async for session in session_iter:
            probe_ms: float | None = None
            tenant_context_ms: float | None = None
            session_available = False
            try:
                try:
                    probe_started_at = _time.perf_counter()
                    await session.execute(text("SELECT 1"))
                    probe_ms = (_time.perf_counter() - probe_started_at) * 1000
                    if tenant_id:
                        tenant_context_started_at = _time.perf_counter()
                        await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                        tenant_context_ms = (_time.perf_counter() - tenant_context_started_at) * 1000
                except Exception:
                    yield None
                    return
                session_available = True
                try:
                    yield session
                    commit = getattr(session, "commit", None)
                    if callable(commit):
                        await commit()
                except HTTPException:
                    raise
                except Exception as exc:
                    logger.error("get_optional_session: exception during yield/commit: %s", exc)
                    rollback = getattr(session, "rollback", None)
                    if callable(rollback):
                        await rollback()
                    raise
            finally:
                _log_session_dependency_timing(
                    "get_optional_session",
                    started_at=started_at,
                    available=session_available,
                    tenant_id=tenant_id,
                    probe_ms=probe_ms,
                    tenant_context_ms=tenant_context_ms,
                )
                if tenant_id:
                    await clear_tenant_context(session)
    finally:
        await session_iter.aclose()


async def get_observability_session() -> AsyncIterator[AsyncSession | None]:
    """Session provider without tenant validation for diagnostics."""
    started_at = _time.perf_counter()
    session_iter = cast(AsyncGenerator[AsyncSession, None], _get_session())
    try:
        async for session in session_iter:
            probe_ms: float | None = None
            try:
                probe_started_at = _time.perf_counter()
                await session.execute(text("SELECT 1"))
                probe_ms = (_time.perf_counter() - probe_started_at) * 1000
            except Exception:
                _log_session_dependency_timing(
                    "get_observability_session",
                    started_at=started_at,
                    available=False,
                    tenant_id=None,
                    probe_ms=probe_ms,
                )
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
            _log_session_dependency_timing(
                "get_observability_session",
                started_at=started_at,
                available=True,
                tenant_id=None,
                probe_ms=probe_ms,
            )
            return
    finally:
        await session_iter.aclose()


__all__ = [
    "get_session",
    "get_optional_session",
    "get_observability_session",
]
