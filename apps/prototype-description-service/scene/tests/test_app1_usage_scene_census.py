"""G2 scene usage-admission census: three compute POSTs, free GETs, replay rules."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from contextlib import contextmanager, suppress
from typing import cast
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import scene.interface_adapters.http.routers.describe as describe_mod
import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.base_imports import Base
from db.models.identity import (
    IdentityCluster,
    IdentityMember,
    IdentityNameSuppression,
    MediaIdentity,
)
from db.models.observability import AuditEvent
from db.models.scene import (
    DescribeDemandLease,
    DescribeOperation,
    DescribeRun,
    DescribeRunItem,
    DescribeStartup,
    ImageDescription,
)
from db.models.tenant import Tenant
from recognition.application.services.usage_admission_service import (
    UsageAdmissionUnavailableError,
    UsageFingerprintConflictError,
)
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.domain.describe_run import DescribeUsageRouteMode, compute_request_digest, compute_usage_request_fingerprint
from scene.interface_adapters.http.router import router as scene_router
from scene.interface_adapters.http.routers.describe import AsyncAdmissionGate

TENANT_ID = UUID("00000000-0000-0000-0000-0000000000cc")
OP_A = "scene-usage-op-aaaaaaaa"
OP_B = "scene-usage-op-bbbbbbbb"
IDEMP_K = "scene-idem-key-aaaaaa"
PNG = b"\x89PNG\r\n\x1a\nFIRST"
PNG_B = b"\x89PNG\r\n\x1a\nSECOND"
_UNSET = object()

COMPUTE_POSTS = (
    "/scene/describe/multipart",
    "/scene/describe/async",
    "/scene/describe/run",
)
FREE_GETS = (
    "/scene/describe/jobs/{job_id}",
    "/scene/describe/run/{run_id}",
    "/scene/describe/run/{run_id}/items",
)


class _Auth:
    tenant_claim = str(TENANT_ID)
    user_id = 7


class _FakeAdmission:
    def __init__(self) -> None:
        self.reserves: list[dict[str, object]] = []
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []
        self._by_operation: dict[tuple[UUID, str], UsageTicket] = {}
        self.unavailable = False

    async def reserve(
        self,
        tenant_id,
        *,
        idempotency_key,
        job_id,
        cost_units,
        operation_id=None,
        request_fingerprint=None,
        queue_bytes=0,
    ):
        self.reserves.append(
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "job_id": job_id,
                "cost_units": cost_units,
                "operation_id": operation_id,
                "request_fingerprint": request_fingerprint,
                "queue_bytes": queue_bytes,
            }
        )
        if self.unavailable:
            raise UsageAdmissionUnavailableError("global usage admission state is missing")
        key = (tenant_id, operation_id or idempotency_key)
        existing = self._by_operation.get(key)
        if existing is not None:
            if existing.request_fingerprint != (request_fingerprint or ""):
                raise UsageFingerprintConflictError("usage operation reused with a different request fingerprint")
            return existing
        ticket = UsageTicket(
            uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=operation_id or idempotency_key,
            request_fingerprint=request_fingerprint or "",
            job_id=job_id,
            fence_token="fence-scene-g2",
        )
        self._by_operation[key] = ticket
        return ticket

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)

    async def commit_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        if fence_token != ticket.fence_token:
            raise UsageAdmissionUnavailableError("stale usage fence")
        self.commits.append(ticket)

    async def release_fenced(self, ticket: UsageTicket, *, fence_token: str) -> None:
        if fence_token != ticket.fence_token:
            raise UsageAdmissionUnavailableError("stale usage fence")
        self.releases.append(ticket)


@contextmanager
def _census_client(admission: _FakeAdmission | None, monkeypatch, *, install_admission: bool = True, adapter=None):
    path = os.path.join(tempfile.gettempdir(), f"app1_usage_scene_{uuid.uuid4().hex}.db")
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
                        DescribeRun.__table__,
                        DescribeRunItem.__table__,
                        DescribeStartup.__table__,
                        DescribeOperation.__table__,
                        DescribeDemandLease.__table__,
                    ],
                ),
            )
            await conn.execute(
                text(
                    "CREATE TABLE describe_load_snapshot_revisions ("
                    "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                    "revision INTEGER NOT NULL)"
                )
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        async with sf() as session:
            session.add(Tenant(id=TENANT_ID, site_url="http://census.test.local"))
            await session.commit()
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        async with sf() as session:
            yield session

    async def _noop_async(**_kwargs):
        return None

    async def _noop_run(**_kwargs):
        return None

    monkeypatch.setattr(describe_mod, "run_async_describe_job", _noop_async)
    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop_run)

    app = FastAPI()
    app.state.session_factory = sf
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth()
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = _session
    if install_admission and admission is not None:
        app.state.usage_admission_service = admission
        app.dependency_overrides[get_usage_admission_service] = lambda: admission
    if adapter is not None:
        from scene.interface_adapters.http.deps import get_description_adapter

        app.dependency_overrides[get_description_adapter] = lambda: adapter
    try:
        with TestClient(app) as client:
            yield client, sf
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _multipart(
    operation_id=_UNSET,
    *,
    body: bytes = PNG,
    decorative: bool = False,
    media_id: int = 42,
    tenant_id: UUID = TENANT_ID,
):
    envelope = {"tenant_id": str(tenant_id), "media_id": media_id}
    if decorative:
        envelope["decorative"] = True
    data = {"request": json.dumps(envelope)}
    if operation_id is _UNSET:
        operation_id = uuid4().hex
    if operation_id is not None:
        data["operation_id"] = operation_id
    files = {f"image_{media_id}": ("x.jpg", body, "image/jpeg")}
    return data, files


def _post_multipart(client, **kwargs):
    data, files = _multipart(**kwargs)
    return client.post("/scene/describe/multipart", data=data, files=files)


def _post_async(client, *, operation_id: str | None = OP_A, body: bytes = PNG, media_id: int = 42):
    data, files = _multipart(operation_id=operation_id, body=body, media_id=media_id)
    return client.post("/scene/describe/async", data=data, files=files)


def _post_run(
    client,
    *,
    operation_id: str | None = OP_A,
    idempotency_key=_UNSET,
    body: bytes = PNG,
    media_ids: list[int] | None = None,
):
    media_ids = media_ids or [70]
    data = {
        "tenant_id": str(TENANT_ID),
        "media_ids": json.dumps(media_ids),
        "recognition_enabled": "false",
    }
    if operation_id is not None:
        data["operation_id"] = operation_id
    key = operation_id if idempotency_key is _UNSET else idempotency_key
    if key is not None:
        data["idempotency_key"] = key
    files = [(f"image_{media_id}", (f"{media_id}.png", body, "image/png")) for media_id in media_ids]
    return client.post("/scene/describe/run", data=data, files=files)


def test_usage_fingerprint_covers_route_media_bytes_context_and_tier():
    first = compute_usage_request_fingerprint(
        route_mode=DescribeUsageRouteMode.BULK,
        media_ids=[71, 70],
        image_digests={70: "aa", 71: "bb"},
        context_hash="ctx",
        recognition_enabled=True,
        tier="gpu",
    )
    reordered = compute_usage_request_fingerprint(
        route_mode=DescribeUsageRouteMode.BULK,
        media_ids=[70, 71],
        image_digests={71: "bb", 70: "aa"},
        context_hash="ctx",
        recognition_enabled=True,
        tier="gpu",
    )
    changed_bytes = compute_usage_request_fingerprint(
        route_mode=DescribeUsageRouteMode.BULK,
        media_ids=[70, 71],
        image_digests={70: "aa", 71: "cc"},
        context_hash="ctx",
        recognition_enabled=True,
        tier="gpu",
    )
    other_route = compute_usage_request_fingerprint(
        route_mode=DescribeUsageRouteMode.ASYNC,
        media_ids=[70, 71],
        image_digests={70: "aa", 71: "bb"},
        context_hash="ctx",
        recognition_enabled=True,
        tier="gpu",
    )
    assert first == reordered
    assert len(first) == 64
    assert first != changed_bytes
    assert first != other_route


def test_route_census_enumerates_compute_posts_and_free_gets():
    posts: set[str] = set()
    gets: set[str] = set()
    for route in scene_router.routes:
        path = f"/scene{getattr(route, 'path', '')}"
        methods = getattr(route, "methods", set()) or set()
        if "POST" in methods:
            posts.add(path)
        if "GET" in methods:
            gets.add(path)
    for path in COMPUTE_POSTS:
        assert path in posts
    for path in FREE_GETS:
        assert path in gets


def test_three_compute_posts_reserve_before_dispatch(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        multipart = _post_multipart(client)
        async_job = _post_async(client, operation_id="async-op-00000000", media_id=43)
        bulk = _post_run(client, operation_id="bulk-op-0000000000", media_ids=[70])

    assert multipart.status_code == 200, multipart.text
    assert async_job.status_code == 200, async_job.text
    assert bulk.status_code == 202, bulk.text
    assert len(admission.reserves) == 3
    modes_seen = {reserve["operation_id"] for reserve in admission.reserves}
    assert "async-op-00000000" in modes_seen
    assert "bulk-op-0000000000" in modes_seen
    assert multipart.json()["operation_id"] in modes_seen
    async_id = uuid.UUID(async_job.json()["job_id"])
    bulk_id = uuid.UUID(bulk.json()["run_id"])
    assert any(reserve["job_id"] == str(async_id) for reserve in admission.reserves)
    assert any(reserve["job_id"] == str(bulk_id) for reserve in admission.reserves)
    for reserve in admission.reserves:
        assert isinstance(reserve["job_id"], str) and reserve["job_id"]
        assert isinstance(reserve["request_fingerprint"], str) and len(str(reserve["request_fingerprint"])) == 64
        assert isinstance(reserve["queue_bytes"], int) and reserve["queue_bytes"] >= 0
        assert reserve["operation_id"]
        ticket_fields = admission._by_operation[(TENANT_ID, str(reserve["operation_id"]))]
        assert ticket_fields.reservation_id
        assert ticket_fields.tenant_id == TENANT_ID
        assert ticket_fields.cost_units >= 1
        assert ticket_fields.job_id == reserve["job_id"]
        assert ticket_fields.fence_token == "fence-scene-g2"
    assert len(admission.commits) == 1
    assert admission.commits[0].job_id == admission.reserves[0]["job_id"]
    assert admission.releases == []


def test_get_polling_status_and_results_stay_free(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        async_job = _post_async(client, operation_id="poll-async-000000", media_id=8)
        bulk = _post_run(client, operation_id="poll-bulk-00000000", media_ids=[9])
        assert async_job.status_code == 200, async_job.text
        assert bulk.status_code == 202, bulk.text
        reserved = len(admission.reserves)
        job_id = async_job.json()["job_id"]
        run_id = bulk.json()["run_id"]
        assert client.get(f"/scene/describe/jobs/{job_id}").status_code == 200
        assert client.get(f"/scene/describe/run/{run_id}").status_code == 200
        assert client.get(f"/scene/describe/run/{run_id}/items").status_code == 200
        assert len(admission.reserves) == reserved
        assert admission.commits == []


def test_same_operation_and_fingerprint_replays_one_reservation(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        first = _post_run(client, operation_id=OP_A, media_ids=[70])
        replay = _post_run(client, operation_id=OP_A, media_ids=[70])
        async_first = _post_async(client, operation_id=OP_B, media_id=11)
        async_replay = _post_async(client, operation_id=OP_B, media_id=11)

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert first.json()["run_id"] == replay.json()["run_id"]
    assert async_first.status_code == 200, async_first.text
    assert async_replay.status_code == 200, async_replay.text
    assert async_first.json()["job_id"] == async_replay.json()["job_id"]
    assert len(admission._by_operation) == 2
    assert admission.commits == []


def test_changed_fingerprint_is_409(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        first = _post_run(client, operation_id=OP_A, body=PNG, media_ids=[70])
        changed = _post_run(client, operation_id=OP_A, body=PNG_B, media_ids=[70])
        async_first = _post_async(client, operation_id=OP_B, body=PNG, media_id=12)
        async_changed = _post_async(client, operation_id=OP_B, body=PNG_B, media_id=12)
        mp_first = _post_multipart(client, body=PNG)
        mp_changed = _post_multipart(client, operation_id=mp_first.json()["operation_id"], body=PNG_B)

    assert first.status_code == 202, first.text
    assert changed.status_code == 409, changed.text
    assert async_first.status_code == 200, async_first.text
    assert async_changed.status_code == 409, async_changed.text
    assert mp_first.status_code == 200, mp_first.text
    assert mp_changed.status_code == 409, mp_changed.text


def test_new_operation_is_charged_independently(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        first = _post_run(client, operation_id=OP_A, media_ids=[70])
        second = _post_run(client, operation_id=OP_B, media_ids=[70])

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["run_id"] != second.json()["run_id"]
    assert len(admission._by_operation) == 2
    assert admission.reserves[0]["request_fingerprint"] == admission.reserves[1]["request_fingerprint"]


def test_http_202_does_not_commit_or_release_usage(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        response = _post_run(client, operation_id=OP_A, media_ids=[70, 71])

    assert response.status_code == 202, response.text
    assert len(admission.reserves) == 1
    assert admission.reserves[0]["cost_units"] == 2
    assert admission.reserves[0]["queue_bytes"] == len(PNG) * 2
    assert admission.commits == []
    assert admission.releases == []


def test_async_queue_rejection_releases_usage(monkeypatch):
    admission = _FakeAdmission()
    gate = AsyncAdmissionGate(max_jobs=1, max_retained_image_bytes=10 * 1024 * 1024)
    assert gate.try_acquire(1) is None
    monkeypatch.setattr(describe_mod, "_ASYNC_ADMISSION", gate)
    with _census_client(admission, monkeypatch) as (client, _sf):
        refused = _post_async(client, operation_id=OP_A)

    assert refused.status_code == 503, refused.text
    assert "describe job queue is full" in refused.json()["detail"]
    assert len(admission.reserves) == 1
    assert len(admission.releases) == 1
    assert admission.commits == []


def test_missing_global_state_is_stable_503(monkeypatch):
    admission = _FakeAdmission()
    admission.unavailable = True
    with _census_client(admission, monkeypatch) as (client, _sf):
        multipart = _post_multipart(client)
        async_job = _post_async(client, operation_id="unavail-async-0000")
        bulk = _post_run(client, operation_id="unavail-bulk-00000")

    assert multipart.status_code == 503, multipart.text
    assert async_job.status_code == 503, async_job.text
    assert bulk.status_code == 503, bulk.text
    assert admission.commits == []


def test_decorative_and_cache_paths_stay_free(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        decorative = _post_multipart(client, decorative=True)
        first = _post_multipart(client)
        cached = _post_multipart(client, operation_id=None)

    assert decorative.status_code == 204, decorative.text
    assert first.status_code == 200, first.text
    assert cached.status_code == 200, cached.text
    assert cached.json()["cached"] is True
    assert len(admission.reserves) == 1
    assert len(admission.commits) == 1
    assert admission.releases == []


def test_multipart_precompute_failure_releases_without_commit(monkeypatch):
    from fastapi import HTTPException

    async def _boom(*_args, **_kwargs):
        raise HTTPException(status_code=429, detail={"code": "demo_quota_exceeded"})

    monkeypatch.setattr(describe_mod, "maybe_consume_demo_quota", _boom)
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        response = _post_multipart(client)

    assert response.status_code == 429, response.text
    assert len(admission.reserves) == 1
    assert len(admission.releases) == 1
    assert admission.commits == []


class _BoomAdapter:
    kind = describe_mod.DescriptionAdapterKind.SEEDED
    model_id = "boom-seeded"
    model_version = "1"
    prompt_or_task_version = "1"
    calls = 0

    def describe(self, *, image_bytes, context):
        del image_bytes, context
        type(self).calls += 1
        raise RuntimeError("adapter exploded after dispatch")


class _GpuBoomAdapter(_BoomAdapter):
    kind = describe_mod.DescriptionAdapterKind.GPU


def test_multipart_postcompute_failure_commits_without_release(monkeypatch):
    _BoomAdapter.calls = 0
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch, adapter=_BoomAdapter()) as (client, _sf):
        response = _post_multipart(client)

    assert response.status_code == 502, response.text
    assert _BoomAdapter.calls == 1
    assert len(admission.reserves) == 1
    assert len(admission.commits) == 1
    assert admission.releases == []


def test_idempotency_key_without_caller_operation_replays_one_reservation(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _sf):
        first = _post_run(client, operation_id=OP_A, idempotency_key=IDEMP_K, media_ids=[70])
        replay = _post_run(client, operation_id=None, idempotency_key=IDEMP_K, media_ids=[70])
        changed = _post_run(client, operation_id=None, idempotency_key=IDEMP_K, body=PNG_B, media_ids=[70])
        independent = _post_run(client, operation_id=OP_B, idempotency_key=OP_B, media_ids=[70])

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert first.json()["run_id"] == replay.json()["run_id"]
    assert changed.status_code == 409, changed.text
    assert independent.status_code == 202, independent.text
    assert independent.json()["run_id"] != first.json()["run_id"]
    assert len(admission.reserves) == 2
    assert {reserve["idempotency_key"] for reserve in admission.reserves} == {IDEMP_K, OP_B}
    assert all(reserve["idempotency_key"] == reserve["operation_id"] for reserve in admission.reserves)


def test_metered_posts_fail_closed_when_admission_service_missing(monkeypatch):
    _BoomAdapter.calls = 0
    with _census_client(None, monkeypatch, install_admission=False, adapter=_BoomAdapter()) as (client, _sf):
        multipart = _post_multipart(client)
        async_job = _post_async(client, operation_id="missing-async-0000")
        bulk = _post_run(client, operation_id="missing-bulk-00000")

    assert multipart.status_code == 503, multipart.text
    assert async_job.status_code == 503, async_job.text
    assert bulk.status_code == 503, bulk.text
    assert multipart.json()["detail"] == {"error": "usage_admission_unavailable"}
    assert _BoomAdapter.calls == 0


def test_gpu_multipart_missing_admission_does_not_keep_demand_lease_active(monkeypatch):
    _GpuBoomAdapter.calls = 0
    with _census_client(None, monkeypatch, install_admission=False, adapter=_GpuBoomAdapter()) as (client, sf):
        first = _post_multipart(client, operation_id=OP_A)

        async def _lease_states():
            async with sf() as session:
                leases = list((await session.execute(select(DescribeDemandLease))).scalars())
                return [lease.state for lease in leases]

        after_first = asyncio.run(_lease_states())
        retry = _post_multipart(client, operation_id=OP_A)
        after_retry = asyncio.run(_lease_states())

    assert first.status_code == 503, first.text
    assert retry.status_code == 503, retry.text
    assert "active" not in after_first
    assert after_retry == after_first
    assert _GpuBoomAdapter.calls == 0


def test_legacy_run_digest_replays_identical_bytes_and_conflicts_on_changed_bytes(monkeypatch):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, sf):
        first = _post_run(client, operation_id=OP_A, media_ids=[70], body=PNG)
        run_id = UUID(first.json()["run_id"])

        async def _seed_legacy_digest():
            async with sf() as session:
                run = await session.get(DescribeRun, run_id)
                assert run is not None
                run.request_digest = compute_request_digest(media_ids=[70], recognition_enabled=False)
                await session.commit()

        asyncio.run(_seed_legacy_digest())
        replay = _post_run(client, operation_id=OP_A, media_ids=[70], body=PNG)
        changed = _post_run(client, operation_id=OP_A, media_ids=[70], body=PNG_B)

    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert replay.json()["run_id"] == first.json()["run_id"]
    assert changed.status_code == 409, changed.text
    assert len(admission.reserves) == 1


@contextmanager
def _ledger_client(monkeypatch, *, adapter=None):
    from datetime import UTC, datetime, timedelta

    from db.models import UsageReservation
    from db.models.portal_billing import GlobalUsageAdmissionState, TenantEntitlement
    from recognition.domain.portal_contracts import (
        DEFAULT_GLOBAL_CONFIG_VERSION,
        DEFAULT_GLOBAL_DAILY_COST_LIMIT,
        DEFAULT_GLOBAL_FENCE_EPOCH,
        DEFAULT_GLOBAL_INFLIGHT_LIMIT,
        DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
        DEFAULT_GLOBAL_QUEUE_LIMIT,
        GLOBAL_USAGE_ADMISSION_STATE_ID,
        EntitlementStatus,
    )
    from recognition.interface_adapters.http.deps.portal_composition import UsageAdmissionServiceFactory

    path = os.path.join(tempfile.gettempdir(), f"app1_usage_ledger_{uuid.uuid4().hex}.db")
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
                        TenantEntitlement.__table__,
                        UsageReservation.__table__,
                        GlobalUsageAdmissionState.__table__,
                        ImageDescription.__table__,
                        AuditEvent.__table__,
                        MediaIdentity.__table__,
                        IdentityCluster.__table__,
                        IdentityMember.__table__,
                        IdentityNameSuppression.__table__,
                        DescribeRun.__table__,
                        DescribeRunItem.__table__,
                        DescribeStartup.__table__,
                        DescribeOperation.__table__,
                        DescribeDemandLease.__table__,
                    ],
                ),
            )
            await conn.execute(
                text(
                    "CREATE TABLE describe_load_snapshot_revisions ("
                    "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
                    "revision INTEGER NOT NULL)"
                )
            )
        sf = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(tz=UTC)
        async with sf() as session:
            session.add(Tenant(id=TENANT_ID, site_url="http://ledger.test.local"))
            session.add(
                TenantEntitlement(
                    tenant_id=TENANT_ID,
                    plan_code="beta",
                    allowance_version="scene-g2",
                    allowance_jobs=20,
                    period_start=now - timedelta(minutes=1),
                    period_end=now + timedelta(hours=1),
                    status=EntitlementStatus.BETA_ACTIVE,
                    source="unit-test",
                )
            )
            session.add(
                GlobalUsageAdmissionState(
                    id=GLOBAL_USAGE_ADMISSION_STATE_ID,
                    period_start=datetime(now.year, now.month, now.day, tzinfo=UTC),
                    period_end=datetime(now.year, now.month, now.day, tzinfo=UTC) + timedelta(days=1),
                    daily_cost_limit=DEFAULT_GLOBAL_DAILY_COST_LIMIT,
                    daily_cost_units=0,
                    inflight_limit=DEFAULT_GLOBAL_INFLIGHT_LIMIT,
                    inflight_units=0,
                    queue_limit=DEFAULT_GLOBAL_QUEUE_LIMIT,
                    queue_depth=0,
                    queue_byte_limit=DEFAULT_GLOBAL_QUEUE_BYTE_LIMIT,
                    queue_bytes=0,
                    stop_requested=False,
                    fence_epoch=DEFAULT_GLOBAL_FENCE_EPOCH,
                    config_version=DEFAULT_GLOBAL_CONFIG_VERSION,
                    updated_at=now,
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(_init())
    engine = create_async_engine(url)
    sf = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():
        from fastapi import HTTPException

        async with sf() as session:
            try:
                yield session
                await session.commit()
            except HTTPException:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise

    async def _noop_async(**_kwargs):
        return None

    async def _noop_run(**_kwargs):
        return None

    monkeypatch.setattr(describe_mod, "run_async_describe_job", _noop_async)
    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop_run)

    app = FastAPI()
    app.state.session_factory = sf
    app.state.usage_admission_service = UsageAdmissionServiceFactory()
    app.include_router(scene_router, prefix="/scene")
    app.dependency_overrides[require_write_access] = lambda: _Auth()
    app.dependency_overrides[enforce_demo_quota] = lambda: None
    app.dependency_overrides[get_optional_session] = _session
    if adapter is not None:
        from scene.interface_adapters.http.deps import get_description_adapter

        app.dependency_overrides[get_description_adapter] = lambda: adapter
    try:
        with TestClient(app) as client:
            yield client, sf
    finally:
        asyncio.run(engine.dispose())
        with suppress(OSError):
            os.unlink(path)


def _ledger_counters(sf) -> tuple[int, int, list[str]]:
    from db.models import UsageReservation
    from db.models.portal_billing import GlobalUsageAdmissionState
    from recognition.domain.portal_contracts import GLOBAL_USAGE_ADMISSION_STATE_ID

    async def _read() -> tuple[int, int, list[str]]:
        async with sf() as session:
            state = await session.get(GlobalUsageAdmissionState, GLOBAL_USAGE_ADMISSION_STATE_ID)
            rows = list((await session.execute(select(UsageReservation))).scalars())
            assert state is not None
            return int(state.inflight_units), int(state.daily_cost_units), [str(row.status) for row in rows]

    return asyncio.run(_read())


def test_multipart_http_200_commits_usage_db_counters(monkeypatch):
    with _ledger_client(monkeypatch) as (client, sf):
        response = _post_multipart(client)
        inflight, daily, statuses = _ledger_counters(sf)

    assert response.status_code == 200, response.text
    assert statuses == ["committed"]
    assert inflight == 0
    assert daily == 1


def test_http_202_keeps_usage_reserved_in_db(monkeypatch):
    with _ledger_client(monkeypatch) as (client, sf):
        response = _post_run(client, operation_id=OP_A, media_ids=[70, 71])
        inflight, daily, statuses = _ledger_counters(sf)

    assert response.status_code == 202, response.text
    assert statuses == ["reserved"]
    assert inflight == 2
    assert daily == 2


def test_multipart_precompute_failure_does_not_leave_reserved_db_row(monkeypatch):
    from fastapi import HTTPException

    async def _boom(*_args, **_kwargs):
        raise HTTPException(status_code=429, detail={"code": "demo_quota_exceeded"})

    monkeypatch.setattr(describe_mod, "maybe_consume_demo_quota", _boom)
    with _ledger_client(monkeypatch) as (client, sf):
        response = _post_multipart(client)
        inflight, daily, statuses = _ledger_counters(sf)

    assert response.status_code == 429, response.text
    assert "reserved" not in statuses
    assert inflight == 0
    assert daily == 0


def test_multipart_postcompute_failure_accounts_usage_in_db(monkeypatch):
    _BoomAdapter.calls = 0
    with _ledger_client(monkeypatch, adapter=_BoomAdapter()) as (client, sf):
        response = _post_multipart(client)
        inflight, daily, statuses = _ledger_counters(sf)

    assert response.status_code == 502, response.text
    assert _BoomAdapter.calls == 1
    assert statuses == ["committed"]
    assert inflight == 0
    assert daily == 1
