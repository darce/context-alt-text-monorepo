"""
Batch job reporting scaffolding for clustering pipelines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass
class BatchJobReport:
    """Summarizes the outcome of a clustering or assignment job."""

    job_id: str
    algorithm: str
    started_at: datetime
    completed_at: datetime | None
    total_identities: int
    accept_count: int
    suggest_count: int
    reject_count: int
    clusters_created: int
    avg_similarity: float | None = None
    similarity_sum: float = 0.0
    similarity_count: int = 0

    def add_decision(
        self,
        outcome: str,
        similarity: float | None = None,
    ) -> None:
        """Accumulate decision metrics into the report."""
        self.total_identities += 1
        if outcome == "accept":
            self.accept_count += 1
        elif outcome == "suggest":
            self.suggest_count += 1
        else:
            self.reject_count += 1

        if similarity is not None:
            self.similarity_sum += similarity
            self.similarity_count += 1
            self.avg_similarity = self.similarity_sum / float(self.similarity_count)

    def duration_ms(self) -> float:
        """Return the job duration in milliseconds.

        Returns:
            float: Elapsed time in milliseconds.
        """
        if not self.completed_at:
            return 0.0
        delta = self.completed_at - self.started_at
        return delta.total_seconds() * 1000

    def success_rate(self) -> float:
        """Calculate the percentage of accepted assignments.

        Returns:
            float: Success rate between 0 and 1 inclusive.
        """
        if self.total_identities == 0:
            return 0.0
        return self.accept_count / self.total_identities

    def to_json(self) -> str:
        """Serialize the report to JSON for logging or storage."""
        payload: dict[str, Any] = asdict(self)
        payload["started_at"] = self.started_at.isoformat()
        payload["completed_at"] = self.completed_at.isoformat() if self.completed_at else None
        payload["duration_ms"] = self.duration_ms()
        payload["success_rate"] = self.success_rate()
        return json.dumps(payload)
