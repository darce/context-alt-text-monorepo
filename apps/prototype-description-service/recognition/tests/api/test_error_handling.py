"""API error handling tests for security/validation scenarios."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.tests.api.conftest import FakeSession


def test_analyze_maps_insufficient_privilege_to_403(monkeypatch, tenant_id):
    class StubScanService:
        async def analyze_media(self, tenant_id, media_ids, media_sources=None):  # noqa: ANN001
            raise ProgrammingError("stmt", {}, Exception("InsufficientPrivilegeError"))

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    register_exception_handlers(app)

    # Override session to avoid real DB connection
    async def _no_session():
        yield FakeSession()

    def _fake_scan_service_builder():
        def _builder(tenant_id: str):  # noqa: ANN001
            return StubScanService()

        return _builder

    app.dependency_overrides[dependencies.get_session] = _no_session
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    app.dependency_overrides[dependencies.get_scan_service_builder] = _fake_scan_service_builder

    client = TestClient(app)
    resp = client.post(
        "/recognition/analyze",
        json={"tenant_id": tenant_id, "media_items": [{"media_id": 1, "media_url": "http://example.test"}]},
    )

    assert resp.status_code == 403


def test_unhandled_exceptions_return_structured_error(monkeypatch) -> None:
    """Unhandled errors should surface as structured JSON with metadata."""

    class ExplodingJobService:
        async def get_job_status(self, _job_id):  # noqa: ANN001
            raise RuntimeError("boom")

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    register_exception_handlers(app)

    async def _no_session():
        yield FakeSession()

    async def _exploding_job_service():
        return ExplodingJobService()

    app.dependency_overrides[dependencies.get_session] = _no_session
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    app.dependency_overrides[dependencies.get_job_service_dependency] = _exploding_job_service

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/recognition/jobs/job-xyz", headers={"X-Tenant-ID": str(uuid.uuid4())})

    assert resp.status_code == 500
    body = resp.json()
    assert "error" in body
    assert "path" in body
