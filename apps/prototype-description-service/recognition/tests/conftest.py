"""Pytest fixtures shared across recognition tests."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from api.main import create_app
from db.session import async_session_factory


@pytest_asyncio.fixture()
async def async_client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(scope="session")
def event_loop():
    """Use a shared event loop so asyncpg connections stay bound to one loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    with env_path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@pytest_asyncio.fixture()
async def require_database() -> AsyncIterator[None]:
    _load_env()
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (OperationalError, SQLAlchemyError) as exc:
        pytest.skip(f"Database unreachable: {exc}")
    yield
