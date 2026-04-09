"""
Database session management dependencies for recognition HTTP API.

This module provides FastAPI dependencies for database session lifecycle.
"""

from __future__ import annotations

import logging
import re
import time as _time
import uuid
from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi.exceptions import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.settings import get_database_settings
from db.session import async_session_factory
from db.tenant_context import set_tenant_context
from recognition.interface_adapters.http.deps.tenant_common import get_tenant_id_optional
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)
_db_settings = get_database_settings()
_TIMEOUT_PATTERN = re.compile(r"^\d+(?:ms|s|min|h|d)?$")


def _validated_timeout_setting(raw_value: str, *, setting_name: str) -> str:
    """Reject malformed timeout values before interpolating them into SET LOCAL."""
    if not _TIMEOUT_PATTERN.fullmatch(raw_value):
        raise ValueError(
            f"{setting_name} must match <integer><optional unit>; got {raw_value!r}"
        )
    return raw_value


async def _apply_postgres_session_safety_settings(session: AsyncSession) -> None:
    """Apply per-transaction safety settings on PostgreSQL sessions only."""
    if not is_postgres(session):
        return
    statement_timeout = _validated_timeout_setting(
        _db_settings.statement_timeout,
        setting_name="DB_STATEMENT_TIMEOUT",
    )
    idle_in_txn_timeout = _validated_timeout_setting(
        _db_settings.idle_in_txn_timeout,
        setting_name="DB_IDLE_IN_TXN_TIMEOUT",
    )
    await session.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout}'"))
    await session.execute(text(f"SET LOCAL idle_in_transaction_session_timeout = '{idle_in_txn_timeout}'"))


async def _resolve_connection_id(session: AsyncSession) -> str | None:
    """Best-effort connection identity for dependency timing logs."""
    connection = getattr(session, "connection", None)
    if not callable(connection):
        return None
    try:
        async_connection = await connection()
    except Exception:
        return None
    sync_connection = getattr(async_connection, "sync_connection", None)
    if sync_connection is not None:
        return hex(id(sync_connection))
    return hex(id(async_connection))


def _log_session_dependency_timing(
    dependency_name: str,
    *,
    started_at: float,
    available: bool,
    tenant_id: str | None,
    probe_ms: float | None = None,
    tenant_context_ms: float | None = None,
    conn_id: str | None = None,
) -> None:
    """Emit structured timing for session dependencies to support later latency aggregation."""
    logger.info(
        "session_dependency_timing dependency=%s available=%s tenant_id=%s total_ms=%.2f probe_ms=%s tenant_context_ms=%s conn_id=%s",
        dependency_name,
        available,
        tenant_id or "",
        (_time.perf_counter() - started_at) * 1000,
        f"{probe_ms:.2f}" if probe_ms is not None else "n/a",
        f"{tenant_context_ms:.2f}" if tenant_context_ms is not None else "n/a",
        conn_id or "n/a",
    )


async def get_session(tenant_id: str | None = Depends(get_tenant_id_optional)) -> AsyncIterator[AsyncSession]:
    """Yield a SQLAlchemy async session; set tenant context when provided."""
    started_at = _time.perf_counter()
    session = async_session_factory()
    tenant_context_ms: float | None = None
    conn_id: str | None = None
    try:
        await _apply_postgres_session_safety_settings(session)
        if tenant_id:
            tenant_context_started_at = _time.perf_counter()
            await set_tenant_context(session, uuid.UUID(str(tenant_id)))
            tenant_context_ms = (_time.perf_counter() - tenant_context_started_at) * 1000
        conn_id = await _resolve_connection_id(session)
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        _log_session_dependency_timing(
            "get_session",
            started_at=started_at,
            available=True,
            tenant_id=tenant_id,
            tenant_context_ms=tenant_context_ms,
            conn_id=conn_id,
        )
        await session.close()


async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    """Best-effort session provider; returns None when the database is unavailable."""
    started_at = _time.perf_counter()
    session = async_session_factory()
    probe_ms: float | None = None
    tenant_context_ms: float | None = None
    session_available = False
    conn_id: str | None = None
    try:
        try:
            probe_started_at = _time.perf_counter()
            await session.execute(text("SELECT 1"))
            probe_ms = (_time.perf_counter() - probe_started_at) * 1000
            await _apply_postgres_session_safety_settings(session)
            if tenant_id:
                tenant_context_started_at = _time.perf_counter()
                await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                tenant_context_ms = (_time.perf_counter() - tenant_context_started_at) * 1000
            conn_id = await _resolve_connection_id(session)
        except ValueError:
            raise
        except Exception:
            yield None
            return
        session_available = True
        try:
            yield session
            await session.commit()
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("get_optional_session: exception during yield/commit: %s", exc)
            await session.rollback()
            raise
    finally:
        _log_session_dependency_timing(
            "get_optional_session",
            started_at=started_at,
            available=session_available,
            tenant_id=tenant_id,
            probe_ms=probe_ms,
            tenant_context_ms=tenant_context_ms,
            conn_id=conn_id,
        )
        await session.close()


async def get_observability_session() -> AsyncIterator[AsyncSession | None]:
    """Session provider without tenant validation for diagnostics."""
    started_at = _time.perf_counter()
    session = async_session_factory()
    probe_ms: float | None = None
    session_available = False
    conn_id: str | None = None
    try:
        try:
            probe_started_at = _time.perf_counter()
            await session.execute(text("SELECT 1"))
            probe_ms = (_time.perf_counter() - probe_started_at) * 1000
            await _apply_postgres_session_safety_settings(session)
            conn_id = await _resolve_connection_id(session)
        except ValueError:
            raise
        except Exception:
            yield None
            return
        session_available = True
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    finally:
        _log_session_dependency_timing(
            "get_observability_session",
            started_at=started_at,
            available=session_available,
            tenant_id=None,
            probe_ms=probe_ms,
            conn_id=conn_id,
        )
        await session.close()


__all__ = [
    "get_session",
    "get_optional_session",
    "get_observability_session",
]
