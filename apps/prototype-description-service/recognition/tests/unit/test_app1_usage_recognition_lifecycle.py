"""Route, side-effect, and replay coverage for recognition usage admission."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, status

from recognition.application.services.usage_admission_service import UsageFingerprintConflictError
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import (
    get_job_service_dependency,
    get_optional_session,
    get_scan_queue_service_optional,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.usage_admission import (
    admit_usage,
    get_usage_admission_service,
)
from recognition.interface_adapters.http.routers import analyze as analyze_router
from recognition.interface_adapters.http.routers import analyze_multipart as multipart_router

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
MEDIA_ID = "22222222-2222-2222-2222-222222222222"
OTHER_MEDIA_ID = "33333333-3333-3333-3333-333333333333"


class _FakeAdmission:
    def __init__(self) -> None:
        self.reserves: list[dict[str, object]] = []
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []
        self._tickets: dict[tuple[object, str], UsageTicket] = {}

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
        resolved_operation = operation_id or idempotency_key
        resolved_fingerprint = request_fingerprint or idempotency_key
        existing = self._tickets.get((tenant_id, resolved_operation))
        if existing is not None:
            if existing.request_fingerprint != resolved_fingerprint:
                raise UsageFingerprintConflictError("changed fingerprint")
            return existing
        ticket = UsageTicket(
            uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=resolved_operation,
            request_fingerprint=resolved_fingerprint,
            job_id=job_id,
            fence_token="fence-test",
        )
        self._tickets[(tenant_id, resolved_operation)] = ticket
        return ticket

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)


class _CountingScanQueue:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []

    async def create_scan_job_record(self, *, tenant_id, total, created_by_user_id=None, job_id=None):
        self.create_calls.append(
            {
                "tenant_id": tenant_id,
                "total": total,
                "job_id": job_id,
                "created_by_user_id": created_by_user_id,
            }
        )
        return job_id if job_id is not None else uuid4()


class _FakeObjectStore:
    def __init__(self) -> None:
        self.puts: list[dict[str, object]] = []

    def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
        self.puts.append({"job_id": job_id, "media_id": media_id, "data": data})
        return f"blob://{job_id}/{media_id}"

    def cleanup(self, *, job_id: str) -> None:
        return None

    @contextmanager
    def open(self, _uri: str):
        yield io.BytesIO(b"image")


class _JobService:
    async def get_job_status(self, _job_id: str):
        return None


def _json_lifecycle_app(
    admission: _FakeAdmission,
    queue: _CountingScanQueue,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant_claim: str | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(analyze_router.router, prefix="/recognition")
    app.state.usage_admission_service = admission
    dispatch_calls: list[dict[str, object]] = []
    app.state.dispatch_calls = dispatch_calls

    async def _none():
        return None

    async def _auth():
        return SimpleNamespace(tenant_claim=tenant_claim, user_id=None)

    async def _queue():
        return queue

    async def _service():
        return admission

    async def _jobs():
        return _JobService()

    app.dependency_overrides.update(
        {
            require_auth: _none,
            enforce_rate_limit: _none,
            require_write_access: _auth,
            get_optional_session: _none,
            get_scan_queue_service_optional: _queue,
            enforce_demo_quota: _none,
            get_usage_admission_service: _service,
            get_job_service_dependency: _jobs,
        }
    )

    async def _noop_background(**kwargs):
        dispatch_calls.append(kwargs)
        return None

    monkeypatch.setattr(analyze_router, "chain_populate_and_process", _noop_background)
    return app


def _multipart_lifecycle_app(
    admission: _FakeAdmission,
    queue: _CountingScanQueue,
    store: _FakeObjectStore,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    app = FastAPI()
    app.include_router(multipart_router.router, prefix="/recognition")
    app.state.usage_admission_service = admission
    dispatch_calls: list[dict[str, object]] = []
    app.state.dispatch_calls = dispatch_calls

    async def _auth():
        return SimpleNamespace(tenant_claim=None, user_id=None)

    async def _session():
        return None

    async def _queue():
        return queue

    async def _none():
        return None

    async def _service():
        return admission

    async def _store_factory():
        return lambda _tenant: store

    app.dependency_overrides.update(
        {
            require_write_access: _auth,
            get_optional_session: _session,
            get_scan_queue_service_optional: _queue,
            enforce_demo_quota: _none,
            get_usage_admission_service: _service,
            multipart_router.get_object_store_factory_for_request: _store_factory,
        }
    )

    async def _noop_background(**kwargs):
        dispatch_calls.append(kwargs)
        return None

    monkeypatch.setattr(multipart_router, "chain_populate_and_process", _noop_background)
    return app


@pytest.mark.asyncio
async def test_same_operation_replays_same_job_without_second_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch)
    payload = {"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]}
    headers = {"Idempotency-Key": "replay-op"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/recognition/analyze", json=payload, headers=headers)
        second = await client.post("/recognition/analyze", json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["id"] == str(admission.reserves[0]["job_id"])
    assert len(queue.create_calls) == 1
    assert len(app.state.dispatch_calls) == 1
    assert admission.commits == []
    assert admission.releases == []


@pytest.mark.asyncio
async def test_same_operation_changed_media_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch)
    headers = {"Idempotency-Key": "conflict-op"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
            headers=headers,
        )
        second = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [OTHER_MEDIA_ID]},
            headers=headers,
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == {"error": "usage_fingerprint_conflict"}
    assert len(queue.create_calls) == 1
    assert admission.commits == []


@pytest.mark.asyncio
async def test_same_payload_new_operation_is_independently_chargeable(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch)
    payload = {"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/recognition/analyze",
            json=payload,
            headers={"Idempotency-Key": "op-a"},
        )
        second = await client.post(
            "/recognition/analyze",
            json=payload,
            headers={"Idempotency-Key": "op-b"},
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert len(queue.create_calls) == 2
    assert admission.reserves[0]["request_fingerprint"] == admission.reserves[1]["request_fingerprint"]
    assert admission.reserves[0]["operation_id"] == "op-a"
    assert admission.reserves[1]["operation_id"] == "op-b"


@pytest.mark.asyncio
async def test_envelope_operation_id_is_used_and_not_source_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze",
            json={
                "tenant_id": str(TENANT_ID),
                "media_ids": [MEDIA_ID],
                "operation_id": "envelope-op",
            },
        )

    assert response.status_code == 202
    reserved = admission.reserves[0]
    assert reserved["operation_id"] == "envelope-op"
    assert reserved["idempotency_key"] == "envelope-op"
    assert reserved["request_fingerprint"] != "envelope-op"
    assert MEDIA_ID not in str(reserved["operation_id"])


@pytest.mark.asyncio
async def test_tenant_mismatch_rejects_before_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch, tenant_claim=str(uuid4()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
            headers={"Idempotency-Key": "tenant-mismatch"},
        )

    assert response.status_code == 403
    assert admission.reserves == []
    assert queue.create_calls == []


@pytest.mark.asyncio
async def test_get_job_status_does_not_reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    app = _json_lifecycle_app(admission, queue, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
            headers={"Idempotency-Key": "status-op"},
        )
        status_response = await client.get(f"/recognition/jobs/{created.json()['id']}")

    assert created.status_code == 202
    assert status_response.status_code == 404
    assert len(admission.reserves) == 1
    assert admission.commits == []


@pytest.mark.asyncio
async def test_queue_refusal_before_dispatch_releases() -> None:
    admission = _FakeAdmission()
    job_id = uuid4()

    class _RefuseQueue:
        async def create_scan_job_record(self, **_kwargs):
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")

    class _Background:
        def add_task(self, *_args, **_kwargs) -> None:
            raise AssertionError("dispatch must not run after queue refusal")

    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            admission,
            tenant_id=TENANT_ID,
            idempotency_key="refuse-op",
            job_id=str(job_id),
            cost_units=1,
            operation_id="refuse-op",
            request_fingerprint="fp",
        ):
            await analyze_router._schedule_analysis(
                background_tasks=_Background(),
                session=None,
                scan_queue=_RefuseQueue(),
                tenant_uuid=TENANT_ID,
                media_items=[(1, "https://example.test/a.jpg")],
                media_ids=[MEDIA_ID],
                media_sources=["https://example.test/a.jpg"],
                inline_processing=False,
                auth=None,
                job_id=job_id,
            )

    assert exc_info.value.status_code == 503
    assert len(admission.releases) == 1
    assert admission.commits == []


@pytest.mark.asyncio
async def test_committed_job_does_not_release_when_response_fails() -> None:
    admission = _FakeAdmission()
    job_id = uuid4()
    queue = _CountingScanQueue()

    class _BoomBackground:
        def add_task(self, *_args, **_kwargs) -> None:
            raise RuntimeError("response failed")

    async with admit_usage(
        admission,
        tenant_id=TENANT_ID,
        idempotency_key="persist-op",
        job_id=str(job_id),
        cost_units=1,
        operation_id="persist-op",
        request_fingerprint="fp",
    ):
        response = await analyze_router._schedule_analysis(
            background_tasks=_BoomBackground(),
            session=None,
            scan_queue=queue,
            tenant_uuid=TENANT_ID,
            media_items=[(1, "https://example.test/a.jpg")],
            media_ids=[MEDIA_ID],
            media_sources=["https://example.test/a.jpg"],
            inline_processing=False,
            auth=None,
            job_id=job_id,
        )

    assert response.id == str(job_id)
    assert len(queue.create_calls) == 1
    assert admission.releases == []
    assert admission.commits == []


@pytest.mark.asyncio
async def test_multipart_replay_skips_second_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    store = _FakeObjectStore()
    app = _multipart_lifecycle_app(admission, queue, store, monkeypatch)
    headers = {"Idempotency-Key": "multipart-replay"}
    form = {
        "data": {"request": json.dumps({"tenant_id": str(TENANT_ID)})},
        "files": {"image_1": ("image.png", b"image-bytes", "image/png")},
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/recognition/analyze/multipart", headers=headers, **form)
        second = await client.post(
            "/recognition/analyze/multipart",
            headers=headers,
            data={"request": json.dumps({"tenant_id": str(TENANT_ID)})},
            files={"image_1": ("image.png", b"image-bytes", "image/png")},
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(queue.create_calls) == 1
    assert len(store.puts) == 1
    assert len(app.state.dispatch_calls) == 1
    assert admission.commits == []


@pytest.mark.asyncio
async def test_multipart_changed_bytes_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    queue = _CountingScanQueue()
    store = _FakeObjectStore()
    app = _multipart_lifecycle_app(admission, queue, store, monkeypatch)
    headers = {"Idempotency-Key": "multipart-conflict"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/recognition/analyze/multipart",
            headers=headers,
            data={"request": json.dumps({"tenant_id": str(TENANT_ID)})},
            files={"image_1": ("image.png", b"image-one", "image/png")},
        )
        second = await client.post(
            "/recognition/analyze/multipart",
            headers=headers,
            data={"request": json.dumps({"tenant_id": str(TENANT_ID)})},
            files={"image_1": ("image.png", b"image-two", "image/png")},
        )

    assert first.status_code == 202
    assert second.status_code == 409
    assert len(queue.create_calls) == 1
    assert len(store.puts) == 1
