"""API contract tests for analyze endpoints."""

from __future__ import annotations

import uuid

import pytest

from recognition.domain.job import JobType


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
