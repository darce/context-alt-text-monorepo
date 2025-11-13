"""Database configuration helpers for the prototype description service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_ASYNC_DSN = "postgresql+asyncpg://context:context@localhost:5432/context_alt_text"
DEFAULT_SYNC_DSN = "postgresql+psycopg://context:context@localhost:5432/context_alt_text"


@dataclass(frozen=True)
class DatabaseSettings:
    """Settings container for database connectivity and pgvector config."""

    postgres_dsn: str
    postgres_sync_dsn: str
    pgvector_dimension: int


def _infer_sync_dsn(async_dsn: str) -> str:
    """Best-effort conversion from asyncpg URL to psycopg-compatible URL."""

    if "+asyncpg" in async_dsn:
        return async_dsn.replace("+asyncpg", "+psycopg", 1)
    if "+psycopg" in async_dsn:
        return async_dsn
    if async_dsn.startswith("postgresql://"):
        return async_dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    return DEFAULT_SYNC_DSN


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Load settings from environment variables with sensible defaults."""

    async_dsn = os.getenv("POSTGRES_DSN", DEFAULT_ASYNC_DSN)
    sync_dsn = os.getenv("POSTGRES_SYNC_DSN") or _infer_sync_dsn(async_dsn)
    pgvector_dim = int(os.getenv("PGVECTOR_DIM", "1024"))

    return DatabaseSettings(
        postgres_dsn=async_dsn,
        postgres_sync_dsn=sync_dsn,
        pgvector_dimension=pgvector_dim,
    )


__all__ = ["DatabaseSettings", "get_database_settings", "DEFAULT_ASYNC_DSN", "DEFAULT_SYNC_DSN"]
