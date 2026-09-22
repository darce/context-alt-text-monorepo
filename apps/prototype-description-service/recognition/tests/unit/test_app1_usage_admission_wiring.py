"""APP-1 usage admission behavior at the HTTP dispatch boundary."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from recognition.application.services.usage_admission_service import (
    AllowanceExceededError,
    UsageAdmissionTimeoutError,
    UsageAdmissionUnavailableError,
    UsageFingerprintConflictError,
)
from recognition.domain.job import JobPhase, JobStatus, JobType
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    get_scan_queue_service_optional,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.usage_admission import (
    admit_usage,
    build_usage_idempotency_key,
    get_usage_admission_service,
)
from recognition.interface_adapters.http.routers import analyze as analyze_router
from recognition.interface_adapters.http.routers import analyze_multipart as multipart_router
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
MEDIA_ID = "22222222-2222-2222-2222-222222222222"


class _FakeAdmission:
    def __init__(self, *, exhausted: bool = False) -> None:
        self.exhausted = exhausted
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
        if self.exhausted:
            raise AllowanceExceededError()
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


def _job_response() -> JobStatusResponse:
    return JobStatusResponse(
        id=str(uuid4()),
        type=JobType.ANALYZE,
        status=JobStatus.PENDING,
        progress=JobProgressResponse(completed=0, total=1, phase=JobPhase.QUEUED),
        started_at=datetime.now(UTC),
        finished_at=None,
    )


def _json_app(admission: _FakeAdmission, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = FastAPI()
    app.include_router(analyze_router.router, prefix="/recognition")
    app.state.usage_admission_service = admission

    async def _none():
        return None

    async def _auth():
        return SimpleNamespace(tenant_claim=None, user_id=None)

    async def _queue():
        return object()

    async def _service():
        return admission

    app.dependency_overrides.update(
        {
            require_auth: _none,
            enforce_rate_limit: _none,
            require_write_access: _auth,
            get_optional_session: _none,
            get_scan_queue_service_optional: _queue,
            enforce_demo_quota: _none,
            get_usage_admission_service: _service,
        }
    )

    async def _schedule(**_kwargs):
        return _job_response()

    monkeypatch.setattr(analyze_router, "_schedule_analysis", _schedule)
    return app


@pytest.mark.asyncio
async def test_admit_usage_keeps_reserved_after_normal_body() -> None:
    admission = _FakeAdmission()
    async with admit_usage(
        admission,
        tenant_id=TENANT_ID,
        idempotency_key="key",
        job_id="job",
        cost_units=2,
    ) as ticket:
        assert ticket is not None
        assert ticket.fence_token == "fence-test"

    assert len(admission.reserves) == 1
    assert admission.commits == []
    assert admission.releases == []


@pytest.mark.asyncio
async def test_admit_usage_releases_when_dispatch_raises() -> None:
    admission = _FakeAdmission()
    with pytest.raises(RuntimeError, match="dispatch failed"):
        async with admit_usage(
            admission,
            tenant_id=TENANT_ID,
            idempotency_key="key",
            job_id=None,
            cost_units=1,
        ):
            raise RuntimeError("dispatch failed")

    assert len(admission.commits) == 0
    assert len(admission.releases) == 1


@pytest.mark.asyncio
async def test_allowance_exhaustion_maps_to_payment_required() -> None:
    admission = _FakeAdmission(exhausted=True)
    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            admission,
            tenant_id=TENANT_ID,
            idempotency_key="key",
            job_id=None,
            cost_units=1,
        ):
            pass

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == {"error": "allowance_exhausted"}


@pytest.mark.asyncio
async def test_absent_service_does_not_call_anything() -> None:
    async with admit_usage(
        None,
        tenant_id=TENANT_ID,
        idempotency_key="key",
        job_id=None,
        cost_units=1,
    ) as ticket:
        assert ticket is None


@pytest.mark.asyncio
async def test_identical_payloads_without_operation_id_are_independently_chargeable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _FakeAdmission()
    app = _json_app(admission, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    payload = {"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/recognition/analyze", json=payload)
        second = await client.post("/recognition/analyze", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert len(admission.reserves) == 2
    assert admission.reserves[0]["operation_id"] != admission.reserves[1]["operation_id"]
    assert admission.reserves[0]["request_fingerprint"] == admission.reserves[1]["request_fingerprint"]
    assert admission.commits == []


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_without_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    app = _json_app(admission, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    payload = {"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]}
    headers = {"Idempotency-Key": "client-op-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/recognition/analyze", json=payload, headers=headers)
        second = await client.post("/recognition/analyze", json=payload, headers=headers)

    assert first.status_code == 202
    assert second.status_code == 202
    assert len(admission.reserves) == 2
    assert admission.reserves[0]["operation_id"] == "client-op-1"
    assert admission.reserves[1]["operation_id"] == "client-op-1"
    assert admission.reserves[0]["request_fingerprint"] == admission.reserves[1]["request_fingerprint"]
    assert admission.commits == []


@pytest.mark.asyncio
async def test_analyze_reserve_uses_pregenerated_job_and_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    app = _json_app(admission, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
            headers={"Idempotency-Key": "client-op-json"},
        )

    assert response.status_code == 202
    assert len(admission.reserves) == 1
    reserved = admission.reserves[0]
    assert reserved["operation_id"] == "client-op-json"
    assert reserved["idempotency_key"] == "client-op-json"
    assert reserved["job_id"] is not None
    UUID(str(reserved["job_id"]))
    assert reserved["request_fingerprint"] != reserved["operation_id"]
    assert reserved["request_fingerprint"] != MEDIA_ID
    assert admission.commits == []


@pytest.mark.asyncio
async def test_service_absent_keeps_analyze_route_available(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    app = _json_app(admission, monkeypatch)

    async def _absent_service():
        return None

    app.dependency_overrides[get_usage_admission_service] = _absent_service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
        )

    assert response.status_code == 202
    assert admission.reserves == []


@pytest.mark.asyncio
async def test_exhausted_analyze_request_returns_402(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission(exhausted=True)
    app = _json_app(admission, monkeypatch)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze",
            json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
        )

    assert response.status_code == 402
    assert response.json()["detail"] == {"error": "allowance_exhausted"}


class _FakeObjectStore:
    def put(self, *, job_id: str, media_id: str, data: bytes) -> str:
        return f"blob://{job_id}/{media_id}"

    def cleanup(self, *, job_id: str) -> None:
        return None

    @contextmanager
    def open(self, _uri: str):
        yield io.BytesIO(b"image")


class _FakeScanQueue:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []

    async def create_scan_job_record(self, *, tenant_id, total, job_id, created_by_user_id):
        self.create_calls.append(
            {
                "tenant_id": tenant_id,
                "total": total,
                "job_id": job_id,
                "created_by_user_id": created_by_user_id,
            }
        )
        return job_id


@pytest.mark.asyncio
async def test_multipart_request_uses_usage_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    app = FastAPI()
    app.include_router(multipart_router.router, prefix="/recognition")
    queue = _FakeScanQueue()

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
        return lambda _tenant: _FakeObjectStore()

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

    async def _noop_background(**_kwargs):
        return None

    monkeypatch.setattr(multipart_router, "chain_populate_and_process", _noop_background)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/recognition/analyze/multipart",
            data={"request": json.dumps({"tenant_id": str(TENANT_ID)})},
            files={"image_1": ("image.png", b"image", "image/png")},
            headers={"Idempotency-Key": "client-op-multipart"},
        )

    assert response.status_code == 202
    assert len(admission.reserves) == 1
    reserved = admission.reserves[0]
    assert reserved["cost_units"] == 1
    assert reserved["operation_id"] == "client-op-multipart"
    assert reserved["job_id"] is not None
    UUID(str(reserved["job_id"]))
    assert reserved["request_fingerprint"] != reserved["operation_id"]
    assert reserved["queue_bytes"] == len(b"image")
    assert admission.commits == []
    assert len(queue.create_calls) == 1
    assert str(queue.create_calls[0]["job_id"]) == str(reserved["job_id"])


def test_build_usage_key_is_order_stable() -> None:
    first = build_usage_idempotency_key(TENANT_ID, ["2", "1"], ["source-2", "source-1"])
    second = build_usage_idempotency_key(TENANT_ID, ["1", "2"], ["source-1", "source-2"])
    assert first == second


class _ConflictAdmission(_FakeAdmission):
    async def reserve(self, tenant_id, **kwargs):
        raise UsageFingerprintConflictError("changed fingerprint")


class _UnavailableAdmission(_FakeAdmission):
    async def reserve(self, tenant_id, **kwargs):
        raise UsageAdmissionUnavailableError("global state missing")


@pytest.mark.asyncio
async def test_fingerprint_conflict_maps_to_conflict() -> None:
    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            _ConflictAdmission(),
            tenant_id=TENANT_ID,
            idempotency_key="key",
            job_id=None,
            cost_units=1,
            operation_id="op-1",
            request_fingerprint="fp-b",
        ):
            pass

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"error": "usage_fingerprint_conflict"}


@pytest.mark.asyncio
async def test_missing_global_state_maps_to_unavailable() -> None:
    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            _UnavailableAdmission(),
            tenant_id=TENANT_ID,
            idempotency_key="key",
            job_id=None,
            cost_units=1,
        ):
            pass

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"error": "usage_admission_unavailable"}


class _TimeoutAdmission:
    def __init__(self) -> None:
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []
        self.rollback_calls = 0
        self._session = self

    async def reserve(self, tenant_id, **kwargs):
        raise UsageAdmissionTimeoutError("usage admission database operation timed out: reserve")

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)

    async def rollback(self) -> None:
        self.rollback_calls += 1


@pytest.mark.asyncio
async def test_reservation_timeout_maps_to_bounded_503_without_dispatch() -> None:
    admission = _TimeoutAdmission()
    dispatched = False
    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            admission,
            tenant_id=TENANT_ID,
            idempotency_key="key",
            job_id="job-timeout",
            cost_units=1,
        ):
            dispatched = True

    assert dispatched is False
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == {"error": "reservation_timeout"}
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1
    assert admission.rollback_calls == 1
    assert admission.commits == []
    assert admission.releases == []
