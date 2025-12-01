"""Structured logging utilities for clustering events.

This module provides consistent structured logging for clustering operations,
enabling metrics extraction and A/B testing comparison.

See: docs/tasks/4.0/4.2.3/clustering-improvements-dev-plan.md (Section 1.2)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class ClusteringEvent(str, Enum):
    """Enumeration of clustering events for structured logging."""

    # Batch lifecycle
    BATCH_START = "clustering_batch_start"
    BATCH_COMPLETE = "clustering_batch_complete"

    # Matching events
    REP_MATCH_ACCEPT = "rep_match_accept"
    REP_MATCH_REJECT = "rep_match_reject"
    REP_MATCH_BORDERLINE = "rep_match_borderline"
    CENTROID_MATCH_ACCEPT = "centroid_match_accept"
    CENTROID_MATCH_REJECT = "centroid_match_reject"

    # Validation events
    BORDERLINE_VALIDATION_PASS = "borderline_validation_pass"
    BORDERLINE_VALIDATION_FAIL = "borderline_validation_fail"
    MEMBER_VALIDATION_PASS = "member_validation_pass"
    MEMBER_VALIDATION_FAIL = "member_validation_fail"

    # Cluster lifecycle
    CLUSTER_CREATED = "cluster_created"
    CLUSTER_MERGED = "cluster_merged"
    CLUSTER_SPLIT = "cluster_split"

    # Confidence weighting (Option C)
    THRESHOLD_ADJUSTED = "threshold_adjusted"

    # Algorithm selection
    ALGORITHM_SELECTED = "algorithm_selected"

    # User feedback events (for precision/recall measurement)
    # These are ground truth signals from user corrections
    SUGGESTION_ACCEPTED = "suggestion_accepted"  # User confirms match → TRUE POSITIVE
    SUGGESTION_REJECTED = "suggestion_rejected"  # User rejects match → FALSE POSITIVE
    USER_MERGE = "user_merge"  # User manually merges → FALSE NEGATIVE (under-merged)
    USER_SPLIT = "user_split"  # User splits/removes identity → FALSE POSITIVE (over-matched)
    CLUSTER_LABELED = "cluster_labeled"  # User assigns name → confident cluster


@dataclass
class ClusteringLogEntry:
    """Structured log entry for clustering events.

    Provides consistent fields for all clustering operations,
    enabling easy grep/parsing for metrics extraction.
    """

    event: ClusteringEvent
    tenant_id: UUID
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Optional context
    identity_id: UUID | None = None
    cluster_id: UUID | None = None
    media_id: int | None = None

    # Similarity/threshold info
    similarity: float | None = None
    threshold: float | None = None
    effective_threshold: float | None = None

    # Confidence weighting
    confidence: float | None = None
    det_score: float | None = None
    bbox_area: int | None = None

    # Batch context
    batch_size: int | None = None
    processed_count: int | None = None

    # Cluster stats
    cluster_count: int | None = None
    singleton_count: int | None = None
    assigned_count: int | None = None
    created_count: int | None = None

    # Duration
    duration_ms: float | None = None

    # Algorithm info
    algorithm: str | None = None

    # Extra context
    extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None:
                if isinstance(value, UUID):
                    result[key] = str(value)
                elif isinstance(value, datetime):
                    result[key] = value.isoformat()
                elif isinstance(value, ClusteringEvent):
                    result[key] = value.value
                else:
                    result[key] = value
        return result

    def log(self, level: int = logging.INFO) -> None:
        """Emit this entry as a structured log message."""
        data = self.to_dict()
        event_name = data.pop("event")
        # Remove timestamp - already provided by logging formatter
        data.pop("timestamp", None)

        # Format as structured log line for easy grep
        # Format: EVENT_NAME key1=value1 key2=value2 ...
        parts = [f"{k}={v}" for k, v in data.items() if k != "extra"]
        if self.extra:
            for k, v in self.extra.items():
                parts.append(f"{k}={v}")

        message = f"{event_name} {' '.join(parts)}"
        logger.log(level, message)


def log_batch_start(
    tenant_id: UUID,
    batch_size: int,
    existing_clusters: int,
    algorithm: str = "incremental",
) -> None:
    """Log the start of a clustering batch."""
    ClusteringLogEntry(
        event=ClusteringEvent.BATCH_START,
        tenant_id=tenant_id,
        batch_size=batch_size,
        cluster_count=existing_clusters,
        algorithm=algorithm,
    ).log()


def log_batch_complete(
    tenant_id: UUID,
    batch_size: int,
    assigned_count: int,
    created_count: int,
    singleton_count: int,
    duration_ms: float,
    algorithm: str = "incremental",
) -> None:
    """Log the completion of a clustering batch."""
    ClusteringLogEntry(
        event=ClusteringEvent.BATCH_COMPLETE,
        tenant_id=tenant_id,
        batch_size=batch_size,
        assigned_count=assigned_count,
        created_count=created_count,
        singleton_count=singleton_count,
        duration_ms=duration_ms,
        algorithm=algorithm,
    ).log()


def log_rep_match(
    tenant_id: UUID,
    identity_id: UUID,
    cluster_id: UUID | None,
    similarity: float,
    threshold: float,
    accepted: bool,
    effective_threshold: float | None = None,
    confidence: float | None = None,
    is_borderline: bool = False,
) -> None:
    """Log a representative matching decision."""
    if is_borderline:
        event = ClusteringEvent.REP_MATCH_BORDERLINE
    elif accepted:
        event = ClusteringEvent.REP_MATCH_ACCEPT
    else:
        event = ClusteringEvent.REP_MATCH_REJECT

    ClusteringLogEntry(
        event=event,
        tenant_id=tenant_id,
        identity_id=identity_id,
        cluster_id=cluster_id,
        similarity=similarity,
        threshold=threshold,
        effective_threshold=effective_threshold,
        confidence=confidence,
    ).log()


def log_threshold_adjusted(
    tenant_id: UUID,
    identity_id: UUID,
    base_threshold: float,
    effective_threshold: float,
    confidence: float,
    det_score: float,
    bbox_area: int,
) -> None:
    """Log a confidence-weighted threshold adjustment."""
    ClusteringLogEntry(
        event=ClusteringEvent.THRESHOLD_ADJUSTED,
        tenant_id=tenant_id,
        identity_id=identity_id,
        threshold=base_threshold,
        effective_threshold=effective_threshold,
        confidence=confidence,
        det_score=det_score,
        bbox_area=bbox_area,
    ).log()


def log_validation_result(
    tenant_id: UUID,
    identity_id: UUID,
    cluster_id: UUID,
    validation_type: str,  # "borderline" or "member"
    passed: bool,
    similarity: float,
    threshold: float,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log a validation result (borderline or member)."""
    if validation_type == "borderline":
        event = ClusteringEvent.BORDERLINE_VALIDATION_PASS if passed else ClusteringEvent.BORDERLINE_VALIDATION_FAIL
    else:
        event = ClusteringEvent.MEMBER_VALIDATION_PASS if passed else ClusteringEvent.MEMBER_VALIDATION_FAIL

    ClusteringLogEntry(
        event=event,
        tenant_id=tenant_id,
        identity_id=identity_id,
        cluster_id=cluster_id,
        similarity=similarity,
        threshold=threshold,
        extra=extra,
    ).log()


def log_cluster_created(
    tenant_id: UUID,
    cluster_id: UUID,
    member_count: int = 1,
    algorithm: str = "incremental",
) -> None:
    """Log cluster creation."""
    ClusteringLogEntry(
        event=ClusteringEvent.CLUSTER_CREATED,
        tenant_id=tenant_id,
        cluster_id=cluster_id,
        extra={"member_count": member_count},
        algorithm=algorithm,
    ).log()


def log_cluster_merged(
    tenant_id: UUID,
    source_cluster_id: UUID,
    target_cluster_id: UUID,
    moved_count: int,
    similarity: float,
) -> None:
    """Log cluster merge operation."""
    ClusteringLogEntry(
        event=ClusteringEvent.CLUSTER_MERGED,
        tenant_id=tenant_id,
        cluster_id=target_cluster_id,
        similarity=similarity,
        extra={
            "source_cluster_id": str(source_cluster_id),
            "moved_count": moved_count,
        },
    ).log()


def log_algorithm_selected(
    tenant_id: UUID,
    algorithm: str,
    batch_size: int,
    reason: str,
) -> None:
    """Log algorithm selection decision."""
    ClusteringLogEntry(
        event=ClusteringEvent.ALGORITHM_SELECTED,
        tenant_id=tenant_id,
        algorithm=algorithm,
        batch_size=batch_size,
        extra={"reason": reason},
    ).log()


# =============================================================================
# User Feedback Events (Ground Truth for Precision/Recall)
# =============================================================================


def log_suggestion_accepted(
    tenant_id: UUID,
    identity_id: UUID,
    cluster_id: UUID,
    similarity: float,
    cluster_size: int,
) -> None:
    """Log user accepting a suggestion → TRUE POSITIVE signal.

    Args:
        tenant_id: Tenant UUID
        identity_id: Identity that was suggested
        cluster_id: Cluster the identity was suggested for
        similarity: Original match similarity when suggestion was created
        cluster_size: Size of target cluster at acceptance time
    """
    ClusteringLogEntry(
        event=ClusteringEvent.SUGGESTION_ACCEPTED,
        tenant_id=tenant_id,
        identity_id=identity_id,
        cluster_id=cluster_id,
        similarity=similarity,
        extra={"cluster_size": cluster_size},
    ).log()


def log_suggestion_rejected(
    tenant_id: UUID,
    identity_id: UUID,
    cluster_id: UUID,
    similarity: float,
    cluster_size: int,
) -> None:
    """Log user rejecting a suggestion → FALSE POSITIVE signal.

    Args:
        tenant_id: Tenant UUID
        identity_id: Identity that was suggested
        cluster_id: Cluster the identity was suggested for
        similarity: Original match similarity when suggestion was created
        cluster_size: Size of target cluster at rejection time
    """
    ClusteringLogEntry(
        event=ClusteringEvent.SUGGESTION_REJECTED,
        tenant_id=tenant_id,
        identity_id=identity_id,
        cluster_id=cluster_id,
        similarity=similarity,
        extra={"cluster_size": cluster_size},
    ).log()


def log_user_merge(
    tenant_id: UUID,
    source_cluster_id: UUID,
    target_cluster_id: UUID,
    moved_count: int,
    source_size: int,
    target_size: int,
) -> None:
    """Log user manually merging clusters → FALSE NEGATIVE signal (system under-merged).

    Args:
        tenant_id: Tenant UUID
        source_cluster_id: Cluster being merged from
        target_cluster_id: Cluster being merged into
        moved_count: Number of identities moved
        source_size: Original size of source cluster
        target_size: Original size of target cluster
    """
    ClusteringLogEntry(
        event=ClusteringEvent.USER_MERGE,
        tenant_id=tenant_id,
        cluster_id=target_cluster_id,
        extra={
            "source_cluster_id": str(source_cluster_id),
            "moved_count": moved_count,
            "source_size": source_size,
            "target_size": target_size,
        },
    ).log()


def log_user_split(
    tenant_id: UUID,
    identity_id: UUID,
    source_cluster_id: UUID,
    target_cluster_id: UUID | None,
    source_size: int,
    action: str = "remove",
) -> None:
    """Log user removing/moving identity from cluster → FALSE POSITIVE signal (system over-matched).

    Args:
        tenant_id: Tenant UUID
        identity_id: Identity being removed/moved
        source_cluster_id: Cluster identity was removed from
        target_cluster_id: New cluster (if reassigned) or None (if just removed)
        source_size: Size of source cluster before removal
        action: "remove" (no new cluster), "reassign" (moved to existing), or "split" (new cluster)
    """
    ClusteringLogEntry(
        event=ClusteringEvent.USER_SPLIT,
        tenant_id=tenant_id,
        identity_id=identity_id,
        cluster_id=source_cluster_id,
        extra={
            "target_cluster_id": str(target_cluster_id) if target_cluster_id else None,
            "source_size": source_size,
            "action": action,
        },
    ).log()


def log_cluster_labeled(
    tenant_id: UUID,
    cluster_id: UUID,
    label: str,
    cluster_size: int,
    is_first_label: bool = True,
) -> None:
    """Log user labeling a cluster → confidence signal.

    Args:
        tenant_id: Tenant UUID
        cluster_id: Cluster being labeled
        label: The label assigned
        cluster_size: Size of cluster when labeled
        is_first_label: True if this is the initial label, False if rename
    """
    ClusteringLogEntry(
        event=ClusteringEvent.CLUSTER_LABELED,
        tenant_id=tenant_id,
        cluster_id=cluster_id,
        extra={
            "label": label,
            "cluster_size": cluster_size,
            "is_first_label": is_first_label,
        },
    ).log()
