"""Regression coverage for one usage reservation per analyze request."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from recognition.domain.job import JobPhase, JobStatus, JobType
from recognition.interface_adapters.http.deps import (
    get_optional_session,
    get_scan_queue_service_optional,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.object_store import get_object_store_factory_for_request
from recognition.interface_adapters.http.deps import portal_composition
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.usage_admission import (
    admit_usage,
    get_usage_admission_service as get_handler_usage_admission_service,
)
from recognition.interface_adapters.http.routers import analyze, analyze_multipart
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse
from recognition.infrastructure.repositories.usage_repository import ExpiredUsageReservationError

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
MEDIA_ID = "22222222-2222-2222-2222-222222222222"


class _AdmissionStub:
    def __init__(self) -> None:
        self.reservations: list[dict[str, object]] = []
        self.ticket = SimpleNamespace(job_id=None)

    async def reserve(self, tenant_id: UUID, **kwargs: object) -> object:
        self.reservations.append({"tenant_id": tenant_id, **kwargs})
        return self.ticket

    async def commit(self, _ticket: object) -> None:
        return None

    async def release(self, _ticket: object) -> None:
        return None


def _job_response() -> JobStatusResponse:
    return JobStatusResponse(
        id="33333333-3333-3333-3333-333333333333",
        type=JobType.ANALYZE,
        status=JobStatus.PENDING,
        progress=JobProgressResponse(completed=0, total=1, phase=JobPhase.QUEUED),
        started_at=datetime.now(UTC),
        finished_at=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("multipart", (False, True))
async def test_beta_admission_reserves_once_per_analyze_request(
    monkeypatch: pytest.MonkeyPatch,
    multipart: bool,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    monkeypatch.setenv("RECOGNITION_BETA_ADMISSION_ENABLED", "1")
    monkeypatch.delenv("RECOGNITION_PORTAL_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_ENABLED", raising=False)
    monkeypatch.delenv("RECOGNITION_ADMIN_TOKEN", raising=False)

    from api.main import create_app

    app = create_app()
    admission = _AdmissionStub()

    async def _none() -> None:
        return None

    async def _auth() -> SimpleNamespace:
        return SimpleNamespace(tenant_claim=str(TENANT_ID), user_id=None)

    async def _service() -> _AdmissionStub:
        return admission

    async def _object_store_factory() -> object:
        return lambda _tenant_id: object()

    app.dependency_overrides.update(
        {
            require_auth: _none,
            require_write_access: _auth,
            enforce_rate_limit: _none,
            enforce_demo_quota: _none,
            get_optional_session: _none,
            get_scan_queue_service_optional: _none,
            get_handler_usage_admission_service: _service,
            get_object_store_factory_for_request: _object_store_factory,
        }
    )
    # The removed route dependency had a separate service resolver. Override it
    # dynamically so this test reproduces the merged tree before that layer is
    # deleted while remaining valid once the resolver is gone.
    legacy_service_dependency = getattr(portal_composition, "get_usage_admission_service", None)
    if legacy_service_dependency is not None:
        app.dependency_overrides[legacy_service_dependency] = _service

    async def _schedule_analysis(**_kwargs: object) -> JobStatusResponse:
        return _job_response()

    async def _persist_and_dispatch_multipart(**_kwargs: object) -> JobStatusResponse:
        return _job_response()

    monkeypatch.setattr(analyze, "_schedule_analysis", _schedule_analysis)
    monkeypatch.setattr(analyze_multipart, "_persist_and_dispatch_multipart", _persist_and_dispatch_multipart)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = {"Idempotency-Key": "single-admission-test"}
        if multipart:
            response = await client.post(
                "/recognition/analyze/multipart",
                headers=headers,
                data={"request": json.dumps({"tenant_id": str(TENANT_ID)})},
                files={"image_1": ("image.png", b"image-bytes", "image/png")},
            )
        else:
            response = await client.post(
                "/recognition/analyze",
                headers=headers,
                json={"tenant_id": str(TENANT_ID), "media_ids": [MEDIA_ID]},
            )

    assert response.status_code == 202, response.text
    assert len(admission.reservations) == 1


@pytest.mark.asyncio
async def test_expired_usage_reservation_maps_to_conflict() -> None:
    class _ExpiredReservationService(_AdmissionStub):
        async def reserve(self, _tenant_id: UUID, **_kwargs: object) -> object:
            raise ExpiredUsageReservationError("expired key")

    service = _ExpiredReservationService()
    with pytest.raises(HTTPException) as exc_info:
        async with admit_usage(
            service,
            tenant_id=TENANT_ID,
            idempotency_key="expired-key",
            job_id=None,
            cost_units=1,
        ):
            pytest.fail("an expired reservation must not reach dispatch")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"error": "usage_reservation_expired"}


@pytest.mark.asyncio
async def test_stalled_multipart_body_returns_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analyze_multipart, "_MULTIPART_IDLE_TIMEOUT_S", 0.01)

    async def _stalled_receive() -> dict[str, object]:
        await asyncio.Event().wait()
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/recognition/analyze/multipart",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive=_stalled_receive,
    )

    with pytest.raises(HTTPException) as exc_info:
        await asyncio.wait_for(analyze_multipart._parse_multipart_form(request), timeout=1)

    assert exc_info.value.status_code == 408
    assert exc_info.value.detail == "multipart upload timed out"


@pytest.mark.asyncio
async def test_multipart_body_with_progress_can_exceed_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    idle_timeout = 0.1
    monkeypatch.setattr(analyze_multipart, "_MULTIPART_IDLE_TIMEOUT_S", idle_timeout)
    body = b'--test\r\nContent-Disposition: form-data; name="request"\r\n\r\n{}\r\n--test--\r\n'
    chunks = [body[index : index + 8] for index in range(0, len(body), 8)]

    async def _progressing_receive() -> dict[str, object]:
        await asyncio.sleep(0.02)
        chunk = chunks.pop(0)
        return {"type": "http.request", "body": chunk, "more_body": bool(chunks)}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/recognition/analyze/multipart",
            "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive=_progressing_receive,
    )

    started = asyncio.get_running_loop().time()
    form = await asyncio.wait_for(analyze_multipart._parse_multipart_form(request), timeout=1)
    elapsed = asyncio.get_running_loop().time() - started

    try:
        assert elapsed > idle_timeout
        assert form.get("request") == "{}"
    finally:
        await form.close()
