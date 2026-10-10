"""Enforced PostgreSQL RLS gate; a missing URL is explicitly unverified.

Use GTMBURST_POSTGRES_TEST_URL (or POSTGRES_TEST_URL / IDENTITY_PG_TEST_URL)
with a non-superuser, non-BYPASSRLS role allowed to create an isolated schema.
The policy expressions come from the production migration. SQLite and a
superuser connection cannot certify this gate.
"""

from __future__ import annotations

import importlib
import json
import os
import uuid
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models import Tenant
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.tenant_context import set_tenant_context
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.interface_adapters.http.deps import get_async_gpu_description_adapter, get_description_adapter
from scene.interface_adapters.http.routers import describe as route
from scene.tests.test_gtmburst_async_enqueue import IMAGE, TENANT, Admission, gate

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]
MIGRATION = importlib.import_module("db.migrations.versions.001_identity_schema")


@pytest_asyncio.fixture
async def restricted_pg_factory(monkeypatch):
    url = next(
        (
            os.environ[key]
            for key in ("GTMBURST_POSTGRES_TEST_URL", "POSTGRES_TEST_URL", "IDENTITY_PG_TEST_URL")
            if os.environ.get(key)
        ),
        None,
    )
    if not url:
        pytest.skip("BLOCKED: restricted PostgreSQL RLS fixture URL is not configured")
    url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    monkeypatch.delenv("ALLOW_RLS_BYPASS_FOR_TESTS", raising=False)
    schema = f"gtmburst_async_{uuid.uuid4().hex}"
    control = create_async_engine(url, connect_args={"timeout": 10})
    engine = None
    try:
        async with control.begin() as connection:
            flags = (
                await connection.execute(
                    text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
                )
            ).one()
            assert flags == (False, False), "RLS gate requires non-superuser without BYPASSRLS"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(
            url,
            connect_args={
                "timeout": 10,
                "server_settings": {"search_path": schema},
            },
        )
        async with engine.begin() as connection:
            await connection.run_sync(
                Base.metadata.create_all,
                tables=[
                    Tenant.__table__,
                    DescribeRun.__table__,
                    DescribeRunItem.__table__,
                ],
            )
            for table in ("image_description_runs", "image_description_run_items"):
                await connection.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await connection.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
                await connection.execute(
                    text(f"""
                    CREATE POLICY tenant_isolation_{table} ON {table} FOR ALL
                    USING (tenant_id = {MIGRATION.SAFE_TENANT_EXPR} OR {MIGRATION.BYPASS_RLS_EXPR})
                    WITH CHECK (tenant_id = {MIGRATION.SAFE_TENANT_EXPR} OR {MIGRATION.BYPASS_RLS_EXPR})
                """)
                )
                flags = (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = to_regclass(:table)"
                        ),
                        {"table": table},
                    )
                ).one()
                assert flags == (True, True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [
                    Tenant(id=TENANT, site_url="https://rls-enqueue.test"),
                    Tenant(id=uuid.UUID(int=987), site_url="https://rls-other.test"),
                ]
            )
            await session.commit()
        yield factory
    finally:
        if engine is not None:
            await engine.dispose()
        async with control.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await control.dispose()


async def test_actual_post_reseeds_after_commit_and_preserves_cross_tenant_404(
    restricted_pg_factory, gate, monkeypatch
):
    factory = restricted_pg_factory
    monkeypatch.setattr(route, "worker_session_factory", lambda session: factory)
    admission = Admission()
    auth = SimpleNamespace(tenant_claim=str(TENANT), user_id=None)
    app = FastAPI()
    app.include_router(route.router, prefix="/scene")

    async def session_dependency():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_optional_session] = session_dependency
    app.dependency_overrides[require_write_access] = lambda: auth
    app.dependency_overrides[get_usage_admission_service] = lambda: admission
    app.dependency_overrides[get_description_adapter] = lambda: SimpleNamespace()
    app.dependency_overrides[get_async_gpu_description_adapter] = lambda: SimpleNamespace(n_passes=1)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/scene/describe/async",
            data={
                "request": json.dumps({"tenant_id": str(TENANT), "media_id": 42}),
                "operation_id": uuid.uuid4().hex,
            },
            files={"image_42": ("image.jpg", IMAGE, "image/jpeg")},
        )
        assert response.status_code == 200, f"expected async enqueue 200, got {response.status_code}: {response.text}"
        job_id = uuid.UUID(response.json()["job_id"])
        # Dedicated session verifies real durability and the enforced policy.
        async with factory() as session:
            assert await session.scalar(select(DescribeRun).where(DescribeRun.id == job_id)) is None
            await set_tenant_context(session, TENANT)
            assert await session.scalar(select(DescribeRun).where(DescribeRun.id == job_id)) is not None
            assert await session.scalar(select(DescribeRunItem).where(DescribeRunItem.run_id == job_id)) is not None
            await session.commit()
            assert await session.scalar(select(DescribeRunItem).where(DescribeRunItem.run_id == job_id)) is None
        own = await client.get(f"/scene/describe/jobs/{job_id}")
        assert own.status_code == 200, own.text
        auth.tenant_claim = str(uuid.UUID(int=987))
        other = await client.get(f"/scene/describe/jobs/{job_id}")
        assert other.status_code == 404, other.text
    assert gate.releases == 1
