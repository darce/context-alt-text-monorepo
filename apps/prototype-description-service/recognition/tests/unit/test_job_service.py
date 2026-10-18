"""TDD-first tests for JobService orchestration (Phase 7.5)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from recognition.application.orchestration.job_service import JobService
from recognition.domain.job import Job, JobStatus, JobType
from recognition.tests.unit.job_repo_stub import InMemoryJobRepo


class StubClusterService:
    async def cluster_unclustered_identities(self, tenant_id: str):
        return None


class StubScanService:
    async def analyze_media(self, tenant_id: str, media_ids: list[str], media_sources: list[str] | None = None):
        return None


class StubCurationClusterService:
    def __init__(self) -> None:
        self.assignment_writer = SimpleNamespace(cluster_repository=object())


def _make_service(repo: InMemoryJobRepo | None = None) -> JobService:
    return JobService(
        repository=repo or InMemoryJobRepo(), cluster_service=StubClusterService(), scan_service=StubScanService()
    )


@pytest.mark.asyncio
async def test_create_returns_pending_state() -> None:
    service = _make_service()

    job = await service.create_job(JobType.CLUSTERING, tenant_id="tenant-1", total=5)

    assert job.status is JobStatus.PENDING
    assert job.progress_total == 5
    assert job.progress_completed == 0


@pytest.mark.asyncio
async def test_running_transition_sets_status() -> None:
    service = _make_service()
    repo = service.repository
    assert isinstance(repo, InMemoryJobRepo)
    pending = await service.create_job(JobType.ANALYZE, tenant_id="tenant-1", total=2)
    assert pending.status is JobStatus.PENDING

    running = await service.start_job(pending.id)

    assert running.status is JobStatus.RUNNING
    # persisted update
    assert repo.jobs[pending.id].status is JobStatus.RUNNING


@pytest.mark.asyncio
async def test_completed_transition_sets_finished_at() -> None:
    service = _make_service()
    job = await service.create_job(JobType.CLUSTERING, tenant_id="tenant-1", total=3)

    completed = await service.complete_job(job.id)

    assert completed.status is JobStatus.COMPLETED
    assert completed.finished_at is not None


@pytest.mark.asyncio
async def test_failed_transition_stores_error_message() -> None:
    service = _make_service()
    job = await service.create_job(JobType.ANALYZE, tenant_id="tenant-1")

    failed = await service.fail_job(job.id, "boom")

    assert failed.status is JobStatus.FAILED
    assert failed.error_message == "boom"
    assert failed.finished_at is not None


@pytest.mark.asyncio
async def test_progress_updates_completed_and_total() -> None:
    service = _make_service()
    job = await service.create_job(JobType.CLUSTERING, tenant_id="tenant-1", total=10)

    updated = await service.update_progress(job.id, completed=3, total=10)

    assert updated.progress_completed == 3
    assert updated.progress_total == 10


@pytest.mark.asyncio
async def test_update_job_message_persists_message() -> None:
    service = _make_service()
    repo = service.repository
    assert isinstance(repo, InMemoryJobRepo)

    job = await service.create_job(JobType.ANALYZE, tenant_id="tenant-1", total=1)
    updated = await service.update_job_message(job.id, "Queueing 0/1 items")

    assert updated.message == "Queueing 0/1 items"
    assert repo.jobs[job.id].message == "Queueing 0/1 items"


@pytest.mark.asyncio
async def test_queue_curation_followup_includes_merge_cleanup_payload() -> None:
    service = _make_service()

    job = await service.queue_curation_followup(
        tenant_id="tenant-1",
        cluster_ids=["cluster-1"],
        source_cluster_id="cluster-source",
        refresh_idempotency_key="refresh-idem-1",
    )

    assert job.type is JobType.CURATION
    assert job.payload
    assert job.payload["source_cluster_id"] == "cluster-source"
    assert job.payload["refresh_idempotency_key"] == "refresh-idem-1"


@pytest.mark.asyncio
async def test_process_curation_job_passes_payload_identity_ids_to_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = InMemoryJobRepo()
    refresh_metrics = object()
    service = JobService(
        repository=repo,
        cluster_service=StubCurationClusterService(),
        scan_service=StubScanService(),
        curation_refresh_metrics=refresh_metrics,
    )

    job = await service.queue_curation_followup(
        tenant_id="tenant-1",
        cluster_ids=["cluster-1"],
        identity_ids=["identity-1", "identity-2"],
    )

    captured: dict[str, object] = {}

    async def fake_run_curation_job(**kwargs):
        captured.update(kwargs)
        return {"clusters_recomputed": 1}

    import recognition.application.orchestration.curation_job as curation_job_module

    monkeypatch.setattr(curation_job_module, "run_curation_job", fake_run_curation_job)

    completed = await service.process_curation_job(job.id, "tenant-1", cluster_ids=[])

    assert completed.status is JobStatus.COMPLETED
    assert captured["cluster_ids"] == ["cluster-1"]
    assert captured["identity_ids"] == ["identity-1", "identity-2"]
    assert captured["refresh_metrics"] is refresh_metrics
