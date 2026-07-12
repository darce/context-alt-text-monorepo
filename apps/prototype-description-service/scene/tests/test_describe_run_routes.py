"""WBUX-4 S6-01: HTTP-level coverage for the describe-run status-poll and cancel
routes.

The INT-03 stream removal (commit 9b9aa45) deleted test_describe_run_stream.py,
which also carried the ONLY route-level test for GET /scene/describe/run/{id}
(status poll) and DELETE /scene/describe/run/{id} (cancel). This restores that
coverage without the removed SSE stream assertions.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from contextlib import contextmanager, suppress
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import ApiKey, DemoInstance, Tenant
from recognition.application.services.demo_provisioning_service import provision_demo
from recognition.interface_adapters.http.deps import get_optional_session
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from scene.domain.describe_run import DescribeRunStatus
from scene.interface_adapters.http.router import router as scene_router
from scene.tests.test_describe_run_worker import _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _create_run(client) -> str:
    response = _submit(client, [70])
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_status_route_returns_run_snapshot(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        status_response = client.get(f"/scene/describe/run/{run_id}")
        assert status_response.status_code == 200, status_response.text
        body = status_response.json()
        assert body["run_id"] == run_id
        assert body["status"] == DescribeRunStatus.PENDING
        assert "eta_seconds" in body


def test_status_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.get(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404


def test_cancel_route_flags_cancel_requested(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200, cancel_response.text
        body = cancel_response.json()
        assert body["cancel_requested"] is True
        # A cancel on a still-PENDING run resolves terminal-CANCELLED immediately.
        assert body["status"] == DescribeRunStatus.CANCELLED


def test_cancel_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.delete(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DS-2B: demo shared compute budget on describe/run (batch all-or-nothing)
# ---------------------------------------------------------------------------


@contextmanager
def _demo_run_client(*, recognition_quota: int = 5, non_demo: bool = False):
    """Client that exercises inline len(media_ids) consume on POST /describe/run."""
    path = os.path.join(tempfile.gettempdir(), f"ds2b_run_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(
                    list[Table],
                    [
                        Tenant.__table__,
                        ApiKey.__table__,
                        DemoInstance.__table__,
                        DescribeRun.__table__,
                        DescribeRunItem.__table__,
                    ],
                ),
            )
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _provision():
        async with sf() as s:
            result = await provision_demo(s, label="Run Demo", seed="default", recognition_quota=recognition_quota)
            await s.commit()
            return result

    provisioned = asyncio.run(_provision())
    tenant_id = str(provisioned.instance.tenant_id)
    slug = provisioned.instance.slug

    if non_demo:
        auth = AuthContext(
            token="not-a-demo-key",
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )
    else:
        auth = AuthContext(
            token=provisioned.raw_api_key,
            tenant_claim=tenant_id,
            api_key_id=None,
            is_admin=False,
            enabled=True,
        )

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_auth] = lambda: auth
    app.dependency_overrides[get_optional_session] = _session
    try:
        with TestClient(app) as client:
            yield client, sf, provisioned, tenant_id, slug
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _used(sf, slug: str) -> int:
    async def _read():
        async with sf() as s:
            row = await s.get(DemoInstance, slug)
            assert row is not None
            return int(row.recognition_used)

    return asyncio.run(_read())


def _submit_run(client, tenant_id: str, media_ids: list[int]):
    files = [(f"image_{m}", (f"{m}.png", b"\x89PNG\r\n\x1a\n", "image/png")) for m in media_ids]
    data = {"tenant_id": str(tenant_id), "media_ids": json.dumps(media_ids)}
    return client.post("/scene/describe/run", data=data, files=files or None)


def test_demo_quota_run_all_or_nothing_and_success(monkeypatch):
    _no_worker(monkeypatch)
    # budget N-1 → 429, used unchanged; then budget >= N → 202 and used += N
    with _demo_run_client(recognition_quota=2) as (client, sf, _p, tenant_id, slug):
        fail = _submit_run(client, tenant_id, [1, 2, 3])
        assert fail.status_code == 429, fail.text
        detail = fail.json()["detail"]
        assert detail["code"] == "demo_quota_exceeded"
        assert detail["quota_remaining"] == 2
        assert _used(sf, slug) == 0

        ok = _submit_run(client, tenant_id, [1, 2])
        assert ok.status_code == 202, ok.text
        assert _used(sf, slug) == 2


def test_demo_quota_run_empty_media_ids_422_no_consume(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=5) as (client, sf, _p, tenant_id, slug):
        # Explicit empty JSON array; no image parts.
        resp = client.post(
            "/scene/describe/run",
            data={"tenant_id": str(tenant_id), "media_ids": "[]"},
        )
        assert resp.status_code == 422, resp.text
        assert "'media_ids' must be non-empty" in resp.text
        assert _used(sf, slug) == 0


def test_demo_quota_run_non_demo_key_unaffected(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=1, non_demo=True) as (client, sf, _p, tenant_id, slug):
        resp = _submit_run(client, tenant_id, [7, 8])
        assert resp.status_code == 202, resp.text
        assert _used(sf, slug) == 0


def test_demo_quota_run_lifecycle_get_delete_consume_nothing(monkeypatch):
    _no_worker(monkeypatch)
    with _demo_run_client(recognition_quota=5) as (client, sf, _p, tenant_id, slug):
        created = _submit_run(client, tenant_id, [70])
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        used = _used(sf, slug)
        assert used == 1

        status_resp = client.get(f"/scene/describe/run/{run_id}")
        assert status_resp.status_code == 200, status_resp.text
        assert _used(sf, slug) == used

        cancel_resp = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_resp.status_code == 200, cancel_resp.text
        assert _used(sf, slug) == used
