"""Database configuration helpers for the prototype description service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_PGUSER = "context"
DEFAULT_PGPASSWORD = "context"
DEFAULT_PGHOST = "localhost"
DEFAULT_PGPORT = "5432"
DEFAULT_DB_NAME = "context_alt_text"

DEFAULT_ASYNC_DSN_TEMPLATE = "postgresql+asyncpg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{DB_NAME}"
DEFAULT_SYNC_DSN_TEMPLATE = "postgresql+psycopg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{DB_NAME}"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


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
    return _render_default_sync_dsn()


def _load_env_file() -> None:
    """
    Load .env defaults before resolving DSNs so pytest and Alembic pick up local config.

    Values already present in the environment take precedence. Variable references
    like ${PGUSER} are expanded using the progressively built environment.
    """

    if not ENV_FILE.exists():
        return

    for raw_line in ENV_FILE.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = os.path.expandvars(value.strip())


def _render_default_async_dsn() -> str:
    """Build an asyncpg DSN from PG* env vars (or their defaults)."""

    return DEFAULT_ASYNC_DSN_TEMPLATE.format(
        PGUSER=os.getenv("PGUSER", DEFAULT_PGUSER),
        PGPASSWORD=os.getenv("PGPASSWORD", DEFAULT_PGPASSWORD),
        PGHOST=os.getenv("PGHOST", DEFAULT_PGHOST),
        PGPORT=os.getenv("PGPORT", DEFAULT_PGPORT),
        DB_NAME=os.getenv("DB_NAME", DEFAULT_DB_NAME),
    )


def _render_default_sync_dsn() -> str:
    """Build a psycopg DSN from PG* env vars (or their defaults)."""

    return DEFAULT_SYNC_DSN_TEMPLATE.format(
        PGUSER=os.getenv("PGUSER", DEFAULT_PGUSER),
        PGPASSWORD=os.getenv("PGPASSWORD", DEFAULT_PGPASSWORD),
        PGHOST=os.getenv("PGHOST", DEFAULT_PGHOST),
        PGPORT=os.getenv("PGPORT", DEFAULT_PGPORT),
        DB_NAME=os.getenv("DB_NAME", DEFAULT_DB_NAME),
    )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Load settings from environment variables with sensible defaults."""

    _load_env_file()
    async_dsn = os.getenv("POSTGRES_DSN") or _render_default_async_dsn()
    sync_dsn = os.getenv("POSTGRES_SYNC_DSN") or _infer_sync_dsn(async_dsn)
    pgvector_dim = int(os.getenv("PGVECTOR_DIM", "1024"))

    return DatabaseSettings(
        postgres_dsn=async_dsn,
        postgres_sync_dsn=sync_dsn,
        pgvector_dimension=pgvector_dim,
    )


__all__ = [
    "DatabaseSettings",
    "get_database_settings",
    "DEFAULT_ASYNC_DSN_TEMPLATE",
    "DEFAULT_SYNC_DSN_TEMPLATE",
]
