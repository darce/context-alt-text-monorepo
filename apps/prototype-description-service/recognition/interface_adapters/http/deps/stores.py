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

from db.models import IdentityCluster, IdentityMember, MediaIdentity
from recognition.domain.job import Job
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
            type="analyze",
            status="running",
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
            type="clustering",
            status="running",
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

    async def list_by_media_ids(self, tenant_id: str, media_ids: list[int]):
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
        return [
            {
                "identity_id": str(row.MediaIdentity.id),
                "media_id": row.MediaIdentity.media_id,
                "cluster_id": str(row.cluster_id) if row.cluster_id else None,
                "cluster_label": row.cluster_label,
                "is_auto_label": not row.user_confirmed if row.user_confirmed is not None else None,
                "bbox": {
                    "width": row.MediaIdentity.bbox_width,
                    "height": row.MediaIdentity.bbox_height,
                    "x": row.MediaIdentity.bbox_x,
                    "y": row.MediaIdentity.bbox_y,
                },
                "confidence": row.MediaIdentity.confidence,
                "thumbnail_url": row.MediaIdentity.thumbnail_url,
                "media_url": row.MediaIdentity.media_url,
            }
            for row in rows
        ]


__all__ = [
    "InMemoryJobService",
    "InMemoryJobRepository",
    "get_mem_job_repo",
    "DecisionStore",
    "get_decision_store",
    "MediaIdentityService",
]
