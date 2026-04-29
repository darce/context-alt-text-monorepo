"""
In-memory stores and lightweight services for recognition HTTP API.

This module provides in-memory implementations used for testing or fallback.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusterRepresentative, IdentityMember, MediaIdentity
from recognition.application.assignment.quality import compute_identity_quality
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.job import Job, JobStatus, JobType
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse
from recognition.shared.ids import generate_id


class InMemoryJobService:
    """Very small in-memory job tracker."""

    def __init__(self) -> None:
        self.jobs: dict[str, JobStatusResponse] = {}

    async def create_scan_job(self, media_ids: Iterable[str], tenant_id: str) -> JobStatusResponse:
        """Create a completed scan job immediately."""
        media_ids_list = list(media_ids)
        job_id = str(generate_id())
        started_at = datetime.now(tz=UTC)
        job = JobStatusResponse(
            id=job_id,
            type=JobType.ANALYZE,
            status=JobStatus.RUNNING,
            progress=JobProgressResponse(completed=0, total=len(media_ids_list)),
            started_at=started_at,
            finished_at=None,
        )
        self.jobs[job_id] = job
        return job

    async def create_cluster_job(self, tenant_id: str) -> str:
        """Create a clustering job placeholder."""
        job_id = str(generate_id())
        started_at = datetime.now(tz=UTC)
        self.jobs[job_id] = JobStatusResponse(
            id=job_id,
            type=JobType.CLUSTERING,
            status=JobStatus.RUNNING,
            progress=JobProgressResponse(completed=0, total=0),
            started_at=started_at,
            finished_at=None,
        )
        return job_id

    async def get_job_status(self, job_id: str) -> JobStatusResponse | None:
        """Return job status if known."""
        return self.jobs.get(job_id)


class InMemoryJobRepository:
    """Shared in-memory job repository used when the database is unavailable."""

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


# Singleton instance for fallback
_MEM_JOB_REPO = InMemoryJobRepository()


def get_mem_job_repo() -> InMemoryJobRepository:
    """Return the singleton in-memory job repository."""
    return _MEM_JOB_REPO


class DecisionStore:
    """In-memory store for decision logs exposed via diagnostics."""

    def __init__(self) -> None:
        self._decisions: list[dict[str, Any]] = []

    def add(self, decision: dict[str, Any]) -> None:
        self._decisions.append(decision)

    def clear(self) -> None:
        self._decisions.clear()

    def list(
        self,
        *,
        tenant_id: str | None = None,
        outcome: str | None = None,
        cluster_id: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Filter decision logs by tenant, outcome, and time window."""
        filtered: list[dict[str, Any]] = []
        for decision in self._decisions:
            if tenant_id and decision.get("tenant_id") != tenant_id:
                continue
            if outcome and decision.get("decision") != outcome:
                continue
            if cluster_id and decision.get("cluster_id") != cluster_id:
                continue

            ts = self._to_datetime(decision.get("timestamp"))
            if start_at and (ts is None or ts < start_at):
                continue
            if end_at and (ts is None or ts > end_at):
                continue

            filtered.append(dict(decision))

        if offset < 0:
            offset = 0
        if limit < 0:
            limit = 0
        return filtered[offset : offset + limit]

    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None


@lru_cache
def get_decision_store() -> DecisionStore:
    """Singleton decision store."""
    return DecisionStore()


class MediaIdentityService:
    """Lightweight service to fetch media identities by media_id."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_media_ids(self, tenant_id: str, media_ids: list[int], include_debug: bool = False):
        if not media_ids:
            return []
        # Left outer join with IdentityMember and IdentityCluster to get cluster info
        stmt = (
            select(
                MediaIdentity,
                IdentityMember.cluster_id,
                IdentityCluster.label.label("cluster_label"),
                IdentityCluster.user_confirmed.label("user_confirmed"),
            )
            .outerjoin(IdentityMember, MediaIdentity.id == IdentityMember.identity_id)
            .outerjoin(IdentityCluster, IdentityMember.cluster_id == IdentityCluster.id)
            .where(MediaIdentity.tenant_id == uuid.UUID(str(tenant_id)))
            .where(MediaIdentity.media_id.in_(media_ids))
        )
        rows = (await self._session.execute(stmt)).all()
        rep_stats: dict[str, dict[str, object]] = {}
        pose_bucket_size = 0.0
        max_total_buckets = 0

        if include_debug:
            settings = ClusteringSettings()
            pose_bucket_size = settings.pose_bucket_size
            max_total_buckets = settings.max_representatives_per_cluster + settings.pose_diversity_bonus
            cluster_ids = {row.cluster_id for row in rows if row.cluster_id}
            if cluster_ids:
                rep_stmt = (
                    select(
                        IdentityClusterRepresentative.cluster_id,
                        IdentityClusterRepresentative.pose_pitch,
                        IdentityClusterRepresentative.pose_yaw,
                    )
                    .where(IdentityClusterRepresentative.cluster_id.in_(cluster_ids))
                    .where(IdentityClusterRepresentative.tenant_id == uuid.UUID(str(tenant_id)))
                )
                rep_rows = (await self._session.execute(rep_stmt)).all()
                for rep in rep_rows:
                    cluster_key = str(rep.cluster_id)
                    entry = rep_stats.setdefault(cluster_key, {"count": 0, "buckets": set()})
                    entry["count"] = int(entry["count"]) + 1
                    if rep.pose_pitch is not None and rep.pose_yaw is not None and pose_bucket_size:
                        bucket = (int(rep.pose_pitch // pose_bucket_size), int(rep.pose_yaw // pose_bucket_size))
                        entry["buckets"].add(bucket)
        response: list[dict[str, object]] = []
        now = datetime.now(tz=UTC)
        # Only show "Processing..." for identities created in the last 60 seconds
        # that don't have a cluster yet. After 60s, treat as "Unlabeled" so users can act.
        clustering_pending_window_seconds = 60
        for row in rows:
            cluster_id = str(row.cluster_id) if row.cluster_id else None
            # Only pending if: no cluster AND created recently (within window)
            created_at = row.MediaIdentity.created_at
            age_seconds = (now - created_at).total_seconds() if created_at else float("inf")
            clustering_pending = cluster_id is None and age_seconds < clustering_pending_window_seconds
            payload: dict[str, object] = {
                "identity_id": str(row.MediaIdentity.id),
                "media_id": row.MediaIdentity.media_id,
                "cluster_id": cluster_id,
                "cluster_label": row.cluster_label,
                "is_auto_label": not row.user_confirmed if row.user_confirmed is not None else None,
                "clustering_pending": clustering_pending,
                "bbox": {
                    "width": row.MediaIdentity.bbox_width,
                    "height": row.MediaIdentity.bbox_height,
                    "x": row.MediaIdentity.bbox_x,
                    "y": row.MediaIdentity.bbox_y,
                },
                "confidence": row.MediaIdentity.confidence,
                "media_url": row.MediaIdentity.media_url,
            }

            if include_debug:
                pose_pitch = row.MediaIdentity.pose_pitch
                pose_yaw = row.MediaIdentity.pose_yaw
                pose_roll = row.MediaIdentity.pose_roll

                # Compute quality on-the-fly from pose angles (not stale DB value)
                quality_info = compute_identity_quality(
                    confidence=row.MediaIdentity.confidence,
                    pose_pitch=pose_pitch,
                    pose_yaw=pose_yaw,
                    pose_roll=pose_roll,
                    bbox_width=row.MediaIdentity.bbox_width,
                    bbox_height=row.MediaIdentity.bbox_height,
                )

                debug_metrics: dict[str, object] = {
                    "pose": {
                        "pitch": float(pose_pitch or 0),
                        "yaw": float(pose_yaw or 0),
                        "roll": float(pose_roll or 0),
                    },
                    "age": float(row.MediaIdentity.age or 0),
                    "gender": "male" if row.MediaIdentity.gender == 1 else "female",
                    "det_score": float(row.MediaIdentity.confidence),
                    "bbox_area": int(row.MediaIdentity.bbox_width * row.MediaIdentity.bbox_height),
                    "landmark_quality": quality_info.score,
                    "clustering_method": None,
                    "clustering_algorithm": None,
                    "similarity_threshold": None,
                    "match_similarity": None,
                }

                if cluster_id:
                    stats = rep_stats.get(cluster_id, {"count": 0, "buckets": set()})
                    buckets = stats.get("buckets", set())
                    current_bucket = None
                    if pose_pitch is not None and pose_yaw is not None and pose_bucket_size:
                        current_bucket = (
                            int(pose_pitch // pose_bucket_size),
                            int(pose_yaw // pose_bucket_size),
                        )
                    debug_metrics["representative_count"] = int(stats.get("count", 0))
                    debug_metrics["pose_buckets"] = {
                        "filled": len(buckets),
                        "total": max_total_buckets,
                        "current_bucket": current_bucket,
                    }

                payload["debug_metrics"] = debug_metrics

            response.append(payload)

        return response


__all__ = [
    "InMemoryJobService",
    "InMemoryJobRepository",
    "get_mem_job_repo",
    "DecisionStore",
    "get_decision_store",
    "MediaIdentityService",
]
