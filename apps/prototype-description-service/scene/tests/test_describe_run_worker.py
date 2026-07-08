"""Describe-run submit route and worker behavior."""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from contextlib import contextmanager, suppress
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import run_describe_job
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.interface_adapters.http.router import router as scene_router

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


class _Auth:
    tenant_claim = str(TENANT_ID)
    user_id = 42


def _make_db():
    path = os.path.join(tempfile.gettempdir(), f"wbux3_describe_run_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(list[Table], [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]),
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            s.add(Tenant(id=TENANT_ID, site_url="http://test.local"))
            await s.commit()
        await engine.dispose()

    asyncio.run(_init())
    return path, url


async def _make_db_async():
    path = os.path.join(tempfile.gettempdir(), f"wbux3_describe_run_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=cast(list[Table], [Tenant.__table__, DescribeRun.__table__, DescribeRunItem.__table__]),
        )
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as s:
        s.add(Tenant(id=TENANT_ID, site_url="http://test.local"))
        await s.commit()
    await engine.dispose()
    return path, url


@contextmanager
def _client():
    path, url = _make_db()
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth()
    app.dependency_overrides[get_optional_session] = _session
    try:
        with TestClient(app) as client:
            yield client, sf
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def test_submit_describe_run_returns_immediately_and_persists_items():
    with _client() as (client, sf):
        response = client.post("/scene/describe/run", json={"tenant_id": str(TENANT_ID), "media_ids": [7, 8]})
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["tenant_id"] == str(TENANT_ID)
        assert body["total"] == 2
        assert body["completed"] == 0
        assert body["status"] == DescribeRunStatus.PENDING

        async def _assert_rows():
            async with sf() as s:
                run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=uuid.UUID(body["run_id"]))
                items = await DescribeRunRepository(s).list_run_items(
                    tenant_id=TENANT_ID,
                    run_id=uuid.UUID(body["run_id"]),
                )
            assert run is not None
            assert run.created_by_user_id == 42
            assert [item.media_id for item in items] == [7, 8]

        asyncio.run(_assert_rows())


def test_submit_rejects_empty_and_oversize(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIBE_RUN_MAX_ITEMS", "2")
    with _client() as (client, _):
        empty = client.post("/scene/describe/run", json={"tenant_id": str(TENANT_ID), "media_ids": []})
        oversize = client.post("/scene/describe/run", json={"tenant_id": str(TENANT_ID), "media_ids": [1, 2, 3]})
    assert empty.status_code == 422
    assert oversize.status_code == 422


def test_worker_marks_failed_item_and_continues_to_completion():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(tenant_id=TENANT_ID, media_ids=[1, 2, 3])
            await s.commit()

        async def describe_one(media_id: int) -> None:
            if media_id == 2:
                raise TimeoutError("simulated timeout")

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=0.5,
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED_WITH_ERRORS
        assert [(item.media_id, item.status) for item in items] == [
            (1, DescribeItemStatus.COMPLETED),
            (2, DescribeItemStatus.FAILED),
            (3, DescribeItemStatus.COMPLETED),
        ]
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_timeout_marks_item_failed():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(tenant_id=TENANT_ID, media_ids=[5])
            await s.commit()

        async def describe_one(_: int) -> None:
            await asyncio.sleep(0.05)

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=0.001,
        )

        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert items[0].status == DescribeItemStatus.FAILED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_cancel_skips_queued_items():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(tenant_id=TENANT_ID, media_ids=[9, 10])
            assert await repo.request_cancel(tenant_id=TENANT_ID, run_id=run_id)
            await s.commit()

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=lambda _: None,
            timeout_seconds=0.5,
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.CANCELLED
        assert [item.status for item in items] == [DescribeItemStatus.SKIPPED, DescribeItemStatus.SKIPPED]
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
