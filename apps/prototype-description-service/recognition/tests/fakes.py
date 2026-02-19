"""Shared fakes for recognition tests (avoid conftest import side effects)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from recognition.domain.cluster import IdentityCluster
from recognition.domain.job import Job, JobStatus, JobType
from recognition.domain.repositories import IdentityMember
from recognition.interface_adapters.http.schemas.responses import ClusterResponse
from recognition.shared.ids import generate_id


def _clone_cluster(cluster: ClusterResponse, **updates: object) -> ClusterResponse:
    """Copy a ClusterResponse compatible with both Pydantic v1 and v2."""
    copier_v2 = getattr(cluster, "model_copy", None)
    if callable(copier_v2):
        return cast(ClusterResponse, copier_v2(update=updates))
    copier_v1 = getattr(cluster, "copy", None)
    if callable(copier_v1):
        return cast(ClusterResponse, copier_v1(update=updates))
    return cluster


class _FakeClusterRecord:
    """Minimal cluster record with confirmation state."""

    def __init__(self, cluster: ClusterResponse) -> None:
        self.id = cluster.id
        self.label = cluster.label
        self.user_confirmed = bool(cluster.label)


class _FakeClusterRepository:
    """In-memory cluster repository for FakeClusterService."""

    def __init__(self, service: FakeClusterService) -> None:
        self._service = service

    async def get_by_id(self, cluster_id: str) -> _FakeClusterRecord | None:
        cluster = next((c for c in self._service.clusters if c.id == cluster_id), None)
        if not cluster:
            return None
        return _FakeClusterRecord(cluster)

    async def get_members(self, cluster_id: str) -> list[IdentityMember]:
        return []

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]):
        return {}

    async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None):
        return []


class FakeClusterForRepo:
    """Minimal cluster object returned by FakeClusterRepository."""

    def __init__(self, cluster_id: str, tenant_id: str, label: str | None = None, identity_count: int = 1) -> None:
        self.id = cluster_id
        self.tenant_id = tenant_id
        self.label = label
        self.identity_count = identity_count
        self.user_confirmed = bool(label)
        self.is_labeled = bool(label)
        self.created_at = datetime.now(tz=UTC)
        self.is_auto_label = False
        self.dismissed_at: datetime | None = None
        self.representatives: list = []


class FakeClusterRepository:
    """In-memory cluster repository for API tests."""

    def __init__(self) -> None:
        self.clusters: dict[str, FakeClusterForRepo] = {}

    def seed(
        self,
        cluster_id: str,
        tenant_id: str = "00000000-0000-0000-0000-000000000000",
        label: str | None = None,
        identity_count: int = 1,
    ) -> None:
        self.clusters[cluster_id] = FakeClusterForRepo(cluster_id, tenant_id, label, identity_count)

    async def get_by_id(self, cluster_id: str) -> FakeClusterForRepo | None:
        return self.clusters.get(cluster_id)

    async def get_members(self, cluster_id: str):
        return []

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]):
        return {}

    async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None):
        return []

    async def get_top_unlabeled(
        self,
        tenant_id: str,
        limit: int = 10,
        min_identity_count: int = 2,
    ) -> list[FakeClusterForRepo]:
        unlabeled = [
            cluster
            for cluster in self.clusters.values()
            if not cluster.label and cluster.identity_count >= min_identity_count and cluster.dismissed_at is None
        ]
        sorted_clusters = sorted(unlabeled, key=lambda cluster: cluster.identity_count, reverse=True)
        return sorted_clusters[:limit]

    async def dismiss_cluster(self, cluster_id: str) -> bool:
        cluster = self.clusters.get(cluster_id)
        if not cluster or cluster.dismissed_at is not None:
            return False
        cluster.dismissed_at = datetime.now(tz=UTC)
        return True

    async def undismiss_cluster(self, cluster_id: str) -> bool:
        cluster = self.clusters.get(cluster_id)
        if not cluster or cluster.dismissed_at is None:
            return False
        cluster.dismissed_at = None
        return True

    async def get_snapshot(
        self, tenant_id: str
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, object]], int]:
        """Get snapshot data for tests - returns empty members list."""
        # Filter clusters by tenant_id and convert to IdentityCluster domain objects
        clusters_for_tenant = [c for c in self.clusters.values() if c.tenant_id == tenant_id]
        identity_clusters = [
            IdentityCluster(
                id=c.id,
                tenant_id=c.tenant_id,
                label=c.label,
                is_labeled=c.is_labeled,
                identity_count=c.identity_count,
                user_confirmed=c.user_confirmed,
                created_at=c.created_at,
                dismissed_at=c.dismissed_at,
                representatives=c.representatives,
            )
            for c in clusters_for_tenant
        ]
        # Return clusters with empty members and a simple version number
        snapshot_version = int(datetime.now(tz=UTC).timestamp())
        return (identity_clusters, [], snapshot_version)


class FakeJobRepository:
    """In-memory job repository for orchestration tests."""

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


class FakeJobService:
    """JobService stand-in that avoids persistence."""

    def __init__(self, repository: FakeJobRepository | None = None) -> None:
        self.repository = repository or FakeJobRepository()
        self.calls: list[dict[str, object]] = []

    async def create_job(self, job_type: JobType, tenant_id: str, total: int = 0) -> Job:
        job = Job(
            id=str(generate_id()),
            type=job_type,
            tenant_id=tenant_id,
            progress_total=total,
            progress_completed=0,
            status=JobStatus.PENDING,
        )
        return await self.repository.save(job)

    async def start_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.status = JobStatus.RUNNING
        return await self.repository.update(job)

    async def complete_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.complete()
        return await self.repository.update(job)

    async def get_job_status(self, job_id: str) -> Job | None:
        return await self.repository.get(job_id)

    async def cancel_job(self, job_id: str) -> Job:
        job = await self.repository.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        job.fail("canceled")
        return await self.repository.update(job)

    async def queue_curation_followup(
        self,
        *,
        tenant_id: str,
        cluster_ids: list[str],
        identity_ids: list[str] | None = None,
        source_cluster_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "method": "queue_curation_followup",
                "tenant_id": tenant_id,
                "cluster_ids": list(cluster_ids),
                "identity_ids": list(identity_ids) if identity_ids else [],
                "source_cluster_id": source_cluster_id,
            }
        )

    async def queue_split(self, tenant_id: str, payload) -> Job:  # noqa: ANN001
        job = Job(
            id=str(generate_id()),
            type=JobType.SPLIT,
            tenant_id=tenant_id,
            progress_total=1,
            progress_completed=0,
            status=JobStatus.PENDING,
            message="split",
            payload=payload.model_dump() if hasattr(payload, "model_dump") else payload,
        )
        self.calls.append(
            {
                "method": "queue_split",
                "tenant_id": tenant_id,
                "payload": job.payload or {},
            }
        )
        return await self.repository.save(job)


class FakeClusterService:
    """Fake ClusterService for API contract tests."""

    def __init__(self, clusters: list[ClusterResponse] | None = None) -> None:
        self.clusters = clusters or []
        self.calls: list[dict[str, object]] = []
        self.identity_cluster_map: dict[str, str] = {}
        self.assignment_writer = SimpleNamespace(cluster_repository=_FakeClusterRepository(self))
        self.suggestion_refresh_service = None

    async def list_clusters(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
        include_outliers: bool = False,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[ClusterResponse]:
        self.calls.append(
            {"method": "list_clusters", "tenant_id": tenant_id, "include_outliers": include_outliers, "limit": limit}
        )
        filtered = [c for c in self.clusters if c.tenant_id == tenant_id]
        return filtered[offset : offset + limit]

    async def cluster_unclustered_identities(
        self,
        tenant_id: str,
        job_id: str | None = None,
        *,
        commit: bool = True,
    ):
        self.calls.append(
            {
                "method": "cluster_unclustered_identities",
                "tenant_id": tenant_id,
                "job_id": job_id,
                "commit": commit,
            }
        )
        now = datetime.now(tz=UTC)
        return type(
            "Result",
            (),
            {
                "job_id": str(generate_id()),
                "started_at": now,
                "finished_at": now,
                "completed": 0,
                "total": 0,
            },
        )()

    async def update_cluster(
        self,
        cluster_id: str,
        tenant_id: str,
        label: str | None,
        *,
        surface_suggestions: bool = True,
    ) -> ClusterResponse | None:
        cluster = next((c for c in self.clusters if c.id == cluster_id and c.tenant_id == tenant_id), None)
        if not cluster:
            return None
        updated = self._copy_cluster(cluster, label=label, is_labeled=bool(label))
        self._replace_cluster(updated)
        return updated

    async def create_cluster_for_identity(self, identity_id: str, label: str, tenant_id: str) -> ClusterResponse:
        self.calls.append(
            {
                "method": "create_cluster_for_identity",
                "tenant_id": tenant_id,
                "identity_id": identity_id,
                "label": label,
            }
        )
        cluster = ClusterResponse(
            id=str(uuid.uuid4()),
            tenant_id=str(tenant_id),
            label=label,
            is_labeled=True,
            is_auto_label=False,
            identity_count=1,
            representatives=[],
        )
        self.clusters.append(cluster)
        return cluster

    async def merge_cluster(
        self,
        source_cluster_id: str,
        tenant_id: str,
        target_cluster_id: str,
        target_label: str | None,
        defer_recompute: bool = False,
    ) -> ClusterResponse | None:
        source = next((c for c in self.clusters if c.id == source_cluster_id and c.tenant_id == tenant_id), None)
        target = next((c for c in self.clusters if c.id == target_cluster_id and c.tenant_id == tenant_id), None)
        if not source or not target:
            return None
        updated_target = self._copy_cluster(
            target, label=target_label or target.label, identity_count=target.identity_count + source.identity_count
        )
        self._replace_cluster(updated_target)
        if not defer_recompute:
            self.clusters = [c for c in self.clusters if c.id != source_cluster_id]
        return updated_target

    async def assign_outlier_to_cluster(
        self, identity_id: str, target_cluster_id: str, tenant_id: str, similarity: float = 0.0
    ) -> ClusterResponse | None:
        target = next((c for c in self.clusters if c.id == target_cluster_id and c.tenant_id == tenant_id), None)
        if not target:
            return None
        self.identity_cluster_map[identity_id] = target_cluster_id
        updated = self._copy_cluster(target, identity_count=target.identity_count + 1)
        self._replace_cluster(updated)
        return updated

    async def get_identity_cluster_id(self, identity_id: str) -> str | None:
        return self.identity_cluster_map.get(identity_id)

    async def remove_identity_from_cluster(self, identity_id: str, recompute: bool = True) -> bool:
        return self.identity_cluster_map.pop(identity_id, None) is not None

    def seed_identity_membership(self, identity_id: str, cluster_id: str) -> None:
        self.identity_cluster_map[identity_id] = cluster_id

    def _replace_cluster(self, cluster: ClusterResponse) -> None:
        self.clusters = [c for c in self.clusters if c.id != cluster.id]
        self.clusters.append(cluster)

    def _copy_cluster(self, cluster: ClusterResponse, **updates) -> ClusterResponse:
        return _clone_cluster(cluster, **updates)
