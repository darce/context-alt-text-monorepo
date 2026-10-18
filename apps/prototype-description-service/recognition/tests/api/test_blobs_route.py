"""Integration test for GET /recognition/blobs/{job_id}/{media_id}.

Verifies the route reads tenant from auth (never from URL), enforces
the per-tenant filesystem prefix via the FilesystemObjectStore, sniffs
a sensible MIME type from the bytes, and returns 403 / 404 / 400 at the
documented boundaries.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image
from starlette.testclient import TestClient

from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.interface_adapters.http.deps.object_store import _settings_default
from recognition.interface_adapters.http.routers.blobs import router

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes-for-tests"
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIFfake-jpeg-bytes"


def _make_png(width: int, height: int, *, color: tuple[int, int, int] = (20, 40, 60)) -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def tenant_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def app_factory(tmp_path: Path):
    """Build an app whose blob_root is a per-test tmp directory."""

    def _build(*, auth: AuthContext) -> tuple[FastAPI, RecognitionSettings]:
        settings = RecognitionSettings()
        settings.blob_root = tmp_path / "blobs"

        app = FastAPI()
        app.include_router(router, prefix="/recognition")
        app.dependency_overrides[require_auth] = lambda: auth
        app.dependency_overrides[_settings_default] = lambda: settings
        return app, settings

    return _build


def _seed_blob(settings: RecognitionSettings, tenant_id: str, job_id: str, media_id: str, data: bytes) -> Path:
    target = settings.blob_root / tenant_id / job_id / f"{media_id}.bin"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_serves_existing_blob_with_sniffed_mime(app_factory, tenant_id: str) -> None:
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, settings = app_factory(auth=auth)
    job_id = str(uuid.uuid4())
    _seed_blob(settings, tenant_id, job_id, "42", PNG_BYTES)

    response = TestClient(app).get(f"/recognition/blobs/{job_id}/42")
    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"


def test_sniffs_jpeg_mime(app_factory, tenant_id: str) -> None:
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, settings = app_factory(auth=auth)
    job_id = str(uuid.uuid4())
    _seed_blob(settings, tenant_id, job_id, "9", JPEG_BYTES)

    response = TestClient(app).get(f"/recognition/blobs/{job_id}/9")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"


def test_serves_face_thumb_crop_as_jpeg(app_factory, tenant_id: str) -> None:
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, settings = app_factory(auth=auth)
    job_id = str(uuid.uuid4())
    _seed_blob(settings, tenant_id, job_id, "7", _make_png(48, 36))

    response = TestClient(app).get(
        f"/recognition/face-thumbs/{job_id}/7",
        params={"x": 5, "y": 6, "width": 12, "height": 10},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    thumbnail = Image.open(io.BytesIO(response.content))
    assert thumbnail.size == (12, 10)


def test_rejects_face_thumb_crop_component_above_max_geometry(app_factory, tenant_id: str) -> None:
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, settings = app_factory(auth=auth)
    job_id = str(uuid.uuid4())
    _seed_blob(settings, tenant_id, job_id, "7", _make_png(48, 36))

    response = TestClient(app).get(
        f"/recognition/face-thumbs/{job_id}/7",
        params={"x": 5, "y": 6, "width": 40_000, "height": 10},
    )

    assert response.status_code == 422


def test_returns_404_when_blob_missing(app_factory, tenant_id: str) -> None:
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, _ = app_factory(auth=auth)

    response = TestClient(app).get(f"/recognition/blobs/{uuid.uuid4()}/missing")
    assert response.status_code == 404


def test_admin_key_without_tenant_claim_is_rejected(app_factory) -> None:
    """Admin keys (auth.tenant_claim is None) must not be allowed to read blobs.

    There is no admin override on this route — tenant binding is the
    whole point. Other tenants' bytes must not be reachable without an
    explicit tenant-scoped key.
    """
    auth = AuthContext(token="admin", tenant_claim=None, is_admin=True, enabled=True)
    app, _ = app_factory(auth=auth)

    response = TestClient(app).get("/recognition/blobs/job/media")
    assert response.status_code == 403


def test_other_tenants_blob_is_unreachable(app_factory, tenant_id: str) -> None:
    """A tenant-A key cannot read tenant-B's bytes even if it knows the path."""
    other_tenant = str(uuid.uuid4())
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, settings = app_factory(auth=auth)
    job_id = str(uuid.uuid4())
    _seed_blob(settings, other_tenant, job_id, "1", PNG_BYTES)  # written under DIFFERENT tenant

    response = TestClient(app).get(f"/recognition/blobs/{job_id}/1")
    # FilesystemObjectStore.open() resolves to the tenant_id's prefix
    # using the auth-bound tenant; the file does not exist there, so 404.
    assert response.status_code == 404


@pytest.mark.parametrize("bad_segment", ["..", ".", ""])
def test_rejects_traversal_path_segments(app_factory, tenant_id: str, bad_segment: str) -> None:
    """Defense in depth: dotted/empty segments are rejected before the
    filesystem layer can see them."""
    auth = AuthContext(token="t", tenant_claim=tenant_id, enabled=True)
    app, _ = app_factory(auth=auth)

    # An empty segment in the URL path collapses to a 404 from FastAPI's
    # routing rather than reaching the handler; the dotted-segment cases
    # reach the handler and get a 400.
    response = TestClient(app).get(f"/recognition/blobs/{bad_segment}/x")
    assert response.status_code in {400, 404}
