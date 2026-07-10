"""Bounded in-memory async describe job store for the bursty GPU path.

This store is intentionally process-local for the MVP route. Production
multi-worker deployments must either run the async describe surface in a
single-worker process or replace this class with a shared DB/Redis store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from scene.domain.description import DescriptionResultTier


class DescribeJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PROVISIONAL = "provisional"
    FINAL = "final"
    DEGRADED = "degraded"
    FAILED = "failed"


_TERMINAL_STATUSES = frozenset({DescribeJobStatus.FINAL, DescribeJobStatus.DEGRADED, DescribeJobStatus.FAILED})


@dataclass(frozen=True)
class DescribeJob:
    job_id: str
    tenant_id: uuid.UUID
    media_id: int
    image_bytes: bytes
    context: dict[str, Any] | None
    status: DescribeJobStatus
    tier: DescriptionResultTier | None = None
    result_generation: int = 0
    visual_facts: dict[str, Any] | None = None
    error: str | None = None
    result_fetched: bool = False


# Default retained-image budget is intentionally far below max_jobs * max_image_bytes.
# A budget equal to the theoretical worst case never engages under the per-image cap
# (VLMRP-S4-07). 256 MiB ≈ 10 full 25 MiB images queued/in-flight.
_DEFAULT_MAX_RETAINED_IMAGE_BYTES = 256 * 1024 * 1024


class InMemoryDescribeJobStore:
    """Process-local queue used by the MVP async route and tests."""

    def __init__(
        self,
        *,
        max_jobs: int = 1000,
        max_retained_image_bytes: int = _DEFAULT_MAX_RETAINED_IMAGE_BYTES,
    ) -> None:
        self._jobs: dict[str, DescribeJob] = {}
        self._order: list[str] = []
        self._max_jobs = max_jobs
        self._max_retained_image_bytes = max_retained_image_bytes
        self._retained_image_bytes = 0
        self._lock = Lock()

    def enqueue(
        self,
        *,
        tenant_id: uuid.UUID,
        media_id: int,
        image_bytes: bytes,
        context: dict[str, Any] | None,
    ) -> DescribeJob:
        image_len = len(image_bytes)
        with self._lock:
            self._evict_over_capacity_locked()
            if self._retained_image_bytes + image_len > self._max_retained_image_bytes:
                raise RuntimeError("describe job store image byte budget exceeded")
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
            self._retained_image_bytes += image_len
            return job

    def get(self, job_id: str) -> DescribeJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def queue_depth(self) -> int:
        """Jobs waiting for a worker (feeds GPU idle-reaper)."""
        with self._lock:
            return sum(1 for job in self._jobs.values() if job.status is DescribeJobStatus.QUEUED)

    def in_flight(self) -> int:
        """Jobs actively processing (RUNNING or PROVISIONAL; feeds idle-reaper)."""
        with self._lock:
            return sum(
                1
                for job in self._jobs.values()
                if job.status in {DescribeJobStatus.RUNNING, DescribeJobStatus.PROVISIONAL}
            )

    def load_snapshot(self) -> dict[str, int | float]:
        """JSON-shaped load for the out-of-band GPU idle reaper.

        Includes ``written_at`` (unix epoch) so reapers can treat stale dumps as busy.
        """
        import time

        with self._lock:
            queue_depth = sum(1 for job in self._jobs.values() if job.status is DescribeJobStatus.QUEUED)
            in_flight = sum(
                1
                for job in self._jobs.values()
                if job.status in {DescribeJobStatus.RUNNING, DescribeJobStatus.PROVISIONAL}
            )
            return {
                "queue_depth": queue_depth,
                "in_flight": in_flight,
                "written_at": time.time(),
            }

    def write_load_snapshot(self, path: str | Path) -> None:
        """Atomically dump load_snapshot() for the GPU idle reaper (VLMFIX-S2-01)."""
        import json
        import os

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.load_snapshot()
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, separators=(",", ":")))
        os.replace(tmp, target)

    def mark_result_fetched(self, job_id: str) -> DescribeJob | None:
        """Mark terminal job as fetched. Returns None if the job was evicted (S1-05)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.result_fetched:
                return job
            updated = replace(job, result_fetched=True)
            self._jobs[job_id] = updated
            return updated

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
        return self._replace_with_next_generation(
            job_id,
            status=DescribeJobStatus.PROVISIONAL,
            tier=DescriptionResultTier.PROVISIONAL_CPU,
            visual_facts=visual_facts,
            error=None,
        )

    def set_final(self, job_id: str, *, visual_facts: dict[str, Any]) -> DescribeJob:
        return self._replace_with_next_generation(
            job_id,
            status=DescribeJobStatus.FINAL,
            tier=DescriptionResultTier.FINAL_GPU,
            visual_facts=visual_facts,
            image_bytes=b"",
            error=None,
        )

    def set_degraded(self, job_id: str, *, error: str) -> DescribeJob:
        return self._replace(
            job_id,
            status=DescribeJobStatus.DEGRADED,
            image_bytes=b"",
            error=error,
        )

    def set_failed(self, job_id: str, *, error: str) -> DescribeJob:
        return self._replace(job_id, status=DescribeJobStatus.FAILED, image_bytes=b"", error=error)

    def _replace_with_next_generation(self, job_id: str, **changes: Any) -> DescribeJob:
        with self._lock:
            job = self._jobs[job_id]
            updated = replace(job, result_generation=job.result_generation + 1, **changes)
            self._jobs[job_id] = updated
            self._adjust_retained_bytes(job, updated)
            return updated

    def _replace(self, job_id: str, **changes: Any) -> DescribeJob:
        with self._lock:
            job = self._jobs[job_id]
            updated = replace(job, **changes)
            self._jobs[job_id] = updated
            self._adjust_retained_bytes(job, updated)
            return updated

    def _adjust_retained_bytes(self, before: DescribeJob, after: DescribeJob) -> None:
        before_len = len(before.image_bytes)
        after_len = len(after.image_bytes)
        if before_len != after_len:
            self._retained_image_bytes += after_len - before_len

    def _evict_over_capacity_locked(self) -> None:
        while len(self._jobs) >= self._max_jobs:
            for job_id in list(self._order):
                job = self._jobs[job_id]
                if job.status in _TERMINAL_STATUSES and job.result_fetched:
                    self._retained_image_bytes -= len(job.image_bytes)
                    self._jobs.pop(job_id, None)
                    self._order.remove(job_id)
                    break
            else:
                raise RuntimeError("describe job queue is full")
