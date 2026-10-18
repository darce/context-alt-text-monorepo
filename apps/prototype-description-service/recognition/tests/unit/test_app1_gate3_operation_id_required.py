"""Metered analyze requests must carry a client operation key before dispatch."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import HTTPException

from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from recognition.interface_adapters.http.routers import analyze, analyze_multipart
from recognition.tests.unit.test_app1_usage_admission_wiring import (
    MEDIA_ID,
    TENANT_ID,
    _FakeAdmission,
    _json_app,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("multipart", [False, True])
@pytest.mark.parametrize("metered", [False, True])
@pytest.mark.parametrize("key_source", [None, "header", "operation_id", "idempotency_key"])
async def test_operation_key_required_before_reservation_and_job_creation(
    monkeypatch: pytest.MonkeyPatch, multipart: bool, metered: bool, key_source: str | None
) -> None:
    admission = _FakeAdmission()
    app = _json_app(admission, monkeypatch)
    app.include_router(analyze_multipart.router, prefix="/recognition")
    if not metered:
        app.dependency_overrides[get_usage_admission_service] = lambda: None
    jobs: dict[str, object] = {}

    async def persist(**kwargs):
        job_id = kwargs.get("job_id", kwargs.get("pre_generated_job_id"))
        if not kwargs.get("existing_job", False):
            assert str(job_id) not in jobs
            jobs[str(job_id)] = kwargs
        return analyze.queued_analyze_job_response(job_id, 1)

    monkeypatch.setattr(analyze, "_schedule_analysis", persist)
    monkeypatch.setattr(analyze_multipart, "_persist_and_dispatch_multipart", persist)
    app.dependency_overrides[analyze_multipart.get_object_store_factory_for_request] = lambda: object()
    envelope = {"tenant_id": str(TENANT_ID)}
    headers = {}
    if key_source == "header":
        headers["Idempotency-Key"] = "logical-action-1"
    elif key_source:
        envelope[key_source] = "logical-action-1"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for _ in range(2):
            if multipart:
                response = await client.post(
                    "/recognition/analyze/multipart",
                    headers=headers,
                    data={"request": json.dumps(envelope)},
                    files={"image_1": ("image.png", b"image", "image/png")},
                )
            else:
                response = await client.post(
                    "/recognition/analyze", headers=headers, json={**envelope, "media_ids": [MEDIA_ID]}
                )
            if metered and key_source is None:
                assert response.status_code == 400, response.text
                problem = response.json()["detail"]
                assert problem["status"] == 400
                assert problem["type"] == "https://context-alt-text.dev/problems/idempotency-key-required"
                assert "Idempotency-Key" in problem["detail"]
                assert admission.reserves == []
                assert jobs == {}
            else:
                assert response.status_code == 202, response.text

    if metered and key_source:
        # reserve is called for each retry; its unique tenant/key ticket is reused.
        assert len(admission._tickets) == 1
        assert len(jobs) == 1
        assert {call["operation_id"] for call in admission.reserves} == {"logical-action-1"}
    elif not metered:
        assert admission.reserves == []
        assert len(jobs) == 2


@pytest.mark.parametrize("key", ["bad/key", "x" * 129])
def test_invalid_operation_key_still_returns_422(key: str) -> None:
    with pytest.raises(HTTPException) as exc:
        analyze.resolve_analyze_operation_id(header_value=key, required=True)
    assert exc.value.status_code == 422
