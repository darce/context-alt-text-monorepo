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
    raise NotImplementedError("TODO: implement get_pool_stats")


__all__ = ["engine", "get_session", "async_session_factory", "get_pool_stats"]
