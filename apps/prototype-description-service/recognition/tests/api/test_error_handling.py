"""API error handling tests for security/validation scenarios."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.exception_handlers import register_exception_handlers
from recognition.tests.api.conftest import FakeSession


def test_analyze_maps_insufficient_privilege_to_403(monkeypatch, tenant_id):
    class ExplodingScanQueue:
        async def create_scan_job_record(self, **_kwargs):  # noqa: ANN001
            raise ProgrammingError("stmt", {}, Exception("InsufficientPrivilegeError"))

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    register_exception_handlers(app)

    # Override session to avoid real DB connection
    async def _no_session():
        yield FakeSession()

    app.dependency_overrides[dependencies.get_session] = _no_session
    app.dependency_overrides[dependencies.get_optional_session] = _no_session
    app.dependency_overrides[dependencies.get_scan_queue_service] = lambda: ExplodingScanQueue()
    app.dependency_overrides[dependencies.get_scan_queue_service_optional] = lambda: ExplodingScanQueue()

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
    assert body["error"] == "internal_server_error"
    assert body["path"] == "http://testserver/recognition/jobs/job-xyz"
    assert "correlation_id" in body
    assert "message" not in body


def test_pool_exhaustion_returns_retryable_503() -> None:
    """Pool checkout timeouts should surface as retryable 503 responses."""

    class ExplodingJobService:
        async def get_job_status(self, _job_id):  # noqa: ANN001
            raise PoolTimeoutError("QueuePool limit reached")

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

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "5"
    body = resp.json()
    assert body["error"] == "database_unavailable"
    assert body["path"] == "http://testserver/recognition/jobs/job-xyz"
    assert "correlation_id" in body
    assert "message" not in body


def test_integrity_fallback_hides_raw_error_details() -> None:
    """Non-duplicate integrity failures should not leak raw DB details."""

    class ExplodingJobService:
        async def get_job_status(self, _job_id):  # noqa: ANN001
            raise IntegrityError("insert into sensitive_table", {}, Exception("foreign key violation"))

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
    assert body["error"] == "integrity_error"
    assert body["path"] == "http://testserver/recognition/jobs/job-xyz"
    assert "correlation_id" in body
    assert "message" not in body
