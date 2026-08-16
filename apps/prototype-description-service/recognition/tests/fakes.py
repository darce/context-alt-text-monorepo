"""Shared fakes for recognition tests (avoid conftest import side effects)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import numpy as np

from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.job import Job, JobStatus, JobType, ProjectionStatus
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

    def __init__(self, cluster: ClusterResponse | FakeClusterForRepo) -> None:
        self.id = cluster.id
        self.label = cluster.label
        self.backend_version = int(getattr(cluster, "backend_version", 0) or 0)
        # Prefer explicit user_confirmed when the fake repo models it (E21-17-R2-PY-N1).
        if hasattr(cluster, "user_confirmed"):
            self.user_confirmed = bool(cluster.user_confirmed)
        else:
            self.user_confirmed = bool(cluster.label)
        self.identity_count = int(getattr(cluster, "identity_count", 0) or 0)
        self.representative_identity_id = getattr(cluster, "representative_identity_id", None)


class _FakeClusterRepository:
    """In-memory cluster repository for FakeClusterService."""

    def __init__(self, service: FakeClusterService) -> None:
        self._service = service

    async def get_by_id(self, cluster_id: str) -> _FakeClusterRecord | None:
        if self._service.fake_cluster_repository is not None:
            seeded_cluster = await self._service.fake_cluster_repository.get_by_id(cluster_id)
            if seeded_cluster is not None:
                return _FakeClusterRecord(seeded_cluster)

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

    def __init__(
        self,
        cluster_id: str,
        tenant_id: str,
        label: str | None = None,
        identity_count: int = 1,
        backend_version: int = 0,
        *,
        user_confirmed: bool | None = None,
    ) -> None:
        self.id = cluster_id
        self.tenant_id = tenant_id
        self.label = label
        self.identity_count = identity_count
        self.backend_version = backend_version
        self.user_confirmed = bool(label) if user_confirmed is None else user_confirmed
        self.is_labeled = bool(label)
        self.created_at = datetime.now(tz=UTC)
        self.is_auto_label = False
        self.dismissed_at: datetime | None = None
        self.representatives: list = []


class FakeClusterRepository:
    """In-memory cluster repository for API tests."""

    def __init__(self) -> None:
        self.clusters: dict[str, FakeClusterForRepo] = {}
        self.members_by_cluster: dict[str, list[tuple[IdentityMember, MediaIdentity]]] = {}
        self._snapshot_version = 1

    def seed(
        self,
        cluster_id: str,
        tenant_id: str = "00000000-0000-0000-0000-000000000000",
        label: str | None = None,
        identity_count: int = 1,
        backend_version: int = 0,
        *,
        user_confirmed: bool | None = None,
    ) -> None:
        self.clusters[cluster_id] = FakeClusterForRepo(
            cluster_id,
            tenant_id,
            label,
            identity_count,
            backend_version,
            user_confirmed=user_confirmed,
        )
        self._snapshot_version += 1

    def seed_member(self, *, tenant_id: str, cluster_id: str, identity_id: str, media_id: str = "1") -> None:
        member = IdentityMember(
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            identity_id=identity_id,
            similarity=0.9,
            tenant_id=tenant_id,
        )
        identity = MediaIdentity(
            id=identity_id,
            tenant_id=tenant_id,
            media_id=media_id,
            embedding=np.zeros(512, dtype=np.float32),
            confidence=0.99,
            bbox_x=0,
            bbox_y=0,
            bbox_width=1,
            bbox_height=1,
            cluster_id=cluster_id,
        )
        self.members_by_cluster.setdefault(cluster_id, []).append((member, identity))
        self._snapshot_version += 1

    def apply_split(self, source_cluster_id: str, new_cluster_ids: Sequence[str]) -> None:
        source_members = list(self.members_by_cluster.get(source_cluster_id, []))
        if not source_members:
            return

        retained_members = list(source_members)
        for new_cluster_id in new_cluster_ids:
            if len(retained_members) <= 1:
                break
            member, identity = retained_members.pop()
            moved_member = IdentityMember(
                id=member.id,
                cluster_id=new_cluster_id,
                identity_id=member.identity_id,
                similarity=member.similarity,
                tenant_id=member.tenant_id,
                assigned_at=member.assigned_at,
            )
            moved_identity = MediaIdentity(
                id=identity.id,
                tenant_id=identity.tenant_id,
                media_id=identity.media_id,
                embedding=identity.embedding,
                confidence=identity.confidence,
                bbox_width=identity.bbox_width,
                bbox_height=identity.bbox_height,
                bbox_x=identity.bbox_x,
                bbox_y=identity.bbox_y,
                pose_pitch=identity.pose_pitch,
                pose_yaw=identity.pose_yaw,
                pose_roll=identity.pose_roll,
                image_phash=identity.image_phash,
                metadata=dict(identity.metadata),
                cluster_id=new_cluster_id,
                moved_by_merge_id=identity.moved_by_merge_id,
            )
            self.members_by_cluster.setdefault(new_cluster_id, []).append((moved_member, moved_identity))

        self.members_by_cluster[source_cluster_id] = retained_members
        self._snapshot_version += 1

    async def get_by_id(self, cluster_id: str) -> FakeClusterForRepo | None:
        return self.clusters.get(cluster_id)

    async def get_by_ids(self, cluster_ids: Sequence[str]) -> list[FakeClusterForRepo]:
        return [self.clusters[cluster_id] for cluster_id in cluster_ids if cluster_id in self.clusters]

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
        self, tenant_id: str, *, stamp_export: bool = False
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int, str | None]:
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
        snapshot_version = await self.get_snapshot_version(tenant_id)
        members = await self.get_members_by_cluster_ids(tenant_id, list(self.clusters.keys()))
        snapshot_generation_id = str(uuid.uuid4()) if stamp_export else None
        return (identity_clusters, members, snapshot_version, snapshot_generation_id)

    async def get_delta(
        self,
        tenant_id: str,
        *,
        since_version: int,
    ) -> tuple[list[IdentityCluster], list[tuple[IdentityMember, MediaIdentity]], int]:
        snapshot_version = await self.get_snapshot_version(tenant_id)
        if since_version >= snapshot_version:
            return ([], [], snapshot_version)
        clusters, members, _snapshot_version, _generation_id = await self.get_snapshot(tenant_id)
        return (clusters, members, snapshot_version)

    async def get_members_by_cluster_ids(
        self, tenant_id: str, cluster_ids: Sequence[str]
    ) -> list[tuple[IdentityMember, MediaIdentity]]:
        rows: list[tuple[IdentityMember, MediaIdentity]] = []
        for cluster_id in cluster_ids:
            for member, identity in self.members_by_cluster.get(cluster_id, []):
                if identity.tenant_id == tenant_id:
                    rows.append((member, identity))
        return rows

    async def get_member_identity_count(self, cluster_id: str) -> int:
        return len(self.members_by_cluster.get(cluster_id, []))

    async def get_member_identities_with_similarity(
        self,
        cluster_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[MediaIdentity, float]]:
        rows = self.members_by_cluster.get(cluster_id, [])
        start = max(0, offset)
        if limit is not None:
            rows = rows[start : start + limit]
        elif start:
            rows = rows[start:]
        return [(identity, member.similarity) for member, identity in rows]

    async def get_clusters_by_ids(self, tenant_id: str, cluster_ids: Sequence[str]) -> list[IdentityCluster]:
        return [
            IdentityCluster(
                id=cluster.id,
                tenant_id=cluster.tenant_id,
                label=cluster.label,
                is_labeled=cluster.is_labeled,
                identity_count=cluster.identity_count,
                user_confirmed=cluster.user_confirmed,
                created_at=cluster.created_at,
                dismissed_at=cluster.dismissed_at,
                representatives=cluster.representatives,
            )
            for cluster_id, cluster in self.clusters.items()
            if cluster_id in cluster_ids and cluster.tenant_id == tenant_id
        ]

    async def get_snapshot_version(self, tenant_id: str) -> int:
        if not any(c.tenant_id == tenant_id for c in self.clusters.values()):
            return 0
        return self._snapshot_version


class FakeJobRepository:
    """In-memory job repository for orchestration tests."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.projections: dict[tuple[str, str], ProjectionStatus] = {}

    async def save(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def update(self, job: Job) -> Job:
        self.jobs[job.id] = job
        return job

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        for job in reversed(list(self.jobs.values())):
            if job.type is not JobType.CLUSTERING:
                continue
            payload = job.payload or {}
            if payload.get("scan_job_id") == scan_job_id:
                return job
        return None

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        for job in reversed(list(self.jobs.values())):
            if job.type is not JobType.CLUSTERING:
                continue
            if job.tenant_id != tenant_id or job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
                continue
            return job
        return None

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        for job in reversed(list(self.jobs.values())):
            if job.type is not JobType.CLUSTERING:
                continue
            if job.tenant_id != tenant_id or job.status is not JobStatus.COMPLETED:
                continue
            return job
        return None

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        return self.projections.get((job_id, tenant_id))

    async def record_projection_acknowledgement(
        self,
        *,
        job_id: str,
        tenant_id: str,
        snapshot_version: int,
        acknowledged_at: datetime,
    ) -> ProjectionStatus | None:
        projection = ProjectionStatus(
            snapshot_version=snapshot_version,
            source_job_id=job_id,
            acknowledged_at=acknowledged_at,
        )
        self.projections[(job_id, tenant_id)] = projection
        return projection


class FakeJobService:
    """JobService stand-in that avoids persistence."""

    def __init__(self, repository: FakeJobRepository | None = None) -> None:
        self.repository = repository or FakeJobRepository()
        self.cluster_repository: FakeClusterRepository | None = None
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

    async def get_followup_clustering_job(self, scan_job_id: str) -> Job | None:
        return await self.repository.get_followup_clustering_job(scan_job_id)

    async def get_active_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        return await self.repository.get_active_clustering_job_for_tenant(tenant_id)

    async def get_projection_status(self, job_id: str, tenant_id: str) -> ProjectionStatus | None:
        return await self.repository.get_projection_status(job_id, tenant_id)

    async def record_projection_acknowledgement(
        self,
        *,
        job_id: str,
        tenant_id: str,
        snapshot_version: int,
        acknowledged_at: datetime,
    ) -> ProjectionStatus | None:
        return await self.repository.record_projection_acknowledgement(
            job_id=job_id,
            tenant_id=tenant_id,
            snapshot_version=snapshot_version,
            acknowledged_at=acknowledged_at,
        )

    async def get_latest_completed_clustering_job_for_tenant(self, tenant_id: str) -> Job | None:
        return await self.repository.get_latest_completed_clustering_job_for_tenant(tenant_id)

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
        refresh_idempotency_key: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "method": "queue_curation_followup",
                "tenant_id": tenant_id,
                "cluster_ids": list(cluster_ids),
                "identity_ids": list(identity_ids) if identity_ids else [],
                "source_cluster_id": source_cluster_id,
                "refresh_idempotency_key": refresh_idempotency_key,
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
        self.fake_cluster_repository: FakeClusterRepository | None = None

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

    async def create_cluster_for_identity(
        self, identity_id: str, label: str, tenant_id: str, desired_cluster_id: str | None = None
    ) -> ClusterResponse:
        self.calls.append(
            {
                "method": "create_cluster_for_identity",
                "tenant_id": tenant_id,
                "identity_id": identity_id,
                "label": label,
                "desired_cluster_id": desired_cluster_id,
            }
        )
        cluster = ClusterResponse(
            id=desired_cluster_id or str(uuid.uuid4()),
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
        moved_by_merge_id: str | None = None,
    ) -> ClusterResponse | None:
        self.calls.append(
            {
                "method": "merge_cluster",
                "source_cluster_id": source_cluster_id,
                "tenant_id": tenant_id,
                "target_cluster_id": target_cluster_id,
                "target_label": target_label,
                "defer_recompute": defer_recompute,
                "moved_by_merge_id": moved_by_merge_id,
            }
        )
        source = next((c for c in self.clusters if c.id == source_cluster_id and c.tenant_id == tenant_id), None)
        target = next((c for c in self.clusters if c.id == target_cluster_id and c.tenant_id == tenant_id), None)
        if not source or not target:
            return None
        final_label = target_label or target.label
        updated_target = self._copy_cluster(
            target, label=final_label, identity_count=target.identity_count + source.identity_count
        )
        self._replace_cluster(updated_target)
        if self.fake_cluster_repository is not None:
            repo_target = self.fake_cluster_repository.clusters.get(target_cluster_id)
            if repo_target is not None:
                # Mirror cluster_merge label/confirmation stamping so API tests can
                # catch reserved-label user_confirmed regressions (E21-17-R2-PY-N1).
                from recognition.domain.cluster import is_reserved_label_shape

                repo_target.label = final_label
                repo_target.is_labeled = bool(final_label)
                repo_target.identity_count = updated_target.identity_count
                if final_label and not is_reserved_label_shape(final_label):
                    repo_target.user_confirmed = True
            if not defer_recompute:
                self.fake_cluster_repository.clusters.pop(source_cluster_id, None)
        if not defer_recompute:
            self.clusters = [c for c in self.clusters if c.id != source_cluster_id]
        return updated_target

    async def split_cluster(
        self,
        cluster_id: str,
        n_clusters: int = 0,
        anchor_identity_id: str | None = None,
        split_mode: str | None = None,
        desired_cluster_ids: list[str] | None = None,
        recompute: bool = True,
    ) -> tuple[list[str], list[int]]:
        self.calls.append(
            {
                "method": "split_cluster",
                "cluster_id": cluster_id,
                "n_clusters": n_clusters,
                "anchor_identity_id": anchor_identity_id,
                "split_mode": split_mode,
                "desired_cluster_ids": desired_cluster_ids,
                "recompute": recompute,
            }
        )
        source = next((c for c in self.clusters if c.id == cluster_id), None)
        if source is None:
            return ([], [])

        split_count = n_clusters if n_clusters >= 2 else 2
        new_cluster_count = split_count - 1
        desired_ids = desired_cluster_ids or []
        new_ids = [
            desired_ids[index] if index < len(desired_ids) else str(uuid.uuid4()) for index in range(new_cluster_count)
        ]
        counts = [1 for _ in range(new_cluster_count)]
        retained_count = max(0, source.identity_count - sum(counts))
        self._replace_cluster(self._copy_cluster(source, identity_count=retained_count or 1))
        for new_cluster_id in new_ids:
            self.clusters.append(
                ClusterResponse(
                    id=new_cluster_id,
                    tenant_id=source.tenant_id,
                    label=source.label,
                    is_labeled=bool(source.label),
                    is_auto_label=False,
                    identity_count=1,
                    representatives=[],
                )
            )
        if self.fake_cluster_repository is not None:
            self.fake_cluster_repository.apply_split(cluster_id, new_ids)
        return (new_ids, counts)

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
