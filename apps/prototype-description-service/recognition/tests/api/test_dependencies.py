"""API dependency override tests."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.routers import clusters as clusters_router
from recognition.tests.api.conftest import FakeSession


def test_analyze_router_uses_fake_scan_queue(api_client, tenant_id, fake_scan_queue_service) -> None:
    resp = api_client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
    )

    assert resp.status_code == 202
    assert len(fake_scan_queue_service.created_jobs) == 1
    call_tenant, call_total = fake_scan_queue_service.created_jobs[0]
    assert call_tenant == tenant_id
    assert call_total > 0


def test_clusters_router_respects_dependency_override(api_client, tenant_id, fake_cluster_service) -> None:
    resp = api_client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert any(call["method"] == "cluster_unclustered_identities" for call in fake_cluster_service.calls)


def test_clusters_router_invokes_cluster_service_dependency(monkeypatch, tenant_id) -> None:
    """Default dependency should call build_cluster_service with request tenant and session."""
    called: dict[str, object] = {}

    async def fake_build(session, tenant_id: str, settings=None):
        called["session"] = session
        called["tenant_id"] = tenant_id

        class StubService:
            async def cluster_unclustered_identities(self, tenant_id: str):
                called["invoke_tenant"] = tenant_id
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

    async def _session_override():
        yield FakeSession()

    async def fake_get_job_service(session, tenant_id, cluster_service_builder=None, scan_service_builder=None):
        from recognition.tests.conftest import FakeJobService

        return FakeJobService()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    monkeypatch.setattr(dependencies, "build_cluster_service", fake_build)
    monkeypatch.setattr(clusters_router, "build_cluster_service", fake_build)
    monkeypatch.setattr(clusters_router, "get_job_service", fake_get_job_service)

    client = TestClient(app)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert resp.json()["type"] == "clustering"
    assert called.get("tenant_id") == tenant_id
    assert called.get("invoke_tenant") == tenant_id
