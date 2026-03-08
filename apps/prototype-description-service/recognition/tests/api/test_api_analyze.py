"""API contract tests for analyze endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models.jobs import IdentityClusteringJob, IdentityScanJob
from recognition.domain.job import JobType
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession


def test_analyze_creates_job(api_client, tenant_id, fake_scan_queue_service) -> None:
    resp = api_client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["id"]
    assert body["type"] == "analyze"
    assert body["status"] in {"running", "pending"}
    assert fake_scan_queue_service.created_jobs[0][0] == tenant_id


def test_analyze_job_starts_with_correct_progress(api_client, tenant_id) -> None:
    payload = {"media_ids": [str(uuid.uuid4()), str(uuid.uuid4())], "tenant_id": tenant_id}

    resp = api_client.post("/recognition/analyze", json=payload)

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] in {"running", "pending"}
    assert body["progress"]["total"] == len(payload["media_ids"])
    assert body["message"] == f"Queueing 0/{len(payload['media_ids'])} items"


@pytest.mark.asyncio
async def test_get_job_status_returns_job(api_client, fake_job_service, tenant_id) -> None:
    job = await fake_job_service.create_job(JobType.ANALYZE, tenant_id=tenant_id, total=1)
    await fake_job_service.start_job(job.id)
    job.message = "Queueing 0/1 items"
    await fake_job_service.repository.update(job)

    resp = api_client.get(f"/recognition/jobs/{job.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job.id
    assert body["type"] == "analyze"
    assert body["message"] == "Queueing 0/1 items"


def test_get_job_status_404_for_unknown_job(api_client) -> None:
    resp = api_client.get("/recognition/jobs/unknown-job-id")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"


def test_get_job_status_surfaces_followup_clustering_job(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.uuid4()

    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="completed",
        media_ids=[],
        total_media=500,
        processed_media=500,
        identities_detected=14,
        message="Queued 500 items",
    )
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="running",
        progress=0.4,
        total_identities=14,
        processed_identities=6,
        message="Clustering identities",
        payload={"scan_job_id": str(scan_job_id), "clusters_created": 3},
    )
    session.set_get_result(model_class=IdentityScanJob, pk=scan_job_id, value=scan_job)
    session.queue_execute_result(all_rows=[clustering_job])

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    class _NullJobService:
        async def get_job_status(self, _job_id: str):
            return None

    async def _job_service_override():
        return _NullJobService()

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_job_service_dependency] = _job_service_override

    client = TestClient(app)
    resp = client.get(f"/recognition/jobs/{scan_job_id}", params={"tenant_id": tenant_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(scan_job_id)
    assert body["type"] == "clustering"
    assert body["status"] == "running"
    assert body["progress"]["phase"] == "clustering"
    assert body["progress"]["completed"] == 6
    assert body["progress"]["total"] == 14
    assert body["progress"]["clusters_created"] == 3
