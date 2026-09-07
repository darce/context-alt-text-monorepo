"""GUIDEDFIX-2: POST /scene/describe/run must be idempotent per (tenant, key).

A lost 202 plus a blind retry used to spend a second paid GPU run ([RES-01],
[COST-10]). The accept is now keyed on a caller-supplied ``idempotency_key``
reserved by a unique index, so a replay returns the first run and does no new
work.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from contextlib import contextmanager, suppress
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from scene.interface_adapters.http.router import router as scene_router

TENANT_A = uuid.UUID("00000000-0000-0000-0000-0000000000ca")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-0000000000cb")
KEY = "acx-idem-0123456789abcdef"


class _AnyTenantAuth:
    """No tenant claim: the submit route then trusts the form's tenant_id."""

    tenant_claim = ""
    user_id = 42


@pytest.fixture(autouse=True)
def _isolate_description_env(monkeypatch):
    for var in ("ACX_DESCRIPTION_ADAPTER", "ACX_GPU_ENDPOINT_URL", "ACX_GPU_WARMUP_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)


@contextmanager
def _app():
    path = os.path.join(tempfile.gettempdir(), f"guidedfix2_idem_{uuid.uuid4().hex}.db")
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
            s.add(Tenant(id=TENANT_A, site_url="http://a.test.local"))
            s.add(Tenant(id=TENANT_B, site_url="http://b.test.local"))
            await s.commit()
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _AnyTenantAuth()
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = _session
    try:
        yield app, sf
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _multipart(media_ids, *, tenant=TENANT_A, key=KEY, with_images=True):
    files = (
        [(f"image_{m}", (f"{m}.png", b"\x89PNG\r\n\x1a\n", "image/png")) for m in media_ids] if with_images else None
    )
    data = {"tenant_id": str(tenant), "media_ids": json.dumps(media_ids)}
    if key is not None:
        data["idempotency_key"] = key
    return data, files


def _submit(client, media_ids, *, tenant=TENANT_A, key=KEY, with_images=True):
    data, files = _multipart(media_ids, tenant=tenant, key=key, with_images=with_images)
    return client.post("/scene/describe/run", data=data, files=files)


def _count_enqueues(monkeypatch) -> list:
    calls: list = []

    async def _spy(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _spy)
    return calls


def _run_rows(sf, tenant) -> int:
    async def _body() -> int:
        async with sf() as s:
            return int(
                await s.scalar(select(func.count()).select_from(DescribeRun).where(DescribeRun.tenant_id == tenant))
            )

    return asyncio.run(_body())


def test_replay_of_same_key_returns_202_same_run_and_enqueues_once(monkeypatch):
    """A blind retry must replay the accepted run, not spend a second one."""
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70, 71])
        assert first.status_code == 202, first.text
        run_id = first.json()["run_id"]

        # No image parts on the replay: proof the replay path reads no bytes and
        # never reaches the missing-image-part validation.
        replay = _submit(client, [70, 71], with_images=False)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == run_id

        assert len(calls) == 1
        assert _run_rows(sf, TENANT_A) == 1


def test_same_key_with_different_media_ids_returns_409(monkeypatch):
    _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70])
        assert first.status_code == 202, first.text

        conflict = _submit(client, [71])
        assert conflict.status_code == 409, conflict.text
        assert "idempotency_key" in conflict.text
        assert _run_rows(sf, TENANT_A) == 1


def test_same_key_under_a_different_tenant_creates_a_distinct_run(monkeypatch):
    """Dedupe scope is (tenant_id, idempotency_key); tenants never collide."""
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        a = _submit(client, [70], tenant=TENANT_A)
        b = _submit(client, [70], tenant=TENANT_B)
        assert a.status_code == 202, a.text
        assert b.status_code == 202, b.text
        assert a.json()["run_id"] != b.json()["run_id"]
        assert len(calls) == 2
        assert _run_rows(sf, TENANT_A) == 1
        assert _run_rows(sf, TENANT_B) == 1


@pytest.mark.parametrize(
    "bad_key",
    [
        "short",
        "a" * 15,
        "a" * 129,
        "has spaces in it here",
        "bad/charset/0123456789",
        "bad.charset.0123456789",
        "",
    ],
)
def test_malformed_idempotency_key_is_rejected_422(monkeypatch, bad_key):
    _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        response = _submit(client, [70], key=bad_key)
        assert response.status_code == 422, response.text
        assert "idempotency_key" in response.text
        assert _run_rows(sf, TENANT_A) == 0


def test_omitted_idempotency_key_keeps_todays_non_deduped_behaviour(monkeypatch):
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70], key=None)
        second = _submit(client, [70], key=None)
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["run_id"] != second.json()["run_id"]
        assert len(calls) == 2
        assert _run_rows(sf, TENANT_A) == 2


def test_concurrent_submits_with_one_key_produce_exactly_one_run(monkeypatch):
    """Two racing accepts must be resolved by the unique index, not a pre-check.

    Both requests are in flight before either reservation lands, so the
    check-then-insert window is open; only the constraint can close it.
    """
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf):

        async def _race():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://race.test") as ac:
                data, files = _multipart([70, 71])
                return await asyncio.gather(
                    ac.post("/scene/describe/run", data=data, files=files),
                    ac.post("/scene/describe/run", data=data, files=files),
                )

        first, second = asyncio.run(_race())
        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert first.json()["run_id"] == second.json()["run_id"]
        assert _run_rows(sf, TENANT_A) == 1
        assert len(calls) == 1
