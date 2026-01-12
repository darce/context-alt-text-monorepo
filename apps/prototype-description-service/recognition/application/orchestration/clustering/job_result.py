"""Result types for incremental clustering jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ClusterJobResult:
    """Summary metrics for a clustering job run."""

    job_id: str
    started_at: datetime
    finished_at: datetime
    completed: int
    total: int
    clusters_created: int
    accepted: int = 0
    suggested: int = 0
    rejected: int = 0
