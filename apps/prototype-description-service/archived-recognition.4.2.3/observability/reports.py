"""Batch job report dataclass for observability.

This module defines the BatchJobReport dataclass that collects statistics
during a batch clustering run for logging and visualization.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class BatchJobReport:
    """Summary statistics for a batch clustering job.

    Collects metrics during a batch run and provides data for:
    - Structured logging (via ClusteringLogger.log_batch_complete)
    - Chart generation (via ClusterVisualizer.generate_batch_report_chart)

    All decision counts use explicit labels (accept/suggest/reject) to
    clearly communicate what happened to each identity.

    Attributes:
        job_id: Unique identifier for this batch job.
        algorithm: Name of the clustering algorithm used.
        started_at: When the job started (UTC).
        completed_at: When the job completed (UTC).
        total_identities: Number of identities processed.
        accept_count: Identities assigned to clusters.
        suggest_count: Identities sent to human review.
        reject_count: Identities that stayed unclustered.
        clusters_created: New clusters created during this job.
        clusters_expanded: Existing clusters that received new members.
        avg_cluster_size: Mean cluster size after this job.
        max_cluster_size: Largest cluster size after this job.
        singleton_count: Clusters with only one member.
        avg_similarity: Mean intra-cluster similarity.
        min_similarity: Minimum intra-cluster similarity (catches outliers).

    Example:
        >>> report = BatchJobReport(
        ...     job_id=UUID("abc123..."),
        ...     algorithm="HDBSCAN",
        ...     started_at=datetime(2025, 12, 1, 14, 30, 0),
        ...     completed_at=datetime(2025, 12, 1, 14, 32, 15),
        ...     total_identities=150,
        ...     accept_count=120,
        ...     suggest_count=18,
        ...     reject_count=12,
        ... )
        >>> report.duration_ms
        135000.0
        >>> report.success_rate
        0.92
    """

    # Job identification
    job_id: UUID
    algorithm: str
    started_at: datetime
    completed_at: datetime = field(default_factory=datetime.utcnow)

    # Input metrics
    total_identities: int = 0

    # Decision outcomes (labeled explicitly as accept/suggest/reject)
    accept_count: int = 0
    suggest_count: int = 0
    reject_count: int = 0

    # Cluster metrics
    clusters_created: int = 0
    clusters_expanded: int = 0
    avg_cluster_size: float = 0.0
    max_cluster_size: int = 0
    singleton_count: int = 0

    # Quality metrics
    avg_similarity: float = 0.0
    min_similarity: float = 0.0

    @property
    def duration_ms(self) -> float:
        """Calculate job duration in milliseconds.

        Returns:
            Duration from started_at to completed_at in milliseconds.

        Example:
            >>> report.duration_ms
            135000.0
        """
        raise NotImplementedError("TODO: Implement duration calculation")

    @property
    def success_rate(self) -> float:
        """Calculate fraction of identities that were accepted or suggested.

        Returns:
            (accept_count + suggest_count) / total_identities, or 0.0 if no identities.

        Example:
            >>> report.success_rate
            0.92
        """
        raise NotImplementedError("TODO: Implement success rate calculation")

    @property
    def decision_breakdown(self) -> dict[str, int]:
        """Get decision counts as a dictionary for charting.

        Returns:
            Dictionary with keys 'Accepted', 'Suggested', 'Rejected'.

        Example:
            >>> report.decision_breakdown
            {'Accepted': 120, 'Suggested': 18, 'Rejected': 12}
        """
        raise NotImplementedError("TODO: Implement decision breakdown")

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dictionary for structured logging.

        Returns:
            Dictionary suitable for JSON logging output.

        Example:
            >>> report.to_log_dict()
            {'job_id': 'abc123...', 'algorithm': 'HDBSCAN', ...}
        """
        raise NotImplementedError("TODO: Implement to_log_dict serialization")

    def to_chart_title(self) -> str:
        """Generate chart title with algorithm and summary.

        Returns:
            Formatted title like "[HDBSCAN] Batch Job Summary - Dec 1, 2025"

        Example:
            >>> report.to_chart_title()
            '[HDBSCAN] Batch Job Summary - Dec 1, 2025 14:32:15'
        """
        raise NotImplementedError("TODO: Implement chart title generation")

    def to_chart_subtitle(self) -> str:
        """Generate chart subtitle with decision counts.

        Returns:
            Formatted subtitle like "Identities: 150 | Accepted: 120 | Suggested: 18 | Rejected: 12"

        Example:
            >>> report.to_chart_subtitle()
            'Identities: 150 | Accepted: 120 | Suggested: 18 | Rejected: 12'
        """
        raise NotImplementedError("TODO: Implement chart subtitle generation")
