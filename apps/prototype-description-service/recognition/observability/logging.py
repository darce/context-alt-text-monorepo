"""
Logging utilities for recognition clustering workflows.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from recognition.observability.decisions import (
    CurationEventLog,
    CurationEventType,
    DecisionLog,
    DecisionType,
)
from recognition.observability.recognition_runs import RecognitionRunContext
from recognition.observability.reports import BatchJobReport


class ClusteringLogger:
    """Structured logger for clustering and assignment decisions."""

    def __init__(
        self, logger: logging.Logger | None = None, *, run_context: RecognitionRunContext | None = None
    ) -> None:
        """Create a logger wrapper for clustering flows.

        Args:
            logger: Optional preconfigured logger. If omitted, a module logger is used.
            run_context: Optional recognition run context for emitting `recognition_events`.
        """
        self.logger = logger or logging.getLogger(__name__)
        self._run_context = run_context

    def bind_run_context(self, context: RecognitionRunContext | None) -> None:
        """Attach or clear the active recognition run context."""
        self._run_context = context

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
        media_id: str | None = None,
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
                "media_id": str(media_id) if media_id else None,
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

        if self._run_context is not None:
            payload: dict[str, Any] = dict(metadata or {})
            payload.update(
                {
                    "decision": decision.value,
                    "similarity": similarity,
                    "reason": reason,
                    "algorithm": algorithm,
                    "job_id": job_id,
                    "media_id": str(media_id) if media_id else None,
                }
            )
            self._run_context.add_event(
                event_type="assignment_decision",
                timestamp=ts,
                identity_id=str(identity_id),
                cluster_id=str(cluster_id) if cluster_id else None,
                payload=payload,
            )

        return decision_log

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

    def log_initial_assignment(
        self,
        *,
        identity_id: str,
        media_id: int,
        cluster_id: str,
        similarity: float,
        algorithm: str,
        tenant_id: str,
    ) -> None:
        """Log when an identity is first assigned to a newly created cluster.

        This fills the logging gap where `persist_new_cluster` creates clusters
        but doesn't emit per-identity assignment logs like the gate does for
        existing clusters.

        Args:
            identity_id: UUID of the identity being assigned
            media_id: WordPress media ID for traceability
            cluster_id: UUID of the newly created cluster
            similarity: Similarity to cluster centroid/seed (1.0 for first member)
            algorithm: Clustering algorithm that created the cluster (e.g., "hdbscan")
            tenant_id: Tenant UUID for multi-tenancy

        Example log output:
            [clustering] INITIAL_ASSIGNED identity=abc123 media_id=6643 cluster=def456
            similarity=1.0000 algorithm=hdbscan tenant_id=xyz789
        """
        self.logger.info(
            "clustering_initial_assignment",
            extra={
                "identity_id": identity_id,
                "media_id": media_id,
                "cluster_id": cluster_id,
                "similarity": similarity,
                "algorithm": algorithm,
                "tenant_id": tenant_id,
                "timestamp": datetime.now(tz=UTC).isoformat(),
            },
        )

    # ========================================================================
    # USER CURATION EVENT LOGGING
    # ========================================================================

    def log_cluster_renamed(
        self,
        cluster_id: str,
        old_label: str | None,
        new_label: str | None,
        tenant_id: str,
    ) -> CurationEventLog:
        """Record a cluster label change.

        Args:
            cluster_id: The cluster being renamed.
            old_label: Previous label (None if unlabeled).
            new_label: New label (None if cleared).
            tenant_id: Tenant performing the action.

        Returns:
            CurationEventLog: Structured log record.
        """
        ts = datetime.now(tz=UTC)
        details = {"old_label": old_label, "new_label": new_label}
        event_log = CurationEventLog(
            event_type=CurationEventType.RENAME,
            cluster_id=cluster_id,
            tenant_id=tenant_id,
            timestamp=ts,
            details=details,
        )
        self.logger.info(
            "curation_event",
            extra={
                "event_type": CurationEventType.RENAME.value,
                "cluster_id": cluster_id,
                "tenant_id": tenant_id,
                "old_label": old_label,
                "new_label": new_label,
                "timestamp": ts.isoformat(),
            },
        )
        return event_log

    def log_cluster_split(
        self,
        original_cluster_id: str,
        new_cluster_ids: list[str],
        moved_counts: list[int],
        tenant_id: str,
    ) -> CurationEventLog:
        """Record a cluster split operation.

        Args:
            original_cluster_id: The cluster being split.
            new_cluster_ids: IDs of newly created clusters.
            moved_counts: Number of members moved to each new cluster.
            tenant_id: Tenant performing the action.

        Returns:
            CurationEventLog: Structured log record.
        """
        ts = datetime.now(tz=UTC)
        details = {
            "original_cluster_id": original_cluster_id,
            "new_cluster_ids": new_cluster_ids,
            "moved_counts": moved_counts,
            "total_moved": sum(moved_counts),
        }
        event_log = CurationEventLog(
            event_type=CurationEventType.SPLIT,
            cluster_id=original_cluster_id,
            tenant_id=tenant_id,
            timestamp=ts,
            details=details,
        )
        self.logger.info(
            "curation_event",
            extra={
                "event_type": CurationEventType.SPLIT.value,
                "original_cluster_id": original_cluster_id,
                "new_cluster_ids": new_cluster_ids,
                "moved_counts": moved_counts,
                "total_moved": sum(moved_counts),
                "tenant_id": tenant_id,
                "timestamp": ts.isoformat(),
            },
        )
        return event_log

    def log_curation_action(
        self,
        action: CurationEventType,
        identity_id: str,
        target_cluster_id: str | None = None,
        previous_cluster_id: str | None = None,
        similarity: float | None = None,
        tenant_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a generic curation action (e.g., assignment, removal).

        Args:
            action: Type of curation event.
            identity_id: Identity affected.
            target_cluster_id: New cluster ID (if applicable).
            previous_cluster_id: Old cluster ID (if applicable).
            similarity: Similarity score (if applicable).
            tenant_id: Tenant ID.
            details: Additional metadata.
        """
        extra = {
            "event_type": action.value,
            "identity_id": identity_id,
            "target_cluster_id": target_cluster_id,
            "previous_cluster_id": previous_cluster_id,
            "similarity": similarity,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }
        if details:
            extra.update(details)

        self.logger.info("curation_event", extra=extra)
