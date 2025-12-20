"""Job domain model and status definitions (Job Orchestration, Phase 7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states for orchestration jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Supported job categories."""

    ANALYZE = "analyze"
    CLUSTERING = "clustering"


@dataclass
class Job:
    """Represents a background job with progress tracking."""

    id: str
    type: JobType
    tenant_id: str
    status: JobStatus = JobStatus.PENDING
    progress_completed: int = 0
    progress_total: int = 0
    error_message: str | None = None
    message: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime | None = None

    def update_progress(self, completed: int, total: int) -> None:
        self.progress_completed = completed
        self.progress_total = total

    def complete(self) -> None:
        self.status = JobStatus.COMPLETED
        self.finished_at = datetime.now(tz=UTC)

    def fail(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.error_message = error
        self.finished_at = datetime.now(tz=UTC)
