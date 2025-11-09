"""SQLAlchemy engine and session helpers for roster storage."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_default_engine(database_url: str, *, echo: bool) -> Engine:
    """Create a default SQLAlchemy engine."""
    return create_engine(database_url, echo=echo, future=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    """Create the sessionmaker used by storage adapters."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope(
    session_factory: sessionmaker,
    configure_fn: Optional[Callable[[Session], None]] = None,
) -> Session:
    """Context manager that yields a configured SQLAlchemy session."""
    session: Session = session_factory()
    try:
        if configure_fn is not None:
            configure_fn(session)
        yield session
    finally:
        session.close()
