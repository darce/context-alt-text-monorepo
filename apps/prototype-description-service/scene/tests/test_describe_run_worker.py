"""Describe-run submit route and worker behavior."""

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
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, run_describe_job
from scene.domain.describe_run import DescribeItemStatus, DescribeRunStatus
from scene.interface_adapters.http.router import router as scene_router

TENANT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


@pytest.fixture(autouse=True)
def _isolate_description_env(monkeypatch):
    """Seeded-path tests must not inherit a deployment shell's GPU env (S1A-09)."""
    for var in ("ACX_DESCRIPTION_ADAPTER", "ACX_GPU_ENDPOINT_URL", "ACX_GPU_WARMUP_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)


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
    # Scene run routes do not depend on enforce_demo_quota, but the shared
    # scene_router also mounts multipart/async which do — keep the harness safe.
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = _session
    try:
        with TestClient(app) as client:
            yield client, sf
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _submit(client, media_ids, *, tenant=TENANT_ID, images_for=None):
    """Multipart submit: tenant_id + media_ids JSON + one image_<id> file part each."""
    parts = media_ids if images_for is None else images_for
    files = [(f"image_{m}", (f"{m}.png", b"\x89PNG\r\n\x1a\n", "image/png")) for m in parts]
    data = {"tenant_id": str(tenant), "media_ids": json.dumps(media_ids)}
    return client.post("/scene/describe/run", data=data, files=files)


def test_submit_describe_run_returns_immediately_and_persists_items(monkeypatch):
    import scene.interface_adapters.http.routers.describe_run as mod

    async def _noop(**_):
        return None

    monkeypatch.setattr(mod, "run_describe_job", _noop)
    with _client() as (client, sf):
        response = _submit(client, [7, 8])
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["tenant_id"] == str(TENANT_ID)
        assert body["total"] == 2
        assert body["completed"] == 0
        assert body["status"] == DescribeRunStatus.PENDING
        assert body["eta_seconds"] is None

        async def _assert_rows():
            async with sf() as s:
                repo = DescribeRunRepository(s)
                run = await repo.get_run(tenant_id=TENANT_ID, run_id=uuid.UUID(body["run_id"]))
                items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=uuid.UUID(body["run_id"]))
            assert run is not None
            assert run.created_by_user_id == 42
            assert [item.media_id for item in items] == [7, 8]
            # bytes persisted (worker no-op'd, so not yet cleared)
            assert all(item.image_bytes for item in items)
            assert all(item.image_content_type == "image/png" for item in items)

        asyncio.run(_assert_rows())


def test_submit_rejects_empty_and_oversize(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIBE_RUN_MAX_ITEMS", "2")
    with _client() as (client, _):
        empty = _submit(client, [])
        oversize = _submit(client, [1, 2, 3])
    assert empty.status_code == 422
    assert oversize.status_code == 422


def test_submit_rejects_media_id_without_image_part():
    with _client() as (client, _):
        # image part only for media_id 1, none for 2 -> 422
        resp = _submit(client, [1, 2], images_for=[1])
    assert resp.status_code == 422
    assert "media_ids" in resp.text or "2" in resp.text


def test_submit_launches_worker(monkeypatch):
    import scene.interface_adapters.http.routers.describe_run as mod

    captured: dict = {}

    async def fake_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(mod, "run_describe_job", fake_job)
    with _client() as (client, _):
        resp = _submit(client, [11, 12])
        assert resp.status_code == 202, resp.text
        assert resp.json()["status"] == DescribeRunStatus.PENDING
    assert captured["tenant_id"] == TENANT_ID
    assert isinstance(captured["run_id"], uuid.UUID)
    assert captured["session_factory"] is not None
    assert callable(captured["describe_one"])


def test_worker_completes_items_persists_drafts_and_clears_bytes():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID,
                media_ids=[1, 2, 3],
                images=dict.fromkeys((1, 2, 3), (b"rawbytes", "image/png")),
            )
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            assert image_bytes == b"rawbytes"
            assert content_type == "image/png"
            return DescribeItemOutcome(
                alt_text_draft=f"alt {media_id}",
                caption=f"cap {media_id}",
                provenance={"adapter": "fake", "media_id": media_id},
            )

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED
        assert (run.completed_items, run.failed_items, run.skipped_items) == (3, 0, 0)
        for item in items:
            assert item.status == DescribeItemStatus.COMPLETED
            # proof it transitioned through RUNNING
            assert item.attempts == 1
            assert item.started_at is not None
            assert item.alt_text_draft == f"alt {item.media_id}"
            assert item.caption == f"cap {item.media_id}"
            assert item.provenance == {"adapter": "fake", "media_id": item.media_id}
            # bytes reclaimed
            assert item.image_bytes is None
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_marks_failed_item_and_continues_to_completion():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[1, 2, 3])
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            if media_id == 2:
                raise TimeoutError("simulated timeout")
            return DescribeItemOutcome(alt_text_draft=f"alt {media_id}")

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.5
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
        failed = next(i for i in items if i.media_id == 2)
        assert failed.last_error
        assert failed.alt_text_draft is None
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_timeout_marks_item_failed():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[5])
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            await asyncio.sleep(0.05)
            return DescribeItemOutcome()

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.001
        )

        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert items[0].status == DescribeItemStatus.FAILED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_cancel_before_run_skips_all_items():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(
                tenant_id=TENANT_ID, media_ids=[9, 10], images=dict.fromkeys((9, 10), (b"rawbytes", "image/png"))
            )
            assert await repo.request_cancel(tenant_id=TENANT_ID, run_id=run_id)
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            return DescribeItemOutcome()

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.5
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.CANCELLED
        assert [item.status for item in items] == [DescribeItemStatus.SKIPPED, DescribeItemStatus.SKIPPED]
        # BE-04: skipped items must not leak image bytes
        assert all(item.image_bytes is None for item in items)
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_cancel_mid_run_ends_cancelled_not_completed(monkeypatch):
    """S1-01: a cancel that lands after some items completed ends CANCELLED."""

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[1, 2])
            await s.commit()

        # Simulate a cancel landing after item 1 finishes without a nested write
        # (a second SQLite writer would deadlock the worker's open transaction):
        # flip cancel_requested on the worker's own identity-mapped run object,
        # which flushes on the next commit.
        state = {"cancel": False}
        original_get_run = DescribeRunRepository.get_run

        async def patched_get_run(self, *, tenant_id, run_id):
            run = await original_get_run(self, tenant_id=tenant_id, run_id=run_id)
            if run is not None and state["cancel"] and not run.cancel_requested:
                run.cancel_requested = True
            return run

        monkeypatch.setattr(DescribeRunRepository, "get_run", patched_get_run)

        async def describe_one(media_id, image_bytes, content_type):
            if media_id == 1:
                state["cancel"] = True
            return DescribeItemOutcome(alt_text_draft=f"alt {media_id}")

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.5
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.CANCELLED
        statuses = {item.media_id: item.status for item in items}
        assert statuses[1] == DescribeItemStatus.COMPLETED
        assert statuses[2] == DescribeItemStatus.SKIPPED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_submit_rejects_oversized_image_part(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_MAX_IMAGE_BYTES", "10")
    with _client() as (client, _):
        files = [("image_1", ("1.png", b"x" * 64, "image/png"))]
        data = {"tenant_id": str(TENANT_ID), "media_ids": json.dumps([1])}
        resp = client.post("/scene/describe/run", data=data, files=files)
    assert resp.status_code == 413, resp.text


def test_submit_rejects_unsupported_content_type():
    with _client() as (client, _):
        files = [("image_1", ("1.bin", b"payload", "application/octet-stream"))]
        data = {"tenant_id": str(TENANT_ID), "media_ids": json.dumps([1])}
        resp = client.post("/scene/describe/run", data=data, files=files)
    assert resp.status_code == 415, resp.text


def test_create_run_dedups_media_ids():
    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[5, 5, 7, 5, 7])
            await s.commit()

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.total_items == 2
        assert run.media_ids == [5, 7]  # first-seen order preserved
        assert [item.media_id for item in items] == [5, 7]
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_worker_sets_tenant_context_on_its_session(monkeypatch):
    """BE-01: the worker's run session must scope RLS (else zero rows on Postgres)."""
    import scene.application.describe_run_worker as wmod

    calls: list = []
    real = wmod.set_tenant_context

    async def recorder(session, tenant_id):
        calls.append(tenant_id)
        await real(session, tenant_id)

    monkeypatch.setattr(wmod, "set_tenant_context", recorder)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[1])
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            return DescribeItemOutcome(alt_text_draft="x")

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.5
        )
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
    assert TENANT_ID in calls


def test_worker_fatal_error_marks_run_failed(monkeypatch):
    """S2-02: an unexpected fatal loop error forces the run terminal-FAILED."""

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        async def boom(self, *args, **kwargs):
            raise RuntimeError("fatal boom")

        monkeypatch.setattr(DescribeRunRepository, "mark_item", boom)

        async def describe_one(media_id, image_bytes, content_type):
            return DescribeItemOutcome(alt_text_draft="x")

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=0.5
        )

        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.FAILED
        assert run.error_message
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_gpu_health_poll_waits_through_boot_responses(monkeypatch):
    import scene.application.describe_run_worker as wmod

    statuses = iter((503, 503, 200))
    calls: list[tuple[str, dict[str, str]]] = []

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            assert timeout.connect == wmod._GPU_HEALTH_REQUEST_TIMEOUT_SECONDS

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, *, headers):
            calls.append((url, headers))
            return httpx.Response(next(statuses))

    monkeypatch.setattr(wmod.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(wmod, "_GPU_HEALTH_POLL_INTERVAL_SECONDS", 0)

    asyncio.run(
        wmod._wait_for_gpu_ready(
            endpoint_url="http://gpu.internal:8000",
            api_key="test-key",
            timeout_seconds=10,
        )
    )

    assert calls == [
        ("http://gpu.internal:8000/health", {"Authorization": "Bearer test-key"}),
        ("http://gpu.internal:8000/health", {"Authorization": "Bearer test-key"}),
        ("http://gpu.internal:8000/health", {"Authorization": "Bearer test-key"}),
    ]


def test_gpu_health_poll_times_out_when_endpoint_stays_unready(monkeypatch):
    import scene.application.describe_run_worker as wmod

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, *, headers):
            return httpx.Response(503)

    monkeypatch.setattr(wmod.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(TimeoutError, match="did not become ready within 0s"):
        asyncio.run(
            wmod._wait_for_gpu_ready(
                endpoint_url="http://gpu.internal:8000",
                api_key=None,
                timeout_seconds=0,
            )
        )


def test_gpu_health_poll_bounds_a_hung_request_to_warmup_deadline(monkeypatch):
    import scene.application.describe_run_worker as wmod

    cancelled = False

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, *, headers):
            nonlocal cancelled
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled = True
                raise

    monkeypatch.setattr(wmod.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(TimeoutError, match="did not become ready"):
        asyncio.run(
            wmod._wait_for_gpu_ready(
                endpoint_url="http://gpu.internal:8000",
                api_key=None,
                timeout_seconds=0.01,
            )
        )
    assert cancelled


def test_gpu_health_poll_stops_when_run_is_cancelled(monkeypatch):
    import scene.application.describe_run_worker as wmod

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def get(self, url, *, headers):
            raise AssertionError("cancel must be checked before the health request")

    async def cancelled():
        return True

    monkeypatch.setattr(wmod.httpx, "AsyncClient", FakeAsyncClient)
    with pytest.raises(wmod._RunCancelledError):
        asyncio.run(
            wmod._wait_for_gpu_ready(
                endpoint_url="http://gpu.internal:8000",
                api_key=None,
                timeout_seconds=10,
                cancel_requested=cancelled,
            )
        )


def test_gpu_warmup_gate_is_adapter_scoped_and_uses_configured_timeout(monkeypatch):
    import scene.application.describe_run_worker as wmod
    from scene.config.settings import DescriptionSettings
    from scene.domain.description import DescriptionAdapterKind

    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://localhost:8000/")
    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "17.5")
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    settings = DescriptionSettings()
    assert wmod.gpu_run_policy(adapter_kind=DescriptionAdapterKind.SEEDED, settings=settings) is None

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    policy = wmod.gpu_run_policy(adapter_kind=DescriptionAdapterKind.GPU, settings=DescriptionSettings())
    assert policy is not None
    assert policy.endpoint_url == "http://localhost:8000"
    assert policy.warmup_timeout_seconds == 17.5


def test_transient_classifier_uses_wrapped_http_status_and_rejects_permanent_faults():
    import scene.application.describe_run_worker as wmod

    request = httpx.Request("POST", "http://gpu.internal/v1/chat/completions")

    def wrapped_status(status_code: int) -> RuntimeError:
        response = httpx.Response(status_code, request=request)
        status_error = httpx.HTTPStatusError("endpoint response", request=request, response=response)
        wrapper = RuntimeError("GPU endpoint call failed")
        wrapper.__cause__ = status_error
        return wrapper

    assert wmod._is_transient_describe_error(wrapped_status(503))
    assert wmod._is_transient_describe_error(httpx.ConnectError("cold boot", request=request))
    assert not wmod._is_transient_describe_error(wrapped_status(400))
    assert not wmod._is_transient_describe_error(ValueError("invalid image"))


def test_gpu_worker_waits_for_readiness_then_retries_transient_item(monkeypatch):
    import scene.application.describe_run_worker as wmod
    from scene.config.settings import DescriptionSettings
    from scene.domain.description import DescriptionAdapterKind

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://localhost:8000")
    events: list[str] = []

    async def ready(**kwargs):
        assert kwargs["endpoint_url"] == "http://localhost:8000"
        assert kwargs["timeout_seconds"] == wmod._DEFAULT_GPU_WARMUP_TIMEOUT_SECONDS
        events.append("ready")

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", ready)
    monkeypatch.setattr(wmod, "_GPU_ITEM_RETRY_BASE_DELAY_SECONDS", 0)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID,
                media_ids=[1],
                images={1: (b"rawbytes", "image/png")},
            )
            await s.commit()

        calls = 0

        async def describe_one(media_id, image_bytes, content_type):
            nonlocal calls
            calls += 1
            events.append(f"describe-{calls}")
            if calls < 3:
                raise httpx.ConnectError("GPU still accepting connections")
            return DescribeItemOutcome(alt_text_draft="recovered")

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=0.5,
            gpu_policy=wmod.gpu_run_policy(
                adapter_kind=DescriptionAdapterKind.GPU,
                settings=DescriptionSettings(),
            ),
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert run is not None
        assert run.status == DescribeRunStatus.COMPLETED
        assert items[0].status == DescribeItemStatus.COMPLETED
        assert items[0].alt_text_draft == "recovered"
        assert calls == wmod._GPU_ITEM_MAX_ATTEMPTS
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())
    assert events == ["ready", "describe-1", "describe-2", "describe-3"]


def test_gpu_worker_opens_run_local_breaker_after_exhausted_retries(monkeypatch):
    import scene.application.describe_run_worker as wmod
    from scene.config.settings import DescriptionSettings
    from scene.domain.description import DescriptionAdapterKind

    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", "http://localhost:8000")
    monkeypatch.setattr(wmod, "_GPU_ITEM_RETRY_BASE_DELAY_SECONDS", 0)

    async def ready(**kwargs):
        return None

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", ready)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(tenant_id=TENANT_ID, media_ids=[1, 2, 3])
            await s.commit()

        calls: list[int] = []

        async def describe_one(media_id, image_bytes, content_type):
            calls.append(media_id)
            raise httpx.ConnectError("GPU disappeared")

        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=0.5,
            gpu_policy=wmod.gpu_run_policy(
                adapter_kind=DescriptionAdapterKind.GPU,
                settings=DescriptionSettings(),
            ),
        )

        async with sf() as s:
            items = await DescribeRunRepository(s).list_run_items(tenant_id=TENANT_ID, run_id=run_id)

        assert calls == [1] * wmod._GPU_ITEM_MAX_ATTEMPTS
        assert [item.status for item in items] == [DescribeItemStatus.FAILED] * 3
        assert "circuit open" in (items[1].last_error or "")
        assert "circuit open" in (items[2].last_error or "")
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_gpu_item_retry_is_bounded_and_permanent_errors_are_not_retried(monkeypatch):
    import scene.application.describe_run_worker as wmod

    monkeypatch.setattr(wmod, "_GPU_ITEM_RETRY_BASE_DELAY_SECONDS", 0)

    async def body():
        transient_calls = 0

        async def transient(*_):
            nonlocal transient_calls
            transient_calls += 1
            raise httpx.ReadTimeout("temporary")

        with pytest.raises(httpx.ReadTimeout):
            await wmod._describe_with_transient_retry(
                describe_one=transient,
                media_id=1,
                image_bytes=b"x",
                content_type="image/png",
                timeout_seconds=1,
                retry_transient=True,
            )
        assert transient_calls == wmod._GPU_ITEM_MAX_ATTEMPTS

        permanent_calls = 0

        async def permanent(*_):
            nonlocal permanent_calls
            permanent_calls += 1
            raise ValueError("invalid image")

        with pytest.raises(ValueError, match="invalid image"):
            await wmod._describe_with_transient_retry(
                describe_one=permanent,
                media_id=2,
                image_bytes=b"x",
                content_type="image/png",
                timeout_seconds=1,
                retry_transient=True,
            )
        assert permanent_calls == 1

    asyncio.run(body())


def test_transient_classifier_rejects_local_wait_for_timeout_and_accepts_chained():
    import scene.application.describe_run_worker as wmod

    assert not wmod._is_transient_describe_error(TimeoutError("local wait_for budget expired"))
    request = httpx.Request("POST", "http://gpu.internal/v1/chat/completions")
    chained = TimeoutError("adapter timeout")
    chained.__cause__ = httpx.ReadTimeout("read timed out", request=request)
    assert wmod._is_transient_describe_error(chained)


def test_seeded_worker_performs_exactly_one_attempt_on_transient_error():
    """S1A-05: retry eligibility belongs to the GPU policy; a seeded run must
    not multiply a transient fault into extra attempts."""

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")}
            )
            await s.commit()

        calls = 0
        request = httpx.Request("POST", "http://gpu.internal/v1/chat/completions")

        async def describe_one(media_id, image_bytes, content_type):
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("transient endpoint fault", request=request)

        await run_describe_job(
            tenant_id=TENANT_ID, run_id=run_id, session_factory=sf, describe_one=describe_one, timeout_seconds=1.0
        )
        assert calls == 1

        async with sf() as s:
            repo = DescribeRunRepository(s)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert [DescribeItemStatus(i.status) for i in items] == [DescribeItemStatus.FAILED]
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_warmup_timeout_marks_run_failed_and_reclaims_item_bytes(monkeypatch):
    """S1A-06 + S1A-04: warmup expiry is a routine terminal path; it must leave
    the run FAILED with a persisted message and no stranded QUEUED bytes."""
    import scene.application.describe_run_worker as wmod

    async def never_ready(**kwargs):
        raise TimeoutError("GPU endpoint did not become ready within 0.01s (no health response)")

    monkeypatch.setattr(wmod, "_wait_for_gpu_ready", never_ready)

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            run_id = await DescribeRunRepository(s).create_run(
                tenant_id=TENANT_ID, media_ids=[1, 2], images={1: (b"a", "image/png"), 2: (b"b", "image/png")}
            )
            await s.commit()

        async def describe_one(media_id, image_bytes, content_type):
            raise AssertionError("describe must not run when warmup never succeeds")

        policy = wmod.GpuRunPolicy(
            endpoint_url="http://gpu.internal:8000", api_key=None, warmup_timeout_seconds=0.01
        )
        await run_describe_job(
            tenant_id=TENANT_ID,
            run_id=run_id,
            session_factory=sf,
            describe_one=describe_one,
            timeout_seconds=1.0,
            gpu_policy=policy,
        )

        async with sf() as s:
            repo = DescribeRunRepository(s)
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            items = await repo.list_run_items(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.status == DescribeRunStatus.FAILED
        assert run.error_message and "ready" in run.error_message
        for item in items:
            assert DescribeItemStatus(item.status) == DescribeItemStatus.FAILED
            assert item.image_bytes is None
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_mark_run_failed_preserves_terminal_cancelled():
    """HARM-01: a cancel that already made the run terminal must not be
    overwritten by a late fatal-path FAILED write."""

    async def body():
        path, url = await _make_db_async()
        engine = create_async_engine(url)
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            repo = DescribeRunRepository(s)
            run_id = await repo.create_run(tenant_id=TENANT_ID, media_ids=[1], images={1: (b"x", "image/png")})
            run = await repo.get_run(tenant_id=TENANT_ID, run_id=run_id)
            assert run is not None
            run.status = DescribeRunStatus.CANCELLED
            await s.commit()

        async with sf() as s:
            changed = await DescribeRunRepository(s).mark_run_failed(
                tenant_id=TENANT_ID, run_id=run_id, error_message="late fatal error"
            )
            await s.commit()
        assert changed is False

        async with sf() as s:
            run = await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)
        assert run is not None
        assert run.status == DescribeRunStatus.CANCELLED
        await engine.dispose()
        os.unlink(path)

    asyncio.run(body())


def test_gpu_warmup_timeout_setting_fails_fast_on_invalid_values(monkeypatch):
    """S1A-07/S1B-05: a typo'd or non-finite warmup timeout fails at settings
    load, not as a per-run FAILED inside the worker."""
    from scene.config.settings import DescriptionSettings

    for bad in ("inf", "nan", "abc", "0", "-5", "999999"):
        monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", bad)
        with pytest.raises(ValueError):
            DescriptionSettings()

    monkeypatch.setenv("ACX_GPU_WARMUP_TIMEOUT_SECONDS", "17.5")
    assert DescriptionSettings().gpu_warmup_timeout_seconds == 17.5
