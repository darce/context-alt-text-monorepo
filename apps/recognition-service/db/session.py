"""Session and engine helpers for the recognition service database layer."""

from __future__ import annotations

from typing import Dict

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_ENGINE_CACHE: Dict[str, Engine] = {}


def create_engine_from_url(url: str, *, echo: bool = False) -> Engine:
    """Return a cached SQLAlchemy engine for the provided database URL."""

    if url not in _ENGINE_CACHE:
        _ENGINE_CACHE[url] = create_engine(url, echo=echo, future=True)
    return _ENGINE_CACHE[url]


def get_session_maker(url: str, *, echo: bool = False) -> sessionmaker[Session]:
    """Create a sessionmaker bound to the cached engine for the URL."""

    engine = create_engine_from_url(url, echo=echo)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_session(url: str, *, echo: bool = False) -> Session:
    """Convenience helper that returns a new Session instance."""

    factory = get_session_maker(url, echo=echo)
    return factory()
