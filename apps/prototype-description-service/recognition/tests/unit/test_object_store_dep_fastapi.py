"""FastAPI-resolution test for the ObjectStore DI provider (E15-11-BR-03).

The wrapper get_object_store_for_request was previously a placeholder that
threw on every request because the auth dependency was a lambda raising
RuntimeError. This test resolves the dependency through FastAPI's DI
machinery via TestClient + dependency_overrides, proving the wrapper
binds to the route's real auth + settings providers.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from starlette.testclient import TestClient

from recognition.application.storage import FilesystemObjectStore, ObjectStore
from recognition.config.settings import RecognitionSettings
from recognition.interface_adapters.http.dependencies import require_write_access
from recognition.interface_adapters.http.deps.auth import AuthContext
from recognition.interface_adapters.http.deps.object_store import (
    _settings_default,
    get_object_store_for_request,
)


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    settings = RecognitionSettings()
    settings.blob_root = tmp_path / "blobs"

    fastapi_app = FastAPI()

    @fastapi_app.get("/probe-store")
    def probe(store: ObjectStore = Depends(get_object_store_for_request)) -> dict:
        assert isinstance(store, FilesystemObjectStore)
        return {
            "tenant_id": store.tenant_id,
            "root": str(store.root),
        }

    fastapi_app.dependency_overrides[require_write_access] = lambda: AuthContext(
        token="t", tenant_claim="tenant-from-auth-override"
    )
    fastapi_app.dependency_overrides[_settings_default] = lambda: settings

    return fastapi_app


def test_get_object_store_for_request_resolves_through_fastapi(app: FastAPI, tmp_path: Path) -> None:
    """Critical regression for BR-03: hitting a route that depends on
    get_object_store_for_request must NOT 500 due to a placeholder
    auth dependency. The wrapper must bind to require_write_access (or
    its override) and produce a tenant-bound ObjectStore."""
    client = TestClient(app)
    response = client.get("/probe-store")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_id"] == "tenant-from-auth-override"
    assert Path(body["root"]).resolve() == (tmp_path / "blobs").resolve()


def test_get_object_store_for_request_returns_distinct_instance_per_request(
    app: FastAPI,
) -> None:
    """Two requests must each resolve a fresh dependency. We verify by
    swapping the auth override between calls and confirming the second
    store binds to the new tenant."""
    client = TestClient(app)
    first = client.get("/probe-store").json()

    new_tenant = str(uuid.uuid4())
    app.dependency_overrides[require_write_access] = lambda: AuthContext(token="t", tenant_claim=new_tenant)

    second = client.get("/probe-store").json()
    assert first["tenant_id"] != second["tenant_id"]
    assert second["tenant_id"] == new_tenant
