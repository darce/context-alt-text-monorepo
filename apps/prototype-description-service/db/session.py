"""Async SQLAlchemy session helpers."""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.settings import get_database_settings

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
    """Provide a scoped async SQLAlchemy session."""

    async with async_session_factory() as session:
        yield session


__all__ = ["engine", "get_session", "async_session_factory"]
