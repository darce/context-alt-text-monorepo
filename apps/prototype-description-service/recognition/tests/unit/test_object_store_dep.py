"""Tests for the FastAPI ObjectStore dependency provider (E15-11 Slice 1.4b).

The multipart route depends on a request-scoped ObjectStore bound to
``auth.tenant_claim``. The provider lives separately from the route so it
can be unit-tested without spinning up the full app.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from recognition.application.storage import FilesystemObjectStore
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.object_store import (
    get_object_store,
)


def _auth(tenant_claim: str | None) -> AuthContext:
    return AuthContext(token="t", tenant_claim=tenant_claim)


@pytest.fixture
def settings_with_blob_root(tmp_path: Path) -> RecognitionSettings:
    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"
    return settings


def test_get_object_store_returns_tenant_bound_filesystem_store(
    settings_with_blob_root: RecognitionSettings,
) -> None:
    tenant = str(uuid.uuid4())
    store = get_object_store(auth=_auth(tenant), settings=settings_with_blob_root)

    assert isinstance(store, FilesystemObjectStore)
    assert store.tenant_id == tenant
    assert store.root.resolve() == settings_with_blob_root.blob_root.resolve()


def test_get_object_store_creates_root_if_missing(tmp_path: Path) -> None:
    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "not-yet-created"
    assert not settings.blob_root.exists()

    store = get_object_store(auth=_auth(str(uuid.uuid4())), settings=settings)
    # put requires an existing root; provider must have created it
    uri = store.put(job_id=str(uuid.uuid4()), media_id="1", data=b"x")
    assert uri.startswith("file://")
    assert settings.blob_root.exists()


def test_get_object_store_rejects_missing_tenant_claim(
    settings_with_blob_root: RecognitionSettings,
) -> None:
    """An unauthenticated request must not be able to mint an ObjectStore;
    require_auth gates the route, but defense in depth: the provider
    refuses an empty tenant_claim so a misconfigured route cannot leak
    cross-tenant access through a 'shared' store."""
    with pytest.raises(HTTPException) as excinfo:
        get_object_store(auth=_auth(None), settings=settings_with_blob_root)
    assert excinfo.value.status_code in (401, 403)


def test_each_call_returns_a_fresh_store(
    settings_with_blob_root: RecognitionSettings,
) -> None:
    """Per-request scoping: two calls must not share state — the second
    request might be for a different tenant."""
    store_a = get_object_store(auth=_auth(str(uuid.uuid4())), settings=settings_with_blob_root)
    store_b = get_object_store(auth=_auth(str(uuid.uuid4())), settings=settings_with_blob_root)
    assert store_a is not store_b
    assert store_a.tenant_id != store_b.tenant_id
