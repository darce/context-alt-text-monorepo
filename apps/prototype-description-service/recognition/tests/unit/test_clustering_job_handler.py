from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from db.models import IdentityClusteringJob
from recognition.worker.handlers.clustering import ClusteringJobHandler


class _FakeSession:
    async def flush(self) -> None:
        return None

    async def execute(self, _statement, _params=None):  # noqa: ANN001
        return None


class _FakeClusterRepository:
    def __init__(self, snapshot_version: int) -> None:
        self.snapshot_version = snapshot_version
        self.snapshot_calls: list[str] = []

    async def get_snapshot(self, tenant_id: str):
        self.snapshot_calls.append(tenant_id)
        return ([], [], self.snapshot_version, None)


class _FakeClusterService:
    def __init__(self, snapshot_version: int) -> None:
        self.cluster_repository = _FakeClusterRepository(snapshot_version)
        self.calls: list[tuple[str, str | None, bool]] = []

    async def cluster_unclustered_identities(self, tenant_id: str, job_id: str | None = None, **kwargs):
        self.calls.append((tenant_id, job_id, bool(kwargs.get("commit", True))))
        callback = kwargs.get("progress_callback")
        if callback is not None:
            await callback(4, 4)
        return SimpleNamespace(completed=4, total=4)


@pytest.mark.asyncio
async def test_clustering_job_handler_records_snapshot_version_on_completion(monkeypatch) -> None:
    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    handler = ClusteringJobHandler(cluster_service=_FakeClusterService(snapshot_version=987654321))
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={"scan_job_id": str(uuid.uuid4())},
    )

    await handler.handle(job, _FakeSession())

    assert job.status == "completed"
    assert job.snapshot_version == 987654321
    assert job.source_job_id == job.id
