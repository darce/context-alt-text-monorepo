"""Session and engine helpers for PostgreSQL adapters."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool


def create_engine_with_pool(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
    echo: bool,
) -> Engine:
    """Create a SQLAlchemy engine configured for the roster service."""
    return create_engine(
        database_url,
        echo=echo,
        future=True,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_pre_ping=True,
    )


def verify_pgvector_extension(engine: Engine, logger: logging.Logger, *, minimum_version: Optional[str] = None) -> None:
    """Verify pgvector extension is installed (and optionally meets minimum version)."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"))
            row = result.fetchone()

            if row is None:
                raise RuntimeError(
                    "pgvector extension not found in database. "
                    "Please install pgvector extension (0.8.1+ required for HNSW support). "
                    "See db/SETUP.md for installation instructions."
                )

            version = row[1]
            if minimum_version and version < minimum_version:
                raise RuntimeError(
                    f"pgvector {minimum_version}+ required for this service. Found version {version}."
                )

            logger.info("✅ pgvector extension verified (version %s)", version)
    except SQLAlchemyError as exc:  # pragma: no cover - defensive logging
        logger.error("Failed to verify pgvector extension: %s", exc)
        raise RuntimeError(
            "Could not verify pgvector extension. "
            "Database connection may be misconfigured or extension may be missing. "
            "See db/SETUP.md for setup instructions."
        ) from exc
