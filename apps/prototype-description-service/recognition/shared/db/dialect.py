"""Dialect helpers for SQLAlchemy sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement


def _dialect_name(session: AsyncSession) -> str:
    bind = getattr(session, "bind", None)
    dialect = getattr(bind, "dialect", None) if bind else None
    return getattr(dialect, "name", "") if dialect else ""


def is_sqlite(session: AsyncSession) -> bool:
    """Return True when session is backed by SQLite."""
    return _dialect_name(session) == "sqlite"


def is_postgres(session: AsyncSession) -> bool:
    """Return True when session is backed by PostgreSQL."""
    return _dialect_name(session).startswith("postgres")


def timestamp_as_epoch(
    col: ColumnElement[datetime] | ColumnElement[datetime | None] | InstrumentedAttribute[datetime | None],
    session: AsyncSession,
) -> ColumnElement[int]:
    """Convert a datetime column to epoch seconds, dialect-aware."""
    if is_sqlite(session):
        return func.cast(func.strftime("%s", col), Integer)
    return func.extract("epoch", col).cast(Integer)
