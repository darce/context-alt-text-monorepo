"""Integration test for POST /recognition/analyze/multipart (E15-11 Slice 1.4d).

Wires the new route into a minimal FastAPI app with overrides for auth,
session, scan_queue, settings, and ObjectStore. Verifies the route accepts
a multipart submission, persists each image part through ObjectStore.put,
calls scan_queue.create_scan_job_record with the pre-generated job_id,
and returns 202 with the matching id. Negative paths assert the 422 / 400
/ 403 boundary checks at the route level.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from recognition.application.storage import FilesystemObjectStore
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.dependencies import (
    get_optional_session,
    get_scan_queue_service_optional,
    require_write_access,
)
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.object_store import (
    _settings_default,
    get_object_store_for_request,
)
from recognition.interface_adapters.http.routers.analyze_multipart import router

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-tests"


class _FakeScanQueue:
    """Captures the create_scan_job_record call so the test can assert on it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_scan_job_record(
        self,
        *,
        tenant_id: uuid.UUID,
        total: int,
        created_by_user_id: int | None = None,
        job_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        # The multipart route must pass the pre-generated job_id.
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "total": total,
                "job_id": job_id,
                "created_by_user_id": created_by_user_id,
            }
        )
        assert job_id is not None, "multipart route must pre-generate job_id"
        return job_id


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def app_with_overrides(tmp_path: Path, tenant_id: str):
    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fake_queue = _FakeScanQueue()

    fastapi_app = FastAPI()
    fastapi_app.include_router(router, prefix="/recognition")

    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=tenant_id)
    fastapi_app.dependency_overrides[get_optional_session] = lambda: None
    fastapi_app.dependency_overrides[get_scan_queue_service_optional] = lambda: fake_queue
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    return fastapi_app, fake_queue, settings


def _multipart_submission(tenant_id: str) -> dict:
    """Build a multipart submission with one image part and a JSON request part."""
    return {
        "files": [
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
            ("image_42", ("a.png", PNG_BYTES, "image/png")),
        ],
    }


def test_multipart_happy_path_returns_202_and_stores_blob(app_with_overrides, tenant_id: str) -> None:
    app, queue, settings = app_with_overrides
    client = TestClient(app)

    response = client.post("/recognition/analyze/multipart", **_multipart_submission(tenant_id))
    assert response.status_code == 202, response.text
    body = response.json()
    job_id = body["id"]
    assert uuid.UUID(job_id), "response id must be a UUID"

    # scan_queue was called exactly once with the pre-generated job_id
    assert len(queue.calls) == 1
    call = queue.calls[0]
    assert str(call["tenant_id"]) == tenant_id
    assert call["total"] == 1
    assert str(call["job_id"]) == job_id

    # Blob landed under <blob_root>/<tenant>/<job_id>/42.bin
    expected = settings.blob_root / tenant_id / job_id / "42.bin"
    assert expected.is_file()
    assert expected.read_bytes() == PNG_BYTES


def test_multipart_rejects_when_request_part_missing(app_with_overrides, tenant_id: str) -> None:
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)

    response = client.post(
        "/recognition/analyze/multipart",
        files=[("image_1", ("a.png", PNG_BYTES, "image/png"))],
    )
    assert response.status_code == 400


def test_multipart_rejects_when_no_image_parts(app_with_overrides, tenant_id: str) -> None:
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)

    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
        ],
    )
    assert response.status_code == 422


def test_multipart_rejects_tenant_mismatch(app_with_overrides, tenant_id: str) -> None:
    """auth.tenant_claim from the override must match the tenant_id in the
    request envelope. A mismatch is 403 — defends against a token issued
    for tenant A submitting work that claims to be tenant B's."""
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)
    other_tenant = str(uuid.uuid4())

    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": other_tenant}), "application/json"),
            ),
            ("image_1", ("a.png", PNG_BYTES, "image/png")),
        ],
    )
    assert response.status_code == 403


def test_multipart_rejects_unsupported_mime(app_with_overrides, tenant_id: str) -> None:
    """The route delegates to multipart_to_media_items which raises 415 for
    a disallowed MIME type. Verify the error surfaces via the route."""
    app, _queue, _settings = app_with_overrides
    client = TestClient(app)
    response = client.post(
        "/recognition/analyze/multipart",
        files=[
            (
                "request",
                ("request.json", json.dumps({"tenant_id": tenant_id}), "application/json"),
            ),
            ("image_1", ("a.gif", b"GIF89a-fake", "image/gif")),
        ],
    )
    assert response.status_code == 415
