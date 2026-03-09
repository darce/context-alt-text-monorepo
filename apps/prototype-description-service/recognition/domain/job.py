"""Job domain model and status definitions (Job Orchestration, Phase 7.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


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
    CURATION = "curation"
    SPLIT = "split"


class JobPhase(str, Enum):
    """High-level phase markers for progress reporting."""

    QUEUED = "queued"
    DETECTING = "detecting"
    CLUSTERING = "clustering"
    AWAITING_PROJECTION = "awaiting_projection"
    COMPLETE = "complete"


@dataclass(frozen=True)
class ProjectionStatus:
    """Projection acknowledgement state for a pipeline job."""

    snapshot_version: int
    source_job_id: str
    acknowledged_at: datetime | None = None


class SplitJobPayload(BaseModel):
    """Payload for async split jobs.

    Attributes:
        cluster_id: Target cluster to split.
        n_clusters: Desired cluster count.
        anchor_identity_id: Optional anchor for label retention.
        split_mode: Optional mode hint.
    """

    cluster_id: str = Field(..., description="Target cluster to split.")
    n_clusters: int = Field(default=0, ge=0, description="Desired cluster count (0=auto).")
    anchor_identity_id: str | None = Field(default=None, description="Optional anchor identity ID.")
    split_mode: str | None = Field(default=None, description="Optional split mode hint.")


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
    payload: dict[str, object] | None = None
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
