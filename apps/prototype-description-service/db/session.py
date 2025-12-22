"""Async SQLAlchemy session helpers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.settings import get_database_settings

logger = logging.getLogger(__name__)

_settings = get_database_settings()

engine: AsyncEngine = create_async_engine(
    _settings.postgres_dsn,
    echo=False,
    pool_pre_ping=True,
    pool_size=_settings.pool_size,
    max_overflow=_settings.max_overflow,
    pool_timeout=_settings.pool_timeout,
    pool_recycle=_settings.pool_recycle,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Provide a scoped async SQLAlchemy session.

    The caller is responsible for committing the transaction.
    The session will be closed after the caller yields back.
    """
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


def get_pool_stats() -> dict[str, int | float]:
    """Return current connection pool statistics.

    Returns:
        Dictionary with pool metrics.
    """
    pool = engine.pool
    size = int(pool.size())
    max_overflow = int(getattr(pool, "_max_overflow", _settings.max_overflow))
    checked_out = int(pool.checkedout())
    checked_in = max(0, size - checked_out)
    overflow_count = max(0, checked_out - size)
    total_capacity = size + max_overflow
    utilization = (checked_out / total_capacity * 100) if total_capacity > 0 else 0.0

    return {
        "size": size,
        "overflow": max_overflow,
        "checked_out": checked_out,
        "checked_in": checked_in,
        "overflow_count": overflow_count,
        "total_capacity": total_capacity,
        "utilization_percent": round(utilization, 2),
    }


__all__ = ["engine", "get_session", "async_session_factory", "get_pool_stats"]
