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

from db.models.base_imports import _DB_SETTINGS, Base
from db.models.identity import (
    IdentityCluster,
    IdentityMember,
    IdentityNameSuppression,
    MediaIdentity,
)
from db.models.observability import AuditEvent
from db.models.scene import ImageDescription
from db.models.tenant import Tenant
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    require_write_access,
)
from recognition.interface_adapters.http.middleware.metrics import get_default_metrics
from scene.application.describe_jobs import InMemoryDescribeJobStore
from scene.application.description_adapter import AdapterResult
from scene.domain.description import DescriptionAdapterKind
from scene.interface_adapters.http.deps import get_description_adapter, get_gpu_description_adapter
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


def _make_db(naming_agreement_enabled=True):
    path = os.path.join(tempfile.gettempdir(), f"e19_route_{uuid.uuid4().hex}.db")
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
                        ImageDescription.__table__,
                        AuditEvent.__table__,
                        MediaIdentity.__table__,
                        IdentityCluster.__table__,
                        IdentityMember.__table__,
                        IdentityNameSuppression.__table__,
                    ],
                ),
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as s:  # provision the tenant so require_tenant_record passes
            s.add(
                Tenant(
                    id=uuid.UUID(TENANT_ID),
                    site_url="http://test.local",
                    naming_agreement_enabled=naming_agreement_enabled,
                )
            )
            await s.commit()
        await engine.dispose()

    asyncio.run(_init())
    return path, url


@contextmanager
def _client(auth_tenant=None, adapter=None, naming_agreement_enabled=True, db_absent=False, seed=None):
    path, url = _make_db(naming_agreement_enabled=naming_agreement_enabled)
    if seed is not None:
        sf_seed = async_sessionmaker(create_async_engine(url), expire_on_commit=False)

        async def _run_seed():
            async with sf_seed() as s:
                await seed(s)
                await s.commit()

        asyncio.run(_run_seed())
    sf = async_sessionmaker(create_async_engine(url), expire_on_commit=False)

    async def _session():
        async with sf() as s:
            yield s

    app = FastAPI()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth(tenant_claim=auth_tenant)
    app.dependency_overrides[get_optional_session] = (lambda: None) if db_absent else _session
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


def _post_async(client, tenant, *, media_id=42, image_key="image_42", content_type="image/jpeg", body=b"image-bytes"):
    return client.post(
        "/scene/describe/async",
        data={"request": json.dumps({"tenant_id": str(tenant), "media_id": media_id})},
        files={image_key: ("x.jpg", body, content_type)},
    )


def test_happy_path_returns_15_fields_then_cached():
    tenant = TENANT_ID
    with _client() as client:
        r1 = _post(client, tenant)
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert len(body) == 20  # 17 core-contract fields + 3 additive preview fields (E19-4a)
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


def test_async_unsupported_mime_415():
    tenant = TENANT_ID
    with _client() as client:
        assert _post_async(client, tenant, content_type="text/plain").status_code == 415


def test_async_empty_image_422():
    tenant = TENANT_ID
    with _client() as client:
        assert _post_async(client, tenant, body=b"").status_code == 422


def test_async_oversized_image_413(monkeypatch):
    monkeypatch.setenv("ACX_DESCRIPTION_MAX_IMAGE_BYTES", "4")
    tenant = TENANT_ID
    with _client() as client:
        assert _post_async(client, tenant, body=b"12345").status_code == 413


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
    middleware_paths = getattr(mws[0], "kwargs", {}).get("paths", set())
    assert "/scene/describe/multipart" in middleware_paths
    assert "/scene/describe/async" in middleware_paths


def test_local_cpu_route_uses_vlm_timeout(monkeypatch):
    monkeypatch.setenv("ACX_VLM_TIMEOUT_SECONDS", "0.001")
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "60")
    with _client(adapter=_SlowLocalAdapter()) as client:
        r = _post(client, TENANT_ID)
        assert r.status_code == 504
        # Message must report the VLM cap that actually fired, not the 60s
        # description timeout (regression guard for E19-1-REV-A-2 / REV-B-1).
        assert "0.001" in r.json()["detail"]


def _png_bytes(width=100, height=50):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), color=(120, 120, 120)).save(buf, format="PNG")
    return buf.getvalue()


def _post_png(client, tenant, *, media_id=42):
    return client.post(
        "/scene/describe/multipart",
        data={"request": json.dumps({"tenant_id": str(tenant), "media_id": media_id})},
        files={f"image_{media_id}": ("x.png", _png_bytes(), "image/png")},
    )


def _seed_confirmed_identity(label="Daniel", *, media_id=42, roster_id=None, suppressed=False):
    async def _seed(s):
        identity = MediaIdentity(
            tenant_id=uuid.UUID(TENANT_ID),
            media_id=media_id,
            media_url="http://test.local/42.png",
            bbox_x=10,
            bbox_y=10,
            bbox_width=20,
            bbox_height=20,
            confidence=0.97,
            embedding=[1.0] + [0.0] * (_DB_SETTINGS.pgvector_dimension - 1),
        )
        cluster = IdentityCluster(
            tenant_id=uuid.UUID(TENANT_ID),
            label=label,
            user_confirmed=True,
            roster_id=roster_id,
        )
        s.add_all([identity, cluster])
        await s.flush()
        s.add(
            IdentityMember(
                tenant_id=uuid.UUID(TENANT_ID),
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=0.9,
            )
        )
        if suppressed:
            s.add(IdentityNameSuppression(tenant_id=uuid.UUID(TENANT_ID), roster_id=roster_id))

    return _seed


def test_preview_fields_generic_when_no_identities():
    with _client() as client:
        r = _post_png(client, TENANT_ID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["generic_draft"] == body["alt_text_draft"]
        assert body["named_draft"] == body["generic_draft"]
        prov = body["naming_provenance"]
        assert prov["naming_allowed"] is False
        assert prov["reason"] == "no_confirmed_identities"
        assert prov["injected_names"] == []


def test_db_absent_named_draft_identical_to_generic():
    with _client(db_absent=True) as client:
        r = _post(client, TENANT_ID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["named_draft"] == body["generic_draft"] == body["alt_text_draft"]
        assert body["naming_provenance"]["reason"] == "db_unavailable"
        assert body["naming_provenance"]["injected_names"] == []


def test_confirmed_identity_named_in_preview():
    roster = uuid.uuid4()
    with _client(seed=_seed_confirmed_identity("Daniel", roster_id=roster)) as client:
        r = _post_png(client, TENANT_ID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["named_draft"].endswith("Pictured from left: Daniel.")
        assert body["generic_draft"] == body["alt_text_draft"]
        prov = body["naming_provenance"]
        assert prov["naming_allowed"] is True
        assert prov["reason"] is None
        assert [n["name"] for n in prov["injected_names"]] == ["Daniel"]
        assert prov["injected_names"][0]["roster_id"] == str(roster)


def test_agreement_off_suppresses_naming():
    with _client(
        naming_agreement_enabled=False,
        seed=_seed_confirmed_identity("Daniel", roster_id=uuid.uuid4()),
    ) as client:
        r = _post_png(client, TENANT_ID)
        body = r.json()
        assert body["named_draft"] == body["generic_draft"]
        assert body["naming_provenance"]["reason"] == "agreement_disabled"
        assert body["naming_provenance"]["injected_names"] == []


def test_suppress_list_blocks_naming_by_roster_id():
    roster = uuid.uuid4()
    with _client(seed=_seed_confirmed_identity("Daniel", roster_id=roster, suppressed=True)) as client:
        r = _post_png(client, TENANT_ID)
        body = r.json()
        assert body["named_draft"] == body["generic_draft"]
        assert body["naming_provenance"]["reason"] == "no_eligible_identities"
        assert body["naming_provenance"]["injected_names"] == []


class _GroundedAdapter:
    """Adapter exposing phrase boxes (S4): drives the NLG span-replacement path."""

    kind = DescriptionAdapterKind.SEEDED
    model_id = "grounded-fake"
    model_version = "1"
    prompt_or_task_version = "1"

    def describe(self, *, image_bytes, context):
        from scene.application.identity_merge import NormalizedBox, PhraseBox

        caption = "A man stands by the window."
        return AdapterResult(
            caption=caption,
            objects=(),
            ocr_text=None,
            alt_text_draft=caption,
            context_sources=(),
            context_applied=False,
            phrase_boxes=(
                PhraseBox(
                    phrase="A man",
                    span_start=0,
                    span_end=5,
                    box=NormalizedBox(x=0.0, y=0.0, width=0.5, height=1.0),
                ),
            ),
        )


def test_naming_preview_failure_degrades_to_generic_with_merge_error(monkeypatch):
    # S3-BR-02: a mid-preview exception must never break the core describe
    # response — both drafts still return, reason=merge_error.
    from scene.interface_adapters.http.routers import describe as describe_module

    async def boom(*args, **kwargs):
        raise RuntimeError("db exploded mid-preview")

    monkeypatch.setattr(describe_module, "load_confirmed_faces", boom)
    with _client() as client:
        r = _post_png(client, TENANT_ID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["named_draft"] == body["generic_draft"] == body["alt_text_draft"]
        assert body["naming_provenance"]["reason"] == "merge_error"


def test_grounded_adapter_names_via_span_replacement():
    # Face bbox (10,10,20,20) in a 100x50 PNG → center (0.2, 0.4), inside the
    # phrase box → NLG replacement, not the positional fallback.
    with _client(
        adapter=_GroundedAdapter(),
        seed=_seed_confirmed_identity("Daniel", roster_id=uuid.uuid4()),
    ) as client:
        r = _post_png(client, TENANT_ID)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["named_draft"] == "Daniel stands by the window."
        assert body["generic_draft"] == "A man stands by the window."
        assert [n["name"] for n in body["naming_provenance"]["injected_names"]] == ["Daniel"]


def test_cache_hit_keeps_grounded_naming_parity():
    # E19-4A-S4-BR-03: phrase boxes persist with the cached row, so the second
    # (cache-hit) call produces the identical grounded named draft — not the
    # positional fallback.
    with _client(
        adapter=_GroundedAdapter(),
        seed=_seed_confirmed_identity("Daniel", roster_id=uuid.uuid4()),
    ) as client:
        first = _post_png(client, TENANT_ID).json()
        second = _post_png(client, TENANT_ID).json()
        assert second["cached"] is True
        assert second["named_draft"] == first["named_draft"] == "Daniel stands by the window."
        assert second["naming_provenance"]["mode"] == first["naming_provenance"]["mode"] == "grounded"
        assert second["naming_provenance"]["injected_names"] == first["naming_provenance"]["injected_names"]


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


class _ImmediateGpuAdapter:
    kind = DescriptionAdapterKind.GPU
    model_id = "gpu-test"
    model_version = "1"
    prompt_or_task_version = "1"

    def describe(self, *, image_bytes, context):
        return AdapterResult(
            caption="GPU caption.",
            objects=(),
            ocr_text=None,
            alt_text_draft="GPU caption.",
            context_sources=(),
            context_applied=False,
        )


def test_async_full_queue_returns_503(monkeypatch):
    from scene.interface_adapters.http.routers import describe as describe_module

    store = InMemoryDescribeJobStore(max_jobs=1)
    store.enqueue(tenant_id=uuid.UUID(TENANT_ID), media_id=1, image_bytes=b"filled", context=None)
    monkeypatch.setattr(describe_module, "_ASYNC_JOBS", store)
    with _client() as client:
        r = _post_async(client, TENANT_ID)
        assert r.status_code == 503, r.text
        assert "describe job queue is full" in r.json()["detail"]


def test_get_describe_job_cross_tenant_returns_404(monkeypatch):
    from scene.interface_adapters.http.routers import describe as describe_module

    store = InMemoryDescribeJobStore()
    job = store.enqueue(
        tenant_id=uuid.UUID(TENANT_ID),
        media_id=42,
        image_bytes=b"image-bytes-payload",
        context=None,
    )
    store.set_final(job.job_id, visual_facts={"alt_text_draft": "done"})
    monkeypatch.setattr(describe_module, "_ASYNC_JOBS", store)
    other_tenant = str(uuid.uuid4())
    with _client(auth_tenant=other_tenant) as client:
        r = client.get(f"/scene/describe/jobs/{job.job_id}")
        assert r.status_code == 404, r.text


def test_get_describe_job_requires_tenant_claim(monkeypatch):
    from scene.interface_adapters.http.routers import describe as describe_module

    store = InMemoryDescribeJobStore()
    job = store.enqueue(
        tenant_id=uuid.UUID(TENANT_ID),
        media_id=42,
        image_bytes=b"image-bytes-payload",
        context=None,
    )
    monkeypatch.setattr(describe_module, "_ASYNC_JOBS", store)
    with _client(auth_tenant=None) as client:
        r = client.get(f"/scene/describe/jobs/{job.job_id}")
        assert r.status_code == 400, r.text
        assert "tenant claim required" in r.json()["detail"]


def test_async_enqueue_and_poll_returns_tenant_scoped_job(monkeypatch):
    from scene.interface_adapters.http.routers import describe as describe_module

    store = InMemoryDescribeJobStore()
    monkeypatch.setattr(describe_module, "_ASYNC_JOBS", store)
    with _client(auth_tenant=TENANT_ID) as client:
        client.app.dependency_overrides[get_gpu_description_adapter] = lambda: _ImmediateGpuAdapter()
        submitted = _post_async(client, TENANT_ID)
        assert submitted.status_code == 200, submitted.text
        job_id = submitted.json()["job_id"]
        polled = client.get(f"/scene/describe/jobs/{job_id}")
        assert polled.status_code == 200, polled.text
        body = polled.json()
        assert body["job_id"] == job_id
        assert body["status"] in {"final", "provisional", "running", "queued"}


def test_hosted_provider_fault_returns_502_with_reason():
    # A hosted-provider fault (key missing, provider 5xx, malformed body) must
    # surface as an actionable 502, not an opaque 500 (E20-11-S1A-08).
    from scene.infrastructure.provider.hosted_provider_adapter import (
        HostedProviderDescriptionAdapter,
    )

    def _boom(*, image_bytes, context, timeout_s, model):
        raise RuntimeError("provider 500: upstream exploded")

    adapter = HostedProviderDescriptionAdapter(model_id="gpt-4o-mini", model_version="gpt-4o-mini", invoke=_boom)
    with _client(adapter=adapter) as client:
        r = _post(client, TENANT_ID)
        assert r.status_code == 502, r.text
        assert "upstream exploded" in r.json()["detail"]
