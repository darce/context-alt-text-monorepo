"""GUIDEDFIX-2: POST /scene/describe/run must be idempotent per (tenant, key).

A lost 202 plus a blind retry used to spend a second paid GPU run ([RES-01],
[COST-10]). The accept is now keyed on a caller-supplied ``idempotency_key``
reserved by a unique index, so a replay returns the first run and does no new
work.
"""

from __future__ import annotations

import asyncio
import json
import logging
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
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


def test_reordered_media_ids_under_one_key_replay_instead_of_conflicting(monkeypatch):
    """S03: order is not payload, so a reshuffled blind retry must replay.

    Predicted RED on the pre-fix route: it compared
    ``list(run.media_ids)`` against ``list(dict.fromkeys(media_ids))``,
    order-sensitive on both sides, so [70, 71] then [71, 70] under one key
    returned 409 and forced the caller to mint a new key — spending the second
    paid run the key exists to prevent. The WP client builds media_ids from a
    query with no pinned ORDER BY, so this is the common retry, not a corner.
    """
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70, 71])
        assert first.status_code == 202, first.text

        replay = _submit(client, [71, 70])
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert len(calls) == 1
        assert _run_rows(sf, TENANT_A) == 1


def test_repeated_media_ids_under_one_key_replay(monkeypatch):
    """Duplicates are deduped before inference, so they are not payload either."""
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70, 71])
        assert first.status_code == 202, first.text

        replay = _submit(client, [71, 70, 71], with_images=False)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert len(calls) == 1
        assert _run_rows(sf, TENANT_A) == 1


def test_same_key_with_a_different_recognition_switch_still_conflicts(monkeypatch):
    """The canonical digest must still catch a genuinely different payload."""
    _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70])
        assert first.status_code == 202, first.text

        data, files = _multipart([70])
        data["recognition_enabled"] = "false"
        conflict = client.post("/scene/describe/run", data=data, files=files)
        assert conflict.status_code == 409, conflict.text
        assert _run_rows(sf, TENANT_A) == 1


def test_same_key_and_media_ids_with_different_bytes_replays_by_contract(monkeypatch):
    """S04, contract option (b): the key binds (media_ids, recognition_enabled).

    Image bytes are deliberately outside the binding — hashing up to 200 x
    max_description_image_bytes on every replay is exactly the cost the
    replay-before-bytes ordering exists to avoid. The caller owns byte stability
    and must mint a new key when an asset's bytes change; the published schema
    says so. This test pins that documented behaviour so it cannot drift
    silently into an undocumented one.
    """
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = client.post(
            "/scene/describe/run",
            data={"tenant_id": str(TENANT_A), "media_ids": json.dumps([70]), "idempotency_key": KEY},
            files=[("image_70", ("70.png", b"\x89PNG\r\n\x1a\nFIRST", "image/png"))],
        )
        assert first.status_code == 202, first.text

        second = client.post(
            "/scene/describe/run",
            data={"tenant_id": str(TENANT_A), "media_ids": json.dumps([70]), "idempotency_key": KEY},
            files=[("image_70", ("70.png", b"\x89PNG\r\n\x1a\nSECOND", "image/png"))],
        )
        assert second.status_code == 202, second.text
        assert second.json()["run_id"] == first.json()["run_id"]
        assert len(calls) == 1
        assert _run_rows(sf, TENANT_A) == 1


def test_conflict_body_never_discloses_the_reserved_run(monkeypatch):
    """S09: the 409 precedes require_tenant_record and POST may carry no claim.

    Predicted RED on the pre-fix route: the detail carried ``run_id`` and the
    stored ``media_ids``, so a write-capable caller with no tenant claim could
    name any tenant_id, guess a key, and read back that tenant's run id and
    media id list.
    """
    _count_enqueues(monkeypatch)
    with _app() as (app, _sf), TestClient(app) as client:
        first = _submit(client, [70])
        assert first.status_code == 202, first.text
        reserved_run_id = first.json()["run_id"]

        conflict = _submit(client, [71])
        assert conflict.status_code == 409, conflict.text
        detail = conflict.json()["detail"]
        assert detail["code"] == "idempotency_conflict"
        assert detail["field"] == "idempotency_key"
        assert "run_id" not in detail
        assert "media_ids" not in detail
        assert reserved_run_id not in conflict.text
        assert "70" not in conflict.text


def test_non_idempotency_integrity_error_is_not_reinterpreted_as_a_collision(monkeypatch, caplog):
    """S05: a permanent IntegrityError must not become an infinite-retry 503.

    Predicted RED on the pre-fix route: the blanket ``except IntegrityError``
    checked no constraint name, so a foreign-key violation (e.g. the tenant row
    cascade-deleted between require_tenant_record and the flush) answered 503
    "retry with the same idempotency_key" and the client retried a
    deterministically failing insert forever, with no log line.
    """
    _count_enqueues(monkeypatch)

    class _ForeignKeyViolationError(Exception):
        sqlstate = "23503"

        def __str__(self) -> str:
            return (
                'insert or update on table "image_description_runs" violates foreign key '
                'constraint "image_description_runs_tenant_id_fkey"'
            )

    async def _boom(*_args, **_kwargs):
        raise IntegrityError("INSERT INTO image_description_runs ...", {}, _ForeignKeyViolationError())

    monkeypatch.setattr(DescribeRunRepository, "create_run", _boom)
    with _app() as (app, sf), TestClient(app) as client, caplog.at_level(logging.ERROR):
        with pytest.raises(IntegrityError):
            _submit(client, [70])
        assert _run_rows(sf, TENANT_A) == 0
    assert any("not an idempotency collision" in record.message for record in caplog.records)


def test_a_key_held_by_a_barren_reclaimed_run_can_be_re_reserved(monkeypatch):
    """S06: a restart-killed run must not own the key at 202 forever.

    Predicted RED on the pre-fix code: ``reclaim_interrupted_runs`` drove the
    orphaned run terminal while it kept the key, and ``_replay_or_conflict``
    returned unconditionally under the route's 202 status_code — so the retry
    got 202 naming a run with zero completed items, permanently.
    """
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70])
        assert first.status_code == 202, first.text
        dead_run_id = first.json()["run_id"]

        async def _reclaim() -> int:
            async with sf() as s:
                reclaimed = await DescribeRunRepository(s).reclaim_interrupted_runs()
                await s.commit()
                return reclaimed

        assert asyncio.run(_reclaim()) == 1

        async def _dead_run():
            async with sf() as s:
                return await s.get(DescribeRun, uuid.UUID(dead_run_id))

        dead = asyncio.run(_dead_run())
        assert dead is not None
        assert dead.completed_items == 0
        assert dead.idempotency_key is None

        retry = _submit(client, [70])
        assert retry.status_code == 202, retry.text
        assert retry.json()["run_id"] != dead_run_id
        assert len(calls) == 2
        assert _run_rows(sf, TENANT_A) == 2


def test_a_cancelled_run_releases_the_key(monkeypatch):
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70])
        assert first.status_code == 202, first.text
        cancelled_run_id = first.json()["run_id"]

        async def _cancel() -> str:
            async with sf() as s:
                repo = DescribeRunRepository(s)
                await repo.request_cancel(tenant_id=TENANT_A, run_id=uuid.UUID(cancelled_run_id))
                await s.commit()
                run = await repo.get_run(tenant_id=TENANT_A, run_id=uuid.UUID(cancelled_run_id))
                assert run is not None
                assert run.idempotency_key is None
                return str(run.status)

        assert asyncio.run(_cancel()) == DescribeRunStatus.CANCELLED

        retry = _submit(client, [70])
        assert retry.status_code == 202, retry.text
        assert retry.json()["run_id"] != cancelled_run_id
        assert len(calls) == 2
        assert _run_rows(sf, TENANT_A) == 2


def test_a_run_with_output_keeps_its_key_even_when_other_items_failed(monkeypatch):
    """Partial output is still output: that key must keep replaying its run."""
    calls = _count_enqueues(monkeypatch)
    with _app() as (app, sf), TestClient(app) as client:
        first = _submit(client, [70, 71])
        assert first.status_code == 202, first.text
        run_id = uuid.UUID(first.json()["run_id"])

        async def _one_ok_one_failed() -> str:
            async with sf() as s:
                repo = DescribeRunRepository(s)
                await repo.mark_item(
                    tenant_id=TENANT_A, run_id=run_id, media_id=70, status=DescribeItemStatus.COMPLETED
                )
                await repo.mark_item(
                    tenant_id=TENANT_A,
                    run_id=run_id,
                    media_id=71,
                    status=DescribeItemStatus.FAILED,
                    error_message="boom",
                )
                await s.commit()
                run = await repo.get_run(tenant_id=TENANT_A, run_id=run_id)
                assert run is not None
                return str(run.status)

        assert asyncio.run(_one_ok_one_failed()) == DescribeRunStatus.COMPLETED_WITH_ERRORS

        replay = _submit(client, [70, 71], with_images=False)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == str(run_id)
        assert len(calls) == 1
        assert _run_rows(sf, TENANT_A) == 1
