"""API dependency override tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession


def test_clusters_router_respects_dependency_override(api_client, tenant_id, fake_cluster_service) -> None:
    resp = api_client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert any(call["method"] == "cluster_unclustered_identities" for call in fake_cluster_service.calls)


def test_clusters_router_invokes_cluster_service_dependency(tenant_id) -> None:
    """Default dependency should call build_cluster_service with request tenant and session."""
    called: dict[str, object] = {}

    def fake_cluster_service_builder():
        async def _builder(dep_tenant_id: str):
            called["tenant_id"] = dep_tenant_id

            class StubService:
                async def cluster_unclustered_identities(self, invoked_tenant_id: str):
                    called["invoke_tenant"] = invoked_tenant_id
                    dt = __import__("datetime")
                    now = dt.datetime.now(tz=dt.UTC)
                    return type(
                        "Result",
                        (),
                        {
                            "job_id": str(uuid.uuid4()),
                            "started_at": now,
                            "finished_at": now,
                            "completed": 0,
                            "total": 0,
                        },
                    )()

            return StubService()

        return _builder

    async def _session_override():
        yield FakeSession()

    async def fake_job_service_dep():
        from recognition.tests.fakes import FakeJobService

        return FakeJobService()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_cluster_service_builder] = fake_cluster_service_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service] = fake_job_service_dep

    client = TestClient(app)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert resp.json()["type"] == "clustering"
    assert called.get("tenant_id") == tenant_id
    assert called.get("invoke_tenant") == tenant_id


def test_clusters_router_does_not_resolve_scan_service_for_clustering_jobs(tenant_id) -> None:
    """Clustering job creation should not build scan-service dependencies."""

    def fake_cluster_service_builder():
        async def _builder(_tenant_id: str):
            class StubService:
                async def cluster_unclustered_identities(self, invoked_tenant_id: str):
                    dt = __import__("datetime")
                    now = dt.datetime.now(tz=dt.UTC)
                    return type(
                        "Result",
                        (),
                        {
                            "job_id": str(uuid.uuid4()),
                            "started_at": now,
                            "finished_at": now,
                            "completed": 0,
                            "total": 0,
                        },
                    )()

            return StubService()

        return _builder

    async def _session_override():
        yield FakeSession()

    async def fake_job_service_dep():
        from recognition.tests.fakes import FakeJobService

        return FakeJobService()

    def should_not_run_scan_builder():
        raise AssertionError("clustering jobs should not resolve scan-service dependencies")

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_cluster_service_builder] = fake_cluster_service_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service] = fake_job_service_dep
    app.dependency_overrides[dependencies.get_scan_service_builder] = should_not_run_scan_builder

    client = TestClient(app)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_retention_policy_service_factory_uses_provided_optional_session() -> None:
    session = FakeSession()

    service = await dependencies.get_retention_policy_service(session=session)

    assert service.__class__.__name__ == "RetentionPolicyService"
    assert getattr(service, "_session") is session
