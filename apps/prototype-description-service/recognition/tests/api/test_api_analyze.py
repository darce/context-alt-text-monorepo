"""API contract tests for analyze endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from db.models import AuditEvent, IdentityCluster, IdentityClusterRepresentative, MediaIdentity, NameSuggestion, Tenant
from db.models.jobs import IdentityClusteringJob, IdentityScanJob
from recognition.domain.job import Job, JobStatus, JobType, ProjectionStatus
from recognition.domain.services.retention_policy_service import RetentionPolicyService
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.tests.api.conftest import FakeSession


class _NoopRetentionPolicyService:
    async def get_policy(self, tenant_id: str) -> dict[str, Any]:
        return {"tenant_id": tenant_id, "retention_mode": "retain_all"}

    async def update_policy(self, tenant_id: str, retention_mode: str, actor: str) -> dict[str, Any]:
        return {"tenant_id": tenant_id, "retention_mode": retention_mode, "actor": actor}

    async def apply_disposal_after_ack(
        self,
        tenant_id: str,
        snapshot_generation_id: str | None,
        actor: str,
    ) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "snapshot_generation_id": snapshot_generation_id,
            "actor": actor,
            "disposed_counts": {},
        }


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


@pytest.mark.asyncio
async def test_get_job_status_uses_service_followup_methods_for_pipeline_resolution(
    api_client, fake_job_service, tenant_id
) -> None:
    scan_job = await fake_job_service.create_job(JobType.ANALYZE, tenant_id=tenant_id, total=2)
    await fake_job_service.complete_job(scan_job.id)
    clustering_job = Job(
        id=str(uuid.uuid4()),
        type=JobType.CLUSTERING,
        tenant_id=tenant_id,
        status=JobStatus.COMPLETED,
        progress_completed=2,
        progress_total=2,
        message="Clustering complete",
        payload={"scan_job_id": scan_job.id, "snapshot_version": 123, "source_job_id": str(uuid.uuid4())},
    )
    await fake_job_service.repository.save(clustering_job)
    fake_job_service.repository.projections[(clustering_job.id, tenant_id)] = ProjectionStatus(
        snapshot_version=123,
        source_job_id=str(clustering_job.id),
        acknowledged_at=None,
    )

    resp = api_client.get(f"/recognition/jobs/{scan_job.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == scan_job.id
    assert body["type"] == "clustering"
    assert body["progress"]["phase"] == "awaiting_projection"
    assert body["snapshot_version"] == 123


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


def test_get_job_status_relies_on_dependency_tenant_setup_once(monkeypatch, tenant_id: str) -> None:
    """The route should not redo tenant setup after get_optional_session has already done it."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)
    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="running",
        media_ids=[],
        total_media=10,
        processed_media=4,
        identities_detected=2,
        message="Queueing 4/10 items",
    )
    session.set_get_result(model_class=IdentityScanJob, pk=scan_job_id, value=scan_job)

    setup_calls = {"count": 0}

    async def _session_override():
        setup_calls["count"] += 1
        yield session

    async def _ensure_tenant_exists(*_args, **_kwargs):
        setup_calls["count"] += 1

    async def _set_tenant_context(*_args, **_kwargs):
        setup_calls["count"] += 1

    class _NullJobService:
        async def get_job_status(self, _job_id: str):
            return None

    async def _job_service_override():
        return _NullJobService()

    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.analyze.ensure_tenant_exists",
        _ensure_tenant_exists,
    )
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.analyze.set_tenant_context",
        _set_tenant_context,
    )

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_job_service_dependency] = _job_service_override

    client = TestClient(app)
    resp = client.get(f"/recognition/jobs/{scan_job_id}", params={"tenant_id": tenant_id})

    assert resp.status_code == 200
    assert setup_calls["count"] == 1


def test_pipeline_response_exposes_retrying_phase_and_checkpoint_fields(monkeypatch, tenant_id: str) -> None:
    """GET /recognition/jobs/{scan_job_id} resolves to a retrying clustering job and exposes checkpoint metadata."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)

    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="completed",
        media_ids=[],
        total_media=100,
        processed_media=100,
        identities_detected=937,
        message="Queued 100 items",
    )
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="pending",  # re-queued after transient failure
        progress=0.5,
        total_identities=937,
        processed_identities=500,
        message="Retrying clustering",
        payload={
            "scan_job_id": str(scan_job_id),
            "retry_count": 2,
            "current_stage": "hac_refinement",
            "last_successful_processed_identities": 500,
            "last_error_code": "TimeoutError",
        },
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
    assert body["status"] == "pending"
    progress = body["progress"]
    assert progress["phase"] == "retrying"
    assert progress["completed"] == 500
    assert progress["total"] == 937
    assert progress["retry_count"] == 2
    assert progress["current_stage"] == "hac_refinement"
    assert progress["last_successful_processed_identities"] == 500
    assert progress["last_error_code"] == "TimeoutError"


def test_pipeline_response_exposes_clustering_phase_for_first_run(monkeypatch, tenant_id: str) -> None:
    """GET /recognition/jobs/{scan_job_id} resolves to a first-attempt clustering job with phase=clustering."""
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)

    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="completed",
        media_ids=[],
        total_media=50,
        processed_media=50,
        identities_detected=200,
        message="Queued 50 items",
    )
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="running",
        progress=0.3,
        total_identities=200,
        processed_identities=60,
        message="Clustering identities",
        payload={
            "scan_job_id": str(scan_job_id),
            "retry_count": 0,
            "current_stage": "assignment",
            "clusters_created": 5,
        },
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
    progress = body["progress"]
    assert progress["phase"] == "clustering"
    assert progress["completed"] == 60
    assert progress["total"] == 200
    assert progress["clusters_created"] == 5
    assert progress.get("retry_count") in (None, 0)


def test_get_job_status_surfaces_projection_pending_for_completed_followup(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)

    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="completed",
        media_ids=[],
        total_media=10,
        processed_media=10,
        identities_detected=10,
        message="Queued 10 items",
    )
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="completed",
        progress=1.0,
        total_identities=10,
        processed_identities=10,
        message="Clustering complete",
        snapshot_version=123456,
        source_job_id=clustering_job_id,
        payload={"scan_job_id": str(scan_job_id), "clusters_created": 4},
    )
    session.set_get_result(model_class=IdentityScanJob, pk=scan_job_id, value=scan_job)
    session.set_get_result(model_class=IdentityClusteringJob, pk=clustering_job_id, value=clustering_job)
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
    assert body["status"] == "completed"
    assert body["progress"]["phase"] == "awaiting_projection"
    assert body["snapshot_version"] == 123456
    assert body["source_job_id"] == str(clustering_job_id)
    assert body["projection_acknowledged_at"] is None


def test_acknowledge_projection_records_acknowledged_timestamp(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="completed",
        progress=1.0,
        total_identities=10,
        processed_identities=10,
        message="Clustering complete",
        snapshot_version=123456,
        source_job_id=clustering_job_id,
        payload={"scan_job_id": str(uuid.uuid4())},
    )
    session.set_get_result(model_class=IdentityClusteringJob, pk=clustering_job_id, value=clustering_job)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_retention_policy_service] = lambda: _NoopRetentionPolicyService()

    client = TestClient(app)
    resp = client.post(
        f"/recognition/jobs/{clustering_job_id}/acknowledge-projection",
        json={"snapshot_version": 123456},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "acknowledged", "snapshot_version": 123456}
    assert clustering_job.projection_acknowledged_at is not None


def test_acknowledge_projection_is_idempotent_for_same_snapshot(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)
    acknowledged_at = datetime.now(tz=UTC)
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="completed",
        progress=1.0,
        total_identities=10,
        processed_identities=10,
        message="Clustering complete",
        snapshot_version=123456,
        source_job_id=clustering_job_id,
        projection_acknowledged_at=acknowledged_at,
        payload={"scan_job_id": str(uuid.uuid4())},
    )
    session.set_get_result(model_class=IdentityClusteringJob, pk=clustering_job_id, value=clustering_job)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_retention_policy_service] = lambda: _NoopRetentionPolicyService()

    client = TestClient(app)
    resp = client.post(
        f"/recognition/jobs/{clustering_job_id}/acknowledge-projection",
        json={"snapshot_version": 123456},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "acknowledged", "snapshot_version": 123456}
    assert clustering_job.projection_acknowledged_at == acknowledged_at


def test_acknowledge_projection_rejects_wrong_tenant_claim(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.UUID(tenant_id)
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="completed",
        progress=1.0,
        total_identities=10,
        processed_identities=10,
        message="Clustering complete",
        snapshot_version=123456,
        source_job_id=clustering_job_id,
        payload={"scan_job_id": str(uuid.uuid4())},
    )
    session.set_get_result(model_class=IdentityClusteringJob, pk=clustering_job_id, value=clustering_job)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_override():
        yield session

    async def _auth_override():
        return SimpleNamespace(tenant_claim=str(uuid.uuid4()))

    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.require_write_access] = _auth_override
    app.dependency_overrides[dependencies.get_retention_policy_service] = lambda: _NoopRetentionPolicyService()

    client = TestClient(app)
    resp = client.post(
        f"/recognition/jobs/{clustering_job_id}/acknowledge-projection",
        json={"snapshot_version": 123456},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "tenant mismatch"


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_marks_snapshot_rows(db_session, tenant: Tenant) -> None:
    tenant.retention_mode = "dispose_after_ack"
    snapshot_generation_id = uuid.uuid4()

    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=701,
        media_url="http://example.test/disposal.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=[0.1] * 512,
        last_exported_snapshot_id=snapshot_generation_id,
    )
    cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Dispose me",
        identity_count=1,
        last_exported_snapshot_id=snapshot_generation_id,
    )
    db_session.add_all([identity, cluster])
    await db_session.flush()

    representative = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        identity_id=identity.id,
        embedding=[0.1] * 512,
        quality_score=0.9,
        last_exported_snapshot_id=snapshot_generation_id,
    )
    name_suggestion = NameSuggestion(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Dispose me",
        confidence_score=0.88,
        last_exported_snapshot_id=snapshot_generation_id,
    )
    db_session.add_all([representative, name_suggestion])
    await db_session.commit()

    service = RetentionPolicyService(db_session)

    await service.apply_disposal_after_ack(
        tenant_id=str(tenant.id),
        snapshot_generation_id=str(snapshot_generation_id),
        actor="tenant:test",
    )

    refreshed_identity = await db_session.get(MediaIdentity, identity.id)
    refreshed_cluster = await db_session.get(IdentityCluster, cluster.id)
    refreshed_rep = await db_session.get(IdentityClusterRepresentative, representative.id)
    refreshed_name_suggestion = await db_session.get(NameSuggestion, name_suggestion.id)
    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.asc())
        )
    ).scalars()

    assert refreshed_identity is not None and refreshed_identity.disposed_at is not None
    assert refreshed_cluster is not None and refreshed_cluster.disposed_at is not None
    assert refreshed_rep is not None and refreshed_rep.disposed_at is not None
    assert refreshed_name_suggestion is not None and refreshed_name_suggestion.disposed_at is not None
    event_list = list(events)
    assert [event.event_type for event in event_list] == ["disposal_completed"]
    assert event_list[0].payload["snapshot_generation_id"] == str(snapshot_generation_id)
    assert event_list[0].payload["disposed_counts"] == {
        "media_identities": 1,
        "identity_clusters": 1,
        "identity_cluster_representatives": 1,
        "name_suggestions": 1,
    }


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_requires_generation_id_when_mode_enabled(
    db_session, tenant: Tenant
) -> None:
    tenant.retention_mode = "dispose_after_ack"
    await db_session.commit()

    with pytest.raises(ValueError, match="snapshot_generation_id is required"):
        service = RetentionPolicyService(db_session)
        await service.apply_disposal_after_ack(
            tenant_id=str(tenant.id),
            snapshot_generation_id=None,
            actor="tenant:test",
        )


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_rejects_invalid_generation_id(db_session, tenant: Tenant) -> None:
    tenant.retention_mode = "dispose_after_ack"
    await db_session.commit()

    with pytest.raises(ValueError, match="snapshot_generation_id must be a valid UUID"):
        await RetentionPolicyService(db_session).apply_disposal_after_ack(
            tenant_id=str(tenant.id),
            snapshot_generation_id="not-a-uuid",
            actor="tenant:test",
        )


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_is_noop_for_retain_all(db_session, tenant: Tenant) -> None:
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=702,
        media_url="http://example.test/retain.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=[0.1] * 512,
        last_exported_snapshot_id=uuid.uuid4(),
    )
    db_session.add(identity)
    await db_session.commit()

    result = await RetentionPolicyService(db_session).apply_disposal_after_ack(
        tenant_id=str(tenant.id),
        snapshot_generation_id=str(identity.last_exported_snapshot_id),
        actor="tenant:test",
    )

    refreshed_identity = await db_session.get(MediaIdentity, identity.id)
    assert refreshed_identity is not None and refreshed_identity.disposed_at is None
    assert result["disposed_counts"] == {
        "media_identities": 0,
        "identity_clusters": 0,
        "identity_cluster_representatives": 0,
        "name_suggestions": 0,
    }


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_succeeds_with_zero_matching_rows(
    db_session, tenant: Tenant
) -> None:
    tenant.retention_mode = "dispose_after_ack"
    await db_session.commit()

    result = await RetentionPolicyService(db_session).apply_disposal_after_ack(
        tenant_id=str(tenant.id),
        snapshot_generation_id=str(uuid.uuid4()),
        actor="tenant:test",
    )

    assert result["disposed_counts"] == {
        "media_identities": 0,
        "identity_clusters": 0,
        "identity_cluster_representatives": 0,
        "name_suggestions": 0,
    }


@pytest.mark.asyncio
async def test_apply_disposal_after_acknowledgement_skips_already_disposed_rows(db_session, tenant: Tenant) -> None:
    tenant.retention_mode = "dispose_after_ack"
    snapshot_generation_id = uuid.uuid4()
    disposed_at = datetime.now(tz=UTC)
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=703,
        media_url="http://example.test/already-disposed.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=[0.1] * 512,
        last_exported_snapshot_id=snapshot_generation_id,
        disposed_at=disposed_at,
    )
    db_session.add(identity)
    await db_session.commit()

    result = await RetentionPolicyService(db_session).apply_disposal_after_ack(
        tenant_id=str(tenant.id),
        snapshot_generation_id=str(snapshot_generation_id),
        actor="tenant:test",
    )

    refreshed_identity = await db_session.get(MediaIdentity, identity.id)
    assert refreshed_identity is not None
    assert refreshed_identity.disposed_at == disposed_at
    assert result["disposed_counts"]["media_identities"] == 0


def test_acknowledge_projection_uses_retention_policy_service_for_disposal(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    clustering_job_id = uuid.uuid4()
    snapshot_generation_id = str(uuid.uuid4())
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    fake_session = FakeSession()

    class FakeProjectionRepo:
        async def get_projection_status(self, job_id: str, tenant_id: str):  # noqa: A003
            assert job_id == str(clustering_job_id)
            assert tenant_id
            return SimpleNamespace(snapshot_version=123456, source_job_id=str(clustering_job_id), acknowledged_at=None)

        async def record_projection_acknowledgement(self, **kwargs):
            return SimpleNamespace(snapshot_version=kwargs["snapshot_version"], acknowledged_at=datetime.now(tz=UTC))

    class FakeRetentionPolicyService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str | None, str]] = []

        async def get_policy(self, tenant_id: str) -> dict[str, Any]:
            return {"tenant_id": tenant_id, "retention_mode": "retain_all"}

        async def update_policy(self, tenant_id: str, retention_mode: str, actor: str) -> dict[str, Any]:
            return {"tenant_id": tenant_id, "retention_mode": retention_mode, "actor": actor}

        async def apply_disposal_after_ack(
            self,
            tenant_id: str,
            snapshot_generation_id: str | None,
            actor: str,
        ) -> dict[str, Any]:
            self.calls.append((tenant_id, snapshot_generation_id, actor))
            return {"retention_mode": "dispose_after_ack", "disposed_counts": {}}

    fake_service = FakeRetentionPolicyService()

    async def _session_override():
        yield fake_session

    async def _retention_policy_override():
        return fake_service

    monkeypatch.setattr(
        "recognition.infrastructure.repositories.job_repository.SqlAlchemyJobRepository",
        lambda _session: FakeProjectionRepo(),
    )
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_retention_policy_service] = _retention_policy_override

    client = TestClient(app)
    response = client.post(
        f"/recognition/jobs/{clustering_job_id}/acknowledge-projection",
        json={"snapshot_version": 123456, "snapshot_generation_id": snapshot_generation_id},
        headers={"X-Tenant-ID": tenant_id},
    )

    assert response.status_code == 200
    assert fake_service.calls == [(tenant_id, snapshot_generation_id, f"tenant:{tenant_id}")]


def test_get_job_status_returns_complete_phase_after_projection_acknowledged(monkeypatch, tenant_id: str) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "0")

    session = FakeSession()
    scan_job_id = uuid.uuid4()
    clustering_job_id = uuid.uuid4()
    tenant_uuid = uuid.uuid4()
    acknowledged_at = datetime.now(tz=UTC)

    scan_job = IdentityScanJob(
        id=scan_job_id,
        tenant_id=tenant_uuid,
        status="completed",
        media_ids=[],
        total_media=5,
        processed_media=5,
        identities_detected=5,
        message="Queued 5 items",
    )
    clustering_job = IdentityClusteringJob(
        id=clustering_job_id,
        tenant_id=tenant_uuid,
        job_type="clustering",
        status="completed",
        progress=1.0,
        total_identities=5,
        processed_identities=5,
        message="Clustering complete",
        snapshot_version=987654,
        source_job_id=clustering_job_id,
        projection_acknowledged_at=acknowledged_at,
        payload={"scan_job_id": str(scan_job_id), "clusters_created": 2},
    )
    session.set_get_result(model_class=IdentityScanJob, pk=scan_job_id, value=scan_job)
    session.set_get_result(model_class=IdentityClusteringJob, pk=clustering_job_id, value=clustering_job)
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
    assert body["status"] == "completed"
    assert body["progress"]["phase"] == "complete"
    assert body["snapshot_version"] == 987654
    assert body["projection_acknowledged_at"] is not None
