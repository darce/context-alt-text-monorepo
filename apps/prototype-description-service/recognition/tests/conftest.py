"""Pytest fixtures shared across recognition tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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


@pytest.fixture(scope="session", autouse=True)
def configure_thumbnail_storage(tmp_path_factory):
    """Store generated thumbnails in a disposable directory during tests."""

    tmp_dir = tmp_path_factory.mktemp("thumbnails")
    prev_dir = os.environ.get("THUMBNAIL_DIR")
    prev_base = os.environ.get("THUMBNAIL_BASE_URL")
    os.environ["THUMBNAIL_DIR"] = str(tmp_dir)
    os.environ["THUMBNAIL_BASE_URL"] = "/test-thumbnails"
    yield
    if prev_dir is not None:
        os.environ["THUMBNAIL_DIR"] = prev_dir
    else:
        os.environ.pop("THUMBNAIL_DIR", None)
    if prev_base is not None:
        os.environ["THUMBNAIL_BASE_URL"] = prev_base
    else:
        os.environ.pop("THUMBNAIL_BASE_URL", None)
