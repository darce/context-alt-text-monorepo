"""Background task orchestration tests (analyze/clustering queues)."""

from __future__ import annotations

import pytest

from recognition.application.orchestration.job_service import JobRepository, JobService
from recognition.domain.job import Job, JobStatus, JobType


class InMemoryJobRepo(JobRepository):
    """Simple repo for job lifecycle assertions."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    async def save(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def update(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job


class SpyScanService:
    """Captures analyze_media calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def analyze_media(self, tenant_id: str, media_ids: list[str]):
        self.calls.append((tenant_id, media_ids))
        # Return a dummy object with scan stats
        dt = __import__("datetime")
        now = dt.datetime.now(tz=dt.UTC)
        return type(
            "ScanJob",
            (),
            {
                "status": "completed",
                "processed_media": len(media_ids),
                "total_media": len(media_ids),
                "started_at": now,
                "completed_at": now,
            },
        )()


class SpyClusterService:
    """Captures clustering queue calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def cluster_unclustered_identities(self, tenant_id: str):
        self.calls.append(tenant_id)
        return type("Result", (), {"completed": 0, "total": 0})()


def _make_service(repo: InMemoryJobRepo | None = None, scan=None, cluster=None) -> JobService:
    return JobService(
        repository=repo or InMemoryJobRepo(),
        cluster_service=cluster or SpyClusterService(),
        scan_service=scan or SpyScanService(),
    )


@pytest.mark.asyncio
async def test_queue_analyze_dispatches_and_completes() -> None:
    repo = InMemoryJobRepo()
    scan = SpyScanService()
    service = _make_service(repo=repo, scan=scan)

    job = await service.queue_analyze("tenant-1", ["m1", "m2"])

    assert job.type is JobType.ANALYZE
    assert job.status is JobStatus.COMPLETED
    assert job.progress_completed == 2
    assert scan.calls == [("tenant-1", ["m1", "m2"])]


@pytest.mark.asyncio
async def test_queue_clustering_dispatches_and_completes() -> None:
    repo = InMemoryJobRepo()
    cluster = SpyClusterService()
    service = _make_service(repo=repo, cluster=cluster)

    job = await service.queue_clustering("tenant-2")

    assert job.type is JobType.CLUSTERING
    assert job.status is JobStatus.COMPLETED
    assert job.progress_completed == 1
    assert cluster.calls == ["tenant-2"]
