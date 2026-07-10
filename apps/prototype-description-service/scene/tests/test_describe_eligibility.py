"""E20-FUSION S3: decorative/eligibility gate on describe multipart route.

Decorative images skip inference entirely (no adapter call, no description).
Non-decorative requests are unaffected.
"""

from __future__ import annotations

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

from db.models.base_imports import Base
from db.models.observability import AuditEvent
from db.models.scene import ImageDescription
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.router import router as scene_router
from scene.interface_adapters.http.schemas.requests import DescribeImageEnvelope

TENANT_ID = "00000000-0000-0000-0000-0000000000bb"


class _Auth:
    def __init__(self, tenant_claim=None):
        self.tenant_claim = tenant_claim
        self.user_id = None


class CountingAdapter:
    kind = DescriptionAdapterKind.SEEDED
    model_id = "eligibility-test"
    model_version = "1"
    prompt_or_task_version = "1"

    def __init__(self):
        self.calls = 0

    def describe(self, *, image_bytes, context):
        self.calls += 1
        return AdapterResult(
            caption="Should not run for decorative.",
            objects=(),
            ocr_text=None,
            alt_text_draft="Should not run for decorative.",
            context_sources=(),
            context_applied=False,
        )


def _make_db():
    path = os.path.join(tempfile.gettempdir(), f"e20_elig_{uuid.uuid4().hex}.db")
    url = f"sqlite+aiosqlite:///{path}"

    async def _init():
        import asyncio

        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(
                Base.metadata.create_all,
                tables=cast(
                    list[Table],
                    [
                        Tenant.__table__,
                        ImageDescription.__table__,
                        AuditEvent.__table__,
                    ],
                ),
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:
            s.add(Tenant(id=uuid.UUID(TENANT_ID), site_url="http://test.local"))
            await s.commit()
        await engine.dispose()

    import asyncio

    asyncio.run(_init())
    return path, url


@contextmanager
def _client(adapter=None, auth_tenant=None):
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


def test_envelope_decorative_defaults_false():
    env = DescribeImageEnvelope.model_validate({"tenant_id": TENANT_ID, "media_id": 7})
    assert env.decorative is False


def test_envelope_accepts_decorative_true():
    env = DescribeImageEnvelope.model_validate({"tenant_id": TENANT_ID, "media_id": 7, "decorative": True})
    assert env.decorative is True


def test_decorative_skips_inference_returns_204():
    """Decorative → 204, adapter never called (skip before service.describe)."""
    adapter = CountingAdapter()
    with _client(adapter=adapter) as client:
        r = client.post(
            "/scene/describe/multipart",
            data={
                "request": json.dumps(
                    {
                        "tenant_id": TENANT_ID,
                        "media_id": 42,
                        "decorative": True,
                    }
                )
            },
            files={"image_42": ("x.jpg", b"image-bytes-payload", "image/jpeg")},
        )
        assert r.status_code == 204, r.text
        assert r.content in (b"", b"null") or len(r.content) == 0
        assert adapter.calls == 0


def test_decorative_skips_without_image_part():
    """Gate runs after envelope parse — decorative needs no image part."""
    adapter = CountingAdapter()
    with _client(adapter=adapter) as client:
        r = client.post(
            "/scene/describe/multipart",
            data={
                "request": json.dumps(
                    {
                        "tenant_id": TENANT_ID,
                        "media_id": 42,
                        "decorative": True,
                    }
                )
            },
            # no image part
        )
        assert r.status_code == 204
        assert adapter.calls == 0


def test_decorative_does_not_bypass_tenant_mismatch_403():
    """S3A-05: the decorative gate is ordered AFTER auth/tenant validation — a
    tenant-B envelope under a tenant-A credential gets 403, not a silent 204."""
    adapter = CountingAdapter()
    with _client(adapter=adapter, auth_tenant=str(uuid.uuid4())) as client:
        r = client.post(
            "/scene/describe/multipart",
            data={
                "request": json.dumps(
                    {
                        "tenant_id": TENANT_ID,
                        "media_id": 42,
                        "decorative": True,
                    }
                )
            },
        )
        assert r.status_code == 403
        assert adapter.calls == 0


def test_decorative_skip_is_logged(caplog):
    """S3A-05: the server backstop is observable — decorative skips log tenant/media."""
    import logging

    adapter = CountingAdapter()
    with _client(adapter=adapter) as client:
        with caplog.at_level(logging.INFO, logger="scene.interface_adapters.http.routers.describe"):
            r = client.post(
                "/scene/describe/multipart",
                data={
                    "request": json.dumps(
                        {
                            "tenant_id": TENANT_ID,
                            "media_id": 42,
                            "decorative": True,
                        }
                    )
                },
            )
        assert r.status_code == 204
        skip_logs = [rec for rec in caplog.records if "decorative image skipped" in rec.getMessage()]
        assert skip_logs, "decorative skip must emit an observability log line"
        assert TENANT_ID in skip_logs[0].getMessage()
        assert "42" in skip_logs[0].getMessage()


def test_non_decorative_unaffected():
    """decorative=false (default) still describes; adapter invoked once."""
    adapter = CountingAdapter()
    with _client(adapter=adapter) as client:
        r = client.post(
            "/scene/describe/multipart",
            data={
                "request": json.dumps(
                    {
                        "tenant_id": TENANT_ID,
                        "media_id": 42,
                        "decorative": False,
                    }
                )
            },
            files={"image_42": ("x.jpg", b"image-bytes-payload", "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["alt_text_draft"]
        assert body["cached"] is False
        assert adapter.calls == 1
