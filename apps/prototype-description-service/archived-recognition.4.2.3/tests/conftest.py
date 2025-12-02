"""Pytest fixtures shared across recognition tests."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from api.main import create_app
from db.session import async_session_factory


def _load_env() -> None:
    """Load .env file early so test skip conditions can check the values."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


# Load .env file before anything else
_load_env()


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


@pytest_asyncio.fixture()
async def require_database() -> AsyncIterator[None]:
    _load_env()  # Ensure .env is loaded (idempotent)
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (OperationalError, SQLAlchemyError, ProgrammingError, PermissionError, OSError) as exc:
        pytest.skip(f"Database unreachable: {exc}")
    yield


@pytest_asyncio.fixture(autouse=True)
async def cleanup_test_data() -> AsyncIterator[None]:
    """Clean up test data after each test to prevent cross-test contamination."""
    yield  # Run the test first

    # Only cleanup if RLS is enforced (bypass disabled)
    if os.getenv("ALLOW_RLS_BYPASS_FOR_TESTS") == "0":
        try:
            async with async_session_factory() as session:
                # Use TRUNCATE CASCADE to remove all test data
                # This is safe because we're using the test database
                await session.execute(text("TRUNCATE TABLE identity_cluster_representatives CASCADE"))
                await session.execute(text("TRUNCATE TABLE identity_members CASCADE"))
                await session.execute(text("TRUNCATE TABLE identity_clusters CASCADE"))
                await session.execute(text("TRUNCATE TABLE media_identities CASCADE"))
                await session.execute(text("TRUNCATE TABLE identity_scan_jobs CASCADE"))
                await session.execute(text("TRUNCATE TABLE tenants CASCADE"))
                await session.commit()
        except Exception:
            # Ignore cleanup errors - they shouldn't fail the test
            pass


@pytest.fixture(scope="session", autouse=True)
def configure_thumbnail_storage(tmp_path_factory):
    """Store generated thumbnails in a disposable directory during tests."""

    tmp_dir = tmp_path_factory.mktemp("thumbnails")
    prev_dir = os.environ.get("THUMBNAIL_DIR")
    # ALLOW_RLS_BYPASS_FOR_TESTS is already set from .env or default above
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
