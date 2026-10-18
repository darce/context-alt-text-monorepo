"""Input validation tests (TDD - expected to fail until validation is enforced)."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession, FakeSuggestionService, seed_cluster
from recognition.tests.fakes import FakeClusterService


def _client(fake_cluster_service: FakeClusterService, fake_suggestion_service: FakeSuggestionService) -> TestClient:
    """Build a TestClient with faked services (no real DB)."""
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return fake_cluster_service

        return _build

    async def suggestion_dep(session=None, tenant_id=None):  # noqa: ANN001
        return fake_suggestion_service

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    app.dependency_overrides[dependencies.get_suggestion_service] = suggestion_dep
    return TestClient(app)


def test_invalid_identity_id_returns_400() -> None:
    client = _client(FakeClusterService(), FakeSuggestionService())
    tenant_id = str(uuid.uuid4())

    resp = client.get(
        "/recognition/identities/not-a-valid-id/suggestions",
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 400


def test_paging_limit_above_max_returns_400() -> None:
    client = _client(FakeClusterService(), FakeSuggestionService())
    tenant_id = str(uuid.uuid4())

    resp = client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"limit": 501},  # max_page_size is 500
    )

    assert resp.status_code == 400


def test_negative_offset_returns_400() -> None:
    client = _client(FakeClusterService(), FakeSuggestionService())
    tenant_id = str(uuid.uuid4())

    resp = client.get(
        "/recognition/suggestions",
        headers={"X-Tenant-ID": tenant_id},
        params={"offset": -1},
    )

    assert resp.status_code == 400


def test_cluster_label_rejects_html() -> None:
    fake_cluster_service = FakeClusterService()
    client = _client(fake_cluster_service, FakeSuggestionService())
    tenant_id = str(uuid.uuid4())
    cluster = seed_cluster(fake_cluster_service, tenant_id, label="safe")

    resp = client.patch(
        f"/recognition/clusters/{cluster.id}",
        headers={"X-Tenant-ID": tenant_id},
        json={"tenant_id": tenant_id, "label": "<script>alert(1)</script>"},
    )

    assert resp.status_code == 400
