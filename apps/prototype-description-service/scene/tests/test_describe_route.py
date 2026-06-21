"""S5: /scene/describe/multipart route behavior + api/main.py wiring."""

import asyncio
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager, suppress
from typing import cast

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.base_imports import Base
from db.models.observability import AuditEvent
from db.models.scene import ImageDescription
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.router import router as scene_router

TENANT_ID = "00000000-0000-0000-0000-0000000000bb"


class _Auth:
    def __init__(self, tenant_claim=None):
        self.tenant_claim = tenant_claim
        self.user_id = None


class _SlowLocalAdapter:
    kind = DescriptionAdapterKind.LOCAL_CPU
    model_id = "slow-local"
    model_version = "1"
    prompt_or_task_version = "1"

    def describe(self, *, image_bytes, context):
        time.sleep(0.05)
        return AdapterResult(
            caption="Slow local caption.",
            objects=(),
            ocr_text=None,
            alt_text_draft="Slow local caption.",
            context_sources=(),
            context_applied=False,
        )


def _make_db():
    path = os.path.join(tempfile.gettempdir(), f"e19_route_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(list[Table], [Tenant.__table__, ImageDescription.__table__, AuditEvent.__table__]),
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:  # provision the tenant so require_tenant_record passes
            s.add(Tenant(id=uuid.UUID(TENANT_ID), site_url="http://test.local"))
            await s.commit()
        await engine.dispose()

    asyncio.run(_init())
    return path, url


@contextmanager
def _client(auth_tenant=None, adapter=None):
    path, url = _make_db()
    sf = async_sessionmaker(create_async_engine(url), expire_on_commit=False)

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth(tenant_claim=auth_tenant)
    app.dependency_overrides[get_optional_session] = _session
    if adapter is not None:
        app.dependency_overrides[get_description_adapter] = lambda: adapter
    try:
        with TestClient(app) as client:
            yield client
    finally:
        with suppress(OSError):
            os.unlink(path)


def _post(client, tenant, *, media_id=42, image_key="image_42", content_type="image/jpeg"):
    return client.post(
        "/scene/describe/multipart",
        data={"request": json.dumps({"tenant_id": str(tenant), "media_id": media_id})},
        files={image_key: ("x.jpg", b"image-bytes-payload", content_type)},
    )


def test_happy_path_returns_15_fields_then_cached():
    tenant = TENANT_ID
    with _client() as client:
        r1 = _post(client, tenant)
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert len(body) == 15
        assert body["cached"] is False
        assert body["media_id"] == 42
        assert body["adapter"] == "seeded"
        assert body["provider_disclosure"]["provider"] == "none"
        r2 = _post(client, tenant)
        assert r2.status_code == 200
        assert r2.json()["cached"] is True


def test_route_records_description_metrics():
    metrics = get_default_metrics()
    with _client() as client:
        r1 = _post(client, TENANT_ID)
        r2 = _post(client, TENANT_ID)
        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

    generated = metrics.description_requests_total.labels(adapter="seeded", result="generated")._value.get()
    cache_hit = metrics.description_requests_total.labels(adapter="seeded", result="cache_hit")._value.get()
    cache_hit_total = metrics.description_cache_hits_total.labels(adapter="seeded")._value.get()
    assert generated >= 1
    assert cache_hit >= 1
    assert cache_hit_total >= 1


def test_two_image_parts_422():
    tenant = TENANT_ID
    with _client() as client:
        r = client.post(
            "/scene/describe/multipart",
            data={"request": json.dumps({"tenant_id": str(tenant), "media_id": 42})},
            files=[
                ("image_42", ("a.jpg", b"x", "image/jpeg")),
                ("image_43", ("b.jpg", b"y", "image/jpeg")),
            ],
        )
        assert r.status_code == 422


def test_tenant_mismatch_403():
    tenant = TENANT_ID
    with _client(auth_tenant=str(uuid.uuid4())) as client:
        assert _post(client, tenant).status_code == 403


def test_media_id_suffix_mismatch_422():
    tenant = TENANT_ID
    with _client() as client:
        assert _post(client, tenant, image_key="image_99").status_code == 422


def test_missing_image_part_422():
    tenant = TENANT_ID
    with _client() as client:
        r = client.post(
            "/scene/describe/multipart",
            data={"request": json.dumps({"tenant_id": str(tenant), "media_id": 42})},
        )
        assert r.status_code == 422


def test_unsupported_mime_415():
    tenant = TENANT_ID
    with _client() as client:
        assert _post(client, tenant, content_type="text/plain").status_code == 415


def test_create_app_registers_route_and_upload_cap():
    from api.main import create_app

    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/scene/describe/multipart" in paths
    mws = [
        m
        for m in app.user_middleware
        if getattr(getattr(m, "cls", None), "__name__", "") == "UploadSizeLimitMiddleware"
    ]
    assert mws, "UploadSizeLimitMiddleware not registered"
    assert "/scene/describe/multipart" in getattr(mws[0], "kwargs", {}).get("paths", set())


def test_local_cpu_route_uses_vlm_timeout(monkeypatch):
    monkeypatch.setenv("ACX_VLM_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "60")
    with _client(adapter=_SlowLocalAdapter()) as client:
        r = _post(client, TENANT_ID)
        assert r.status_code == 504
        # Message must report the VLM cap that actually fired, not the 60s
        # description timeout (regression guard for E19-1-REV-A-2 / REV-B-1).
        assert "0.001" in r.json()["detail"]


def test_stub_profile_returns_503_with_reason():
    # A deferred/stub profile (florence_large, gpu_phi4) resolves to a fail-closed
    # UnavailableDescriptionAdapter; the route must surface its reason as 503, not
    # an opaque 500 (E19-1-REV-C-1).
    from scene.infrastructure.vlm.unavailable_adapter import UnavailableDescriptionAdapter

    stub = UnavailableDescriptionAdapter(
        "florence_large (~39s/image) requires the async describe worker",
        kind=DescriptionAdapterKind.LOCAL_CPU,
        model_id="microsoft/Florence-2-large-ft",
        model_version="florence-2-large-ft",
    )
    with _client(adapter=stub) as client:
        r = _post(client, TENANT_ID)
        assert r.status_code == 503, r.text
        assert "async describe worker" in r.json()["detail"]
