"""In-memory async describe job store for the bursty GPU path."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock
from typing import Any, Literal


class DescribeJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PROVISIONAL = "provisional"
    FINAL = "final"
    FAILED = "failed"


DescribeTier = Literal["provisional_cpu", "final_gpu"]


@dataclass(frozen=True)
class DescribeJob:
    job_id: str
    tenant_id: uuid.UUID
    media_id: int
    image_bytes: bytes
    context: dict[str, Any] | None
    status: DescribeJobStatus
    tier: DescribeTier | None = None
    result_generation: int = 0
    visual_facts: dict[str, Any] | None = None
    error: str | None = None


class InMemoryDescribeJobStore:
    """Process-local queue used by the MVP async route and tests."""

    def __init__(self) -> None:
        self._jobs: dict[str, DescribeJob] = {}
        self._order: list[str] = []
        self._lock = Lock()

    def enqueue(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_bytes: bytes,
        context: dict[str, Any] | None,
    ) -> DescribeJob:
        with self._lock:
            job = DescribeJob(
                job_id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                media_id=media_id,
                image_bytes=image_bytes,
                context=context,
                status=DescribeJobStatus.QUEUED,
            )
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            return job

    def get(self, job_id: str) -> DescribeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def next_queued(self) -> DescribeJob | None:
        with self._lock:
            for job_id in self._order:
                job = self._jobs[job_id]
                if job.status is DescribeJobStatus.QUEUED:
                    return job
            return None

    def mark_running(self, job_id: str) -> DescribeJob:
        return self._replace(job_id, status=DescribeJobStatus.RUNNING)

    def set_provisional(self, job_id: str, *, visual_facts: dict[str, Any]) -> DescribeJob:
        return self._replace(
            job_id,
            status=DescribeJobStatus.PROVISIONAL,
            tier="provisional_cpu",
            result_generation=self._next_generation(job_id),
            visual_facts=visual_facts,
            error=None,
        )

    def set_final(self, job_id: str, *, visual_facts: dict[str, Any]) -> DescribeJob:
        return self._replace(
            job_id,
            status=DescribeJobStatus.FINAL,
            tier="final_gpu",
            result_generation=self._next_generation(job_id),
            visual_facts=visual_facts,
            error=None,
        )

    def set_failed(self, job_id: str, *, error: str) -> DescribeJob:
        return self._replace(job_id, status=DescribeJobStatus.FAILED, error=error)

    def _next_generation(self, job_id: str) -> int:
        return self._jobs[job_id].result_generation + 1

    def _replace(self, job_id: str, **changes: Any) -> DescribeJob:
        with self._lock:
            job = self._jobs[job_id]
            updated = replace(job, **changes)
            self._jobs[job_id] = updated
            return updated
