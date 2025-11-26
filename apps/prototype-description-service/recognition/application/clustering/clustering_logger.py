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
