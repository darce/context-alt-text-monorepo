"""Result types for incremental clustering jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    created_cluster_ids: list[str] = field(default_factory=list)
    accepted: int = 0
    suggested: int = 0
    rejected: int = 0
    probe_space_skip: dict[str, object] = field(default_factory=dict)
