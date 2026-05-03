"""Database configuration helpers for the prototype description service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

DEFAULT_PGUSER = "context"
DEFAULT_PGPASSWORD = "context"
DEFAULT_PGHOST = "localhost"
DEFAULT_PGPORT = "5432"
DEFAULT_DB_NAME = "alt_context_service"
LOCAL_ENV_MODES = frozenset({"local", "development"})
LEGACY_LOCAL_DB_NAMES = frozenset({"context_alt_text_service"})

DEFAULT_ASYNC_DSN_TEMPLATE = "postgresql+asyncpg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{DB_NAME}"
DEFAULT_SYNC_DSN_TEMPLATE = "postgresql+psycopg://{PGUSER}:{PGPASSWORD}@{PGHOST}:{PGPORT}/{DB_NAME}"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


@dataclass(frozen=True)
class DatabaseSettings:
    """Settings container for database connectivity, pool config, and pgvector config."""

    postgres_dsn: str
    postgres_sync_dsn: str
    pgvector_dimension: int
    embedding_timeout_s: float
    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    observability_pool_size: int
    observability_max_overflow: int
    observability_pool_timeout: int
    statement_timeout: str
    idle_in_txn_timeout: str
    breaker_failure_threshold: int
    breaker_window_seconds: int
    breaker_half_open_after_seconds: int
    disable_stmt_cache: bool
    # E15-3a-BR-21 Slice 2: narrow per-statement timeout applied around the
    # clustering handler's tenants SELECT ... FOR UPDATE so a zombie
    # idle-in-transaction row lock fails in ~<1 s instead of riding the global
    # 10 s statement_timeout cliff. retry_after tells the caller how long to
    # back off on admission fail-fast responses (503 Retry-After).
    clustering_tenant_lock_timeout_ms: int
    clustering_admission_retry_after_seconds: int
    # E15-3a-BR-21 Slice 3: clustering-dedicated circuit breaker counts
    # QueryCanceledError on the clustering write path. Separate state from the
    # SLR-3 session-dependency breaker -- see task plan PLAN-09.
    clustering_breaker_failure_threshold: int
    clustering_breaker_window_seconds: float
    clustering_breaker_cooldown_seconds: float
    # E15-3a-BR-21 Slice 4: dedicated clustering pool so contention on
    # SELECT ... FOR UPDATE of tenants cannot back up the business pool or the
    # observability pool. Sized narrow on purpose -- saturating this pool
    # triggers fast 503s instead of blocking unrelated traffic.
    clustering_pool_size: int
    clustering_max_overflow: int
    clustering_pool_timeout: int


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
        resolved_value = os.path.expandvars(value.strip())
        if key == "DB_NAME":
            resolved_value, warning = canonicalize_local_db_name(
                resolved_value,
                env_mode=os.environ.get("ENV_MODE", "local"),
            )
            if warning:
                print(warning)
        os.environ[key] = resolved_value


def _resolved_db_name() -> str:
    """Return the canonical local DB name for settings-driven DSN rendering."""

    resolved_name, warning = canonicalize_local_db_name(
        os.getenv("DB_NAME", DEFAULT_DB_NAME),
        env_mode=os.getenv("ENV_MODE", "local"),
    )
    if warning:
        print(warning)
    return resolved_name or DEFAULT_DB_NAME


def _render_default_async_dsn() -> str:
    """Build an asyncpg DSN from PG* env vars (or their defaults)."""

    return DEFAULT_ASYNC_DSN_TEMPLATE.format(
        PGUSER=os.getenv("PGUSER", DEFAULT_PGUSER),
        PGPASSWORD=os.getenv("PGPASSWORD", DEFAULT_PGPASSWORD),
        PGHOST=os.getenv("PGHOST", DEFAULT_PGHOST),
        PGPORT=os.getenv("PGPORT", DEFAULT_PGPORT),
        DB_NAME=_resolved_db_name(),
    )


def _render_default_sync_dsn() -> str:
    """Build a psycopg DSN from PG* env vars (or their defaults)."""

    return DEFAULT_SYNC_DSN_TEMPLATE.format(
        PGUSER=os.getenv("PGUSER", DEFAULT_PGUSER),
        PGPASSWORD=os.getenv("PGPASSWORD", DEFAULT_PGPASSWORD),
        PGHOST=os.getenv("PGHOST", DEFAULT_PGHOST),
        PGPORT=os.getenv("PGPORT", DEFAULT_PGPORT),
        DB_NAME=_resolved_db_name(),
    )


def _disable_asyncpg_statement_cache(async_dsn: str) -> str:
    """Append the asyncpg prepared statement cache toggle to the DSN."""

    parsed = urlparse(async_dsn)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["prepared_statement_cache_size"] = "0"
    return urlunparse(parsed._replace(query=urlencode(query)))


def canonicalize_local_db_name(
    db_name: str | None,
    *,
    env_mode: str | None,
) -> tuple[str | None, str | None]:
    """Map legacy local DB names to the canonical one for local startup/reset flows."""

    normalized_mode = (env_mode or "").strip().lower()
    if normalized_mode not in LOCAL_ENV_MODES or db_name not in LEGACY_LOCAL_DB_NAMES:
        return db_name, None

    return (
        DEFAULT_DB_NAME,
        (
            f"[prototype-local] DB_NAME={db_name} is legacy for local development; "
            f"using {DEFAULT_DB_NAME} instead. Update apps/prototype-description-service/.env "
            "to keep reset/start flows aligned."
        ),
    )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Load settings from environment variables with sensible defaults."""

    _load_env_file()
    async_dsn = os.getenv("POSTGRES_DSN") or _render_default_async_dsn()
    sync_dsn = os.getenv("POSTGRES_SYNC_DSN") or _infer_sync_dsn(async_dsn)
    pgvector_dim = int(os.getenv("PGVECTOR_DIM", "512"))
    embedding_timeout_s = float(os.getenv("DB_EMBEDDING_TIMEOUT_SECONDS", "30"))
    pool_size = int(os.getenv("DB_POOL_SIZE", "20"))
    max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    pool_timeout = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "3600"))
    observability_pool_size = int(os.getenv("DB_OBSERVABILITY_POOL_SIZE", "2"))
    observability_max_overflow = int(os.getenv("DB_OBSERVABILITY_MAX_OVERFLOW", "0"))
    observability_pool_timeout = int(os.getenv("DB_OBSERVABILITY_POOL_TIMEOUT", "5"))
    statement_timeout = os.getenv("DB_STATEMENT_TIMEOUT", "10s")
    idle_in_txn_timeout = os.getenv("DB_IDLE_IN_TXN_TIMEOUT", "30s")
    breaker_failure_threshold = int(os.getenv("DB_BREAKER_FAILURE_THRESHOLD", "3"))
    breaker_window_seconds = int(os.getenv("DB_BREAKER_WINDOW_SECONDS", "30"))
    breaker_half_open_after_seconds = int(os.getenv("DB_BREAKER_HALF_OPEN_AFTER_SECONDS", "10"))
    disable_stmt_cache = os.getenv("DB_DISABLE_STMT_CACHE", "0") == "1"
    clustering_tenant_lock_timeout_ms = int(os.getenv("DB_CLUSTERING_TENANT_LOCK_TIMEOUT_MS", "1000"))
    clustering_admission_retry_after_seconds = int(os.getenv("DB_CLUSTERING_ADMISSION_RETRY_AFTER_SECONDS", "5"))
    clustering_breaker_failure_threshold = int(os.getenv("DB_CLUSTERING_BREAKER_FAILURE_THRESHOLD", "3"))
    clustering_breaker_window_seconds = float(os.getenv("DB_CLUSTERING_BREAKER_WINDOW_SECONDS", "30"))
    clustering_breaker_cooldown_seconds = float(os.getenv("DB_CLUSTERING_BREAKER_COOLDOWN_SECONDS", "30"))
    clustering_pool_size = int(os.getenv("DB_CLUSTERING_POOL_SIZE", "2"))
    clustering_max_overflow = int(os.getenv("DB_CLUSTERING_MAX_OVERFLOW", "1"))
    clustering_pool_timeout = int(os.getenv("DB_CLUSTERING_POOL_TIMEOUT", "5"))

    if disable_stmt_cache and "+asyncpg" in async_dsn:
        async_dsn = _disable_asyncpg_statement_cache(async_dsn)

    return DatabaseSettings(
        postgres_dsn=async_dsn,
        postgres_sync_dsn=sync_dsn,
        pgvector_dimension=pgvector_dim,
        embedding_timeout_s=embedding_timeout_s,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        observability_pool_size=observability_pool_size,
        observability_max_overflow=observability_max_overflow,
        observability_pool_timeout=observability_pool_timeout,
        statement_timeout=statement_timeout,
        idle_in_txn_timeout=idle_in_txn_timeout,
        breaker_failure_threshold=breaker_failure_threshold,
        breaker_window_seconds=breaker_window_seconds,
        breaker_half_open_after_seconds=breaker_half_open_after_seconds,
        disable_stmt_cache=disable_stmt_cache,
        clustering_tenant_lock_timeout_ms=clustering_tenant_lock_timeout_ms,
        clustering_admission_retry_after_seconds=clustering_admission_retry_after_seconds,
        clustering_breaker_failure_threshold=clustering_breaker_failure_threshold,
        clustering_breaker_window_seconds=clustering_breaker_window_seconds,
        clustering_breaker_cooldown_seconds=clustering_breaker_cooldown_seconds,
        clustering_pool_size=clustering_pool_size,
        clustering_max_overflow=clustering_max_overflow,
        clustering_pool_timeout=clustering_pool_timeout,
    )


__all__ = [
    "DatabaseSettings",
    "get_database_settings",
    "canonicalize_local_db_name",
    "DEFAULT_ASYNC_DSN_TEMPLATE",
    "DEFAULT_SYNC_DSN_TEMPLATE",
]
