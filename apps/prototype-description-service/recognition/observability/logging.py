"""
Logging utilities for recognition clustering workflows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from recognition.observability.decisions import DecisionLog, DecisionType
from recognition.observability.reports import BatchJobReport


class ClusteringLogger:
    """Structured logger for clustering and assignment decisions."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        """Create a logger wrapper for clustering flows.

        Args:
            logger: Optional preconfigured logger. If omitted, a module logger is used.
        """
        self.logger = logger or logging.getLogger(__name__)

    def log_decision(
        self,
        identity_id: str,
        cluster_id: str | None,
        decision: DecisionType,
        similarity: float | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        algorithm: str | None = None,
        job_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> DecisionLog:
        """Record a single assignment decision for observability."""
        ts = timestamp or datetime.now(tz=UTC)
        decision_log = DecisionLog(
            identity_id=identity_id,
            cluster_id=cluster_id,
            decision=decision,
            similarity=similarity,
            reason=reason,
            timestamp=ts,
        )
        self.logger.info(
            "decision",
            extra={
                "identity_id": str(identity_id),
                "cluster_id": str(cluster_id) if cluster_id else None,
                "decision": decision.value,
                "similarity": similarity,
                "reason": reason,
                "metadata": metadata or {},
                "timestamp": ts.isoformat(),
                "algorithm": algorithm,
                "job_id": job_id,
            },
        )
        return decision_log

    def log_batch_start(self, identity_count: int, algorithm: str, tenant_id: str | None = None) -> None:
        """Emit a log entry when a clustering batch begins.

        Args:
            identity_count: Number of identities in the batch.
            algorithm: Name of the algorithm selected for clustering.
            tenant_id: Optional tenant identifier.
        """
        self.logger.info(
            "clustering_batch_start",
            extra={
                "identity_count": identity_count,
                "algorithm": algorithm,
                "tenant_id": tenant_id,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
        )

    def log_batch_complete(self, report: BatchJobReport) -> None:
        """Emit a log entry when a clustering batch completes.

        Args:
            report: Summary report containing batch outcomes.
        """
        self.logger.info(
            "clustering_batch_complete",
            extra={
                "job_id": str(report.job_id),
                "algorithm": report.algorithm,
                "started_at": report.started_at.isoformat(),
                "completed_at": report.completed_at.isoformat() if report.completed_at else None,
                "total_identities": report.total_identities,
                "accept_count": report.accept_count,
                "suggest_count": report.suggest_count,
                "reject_count": report.reject_count,
                "clusters_created": report.clusters_created,
                "avg_similarity": report.avg_similarity,
                "duration_ms": report.duration_ms() if report.completed_at else None,
                "success_rate": report.success_rate(),
                "payload": report.to_json(),
            },
        )
