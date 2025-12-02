"""Clustering metrics collection and comparison (Section 1: Metrics & Observability).

This module provides:
1. ClusteringMetrics dataclass for core KPIs
2. Snapshot functionality for baseline/comparison
3. Comparison utilities for A/B testing

See: docs/tasks/4.0/4.2.3/clustering-improvements-dev-plan.md (Section 1)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ClusteringMetrics:
    """Core metrics for clustering quality assessment.

    This dataclass captures key performance indicators (KPIs) that help
    measure clustering quality and detect regressions. Metrics are frozen
    to ensure immutability after collection.

    Attributes:
        total_identities: Number of face identities processed.
        total_clusters: Number of clusters created.
        singleton_count: Number of clusters with only one member.
        singleton_ratio: Fraction of clusters that are singletons (0-1).
        avg_cluster_size: Mean number of members per cluster.
        median_cluster_size: Median number of members per cluster.
        max_cluster_size: Largest cluster size.
        avg_intra_cluster_similarity: Mean similarity within clusters (higher = tighter).
        min_intra_cluster_similarity: Minimum intra-cluster similarity (catches outliers).
        suggestion_acceptance_rate: Fraction of suggestions accepted by users.
        merge_rate: Fraction of user-initiated cluster merges.
        split_rate: Fraction of user-initiated cluster splits.
        clustering_duration_ms: Time spent on clustering operation.
        batch_size: Number of identities in the current batch.
    """

    # Cluster distribution
    total_identities: int = 0
    total_clusters: int = 0
    singleton_count: int = 0
    singleton_ratio: float = 0.0

    # Cluster sizes
    avg_cluster_size: float = 0.0
    median_cluster_size: float = 0.0
    max_cluster_size: int = 0

    # Quality indicators
    avg_intra_cluster_similarity: float = 0.0
    min_intra_cluster_similarity: float = 0.0

    # User feedback (if available)
    suggestion_acceptance_rate: float = 0.0
    merge_rate: float = 0.0
    split_rate: float = 0.0

    # Performance
    clustering_duration_ms: float = 0.0
    batch_size: int = 0

    def to_snapshot(
        self,
        tenant_id: UUID | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """Create a timestamped snapshot of metrics for storage/comparison.

        Args:
            tenant_id: Optional tenant context for multi-tenant systems.
            label: Optional descriptive label (e.g., "baseline_before_slice_a").

        Returns:
            Dictionary with timestamp, optional tenant_id/label, and metrics.

        Example:
            >>> metrics = ClusteringMetrics(total_identities=100)
            >>> snapshot = metrics.to_snapshot(label="baseline")
            >>> snapshot["label"]
            'baseline'
        """
        snapshot: dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": asdict(self),
        }

        if tenant_id is not None:
            snapshot["tenant_id"] = str(tenant_id)

        if label is not None:
            snapshot["label"] = label

        return snapshot

    @staticmethod
    def compare(
        before: ClusteringMetrics,
        after: ClusteringMetrics,
    ) -> dict[str, dict[str, Any]]:
        """Compare two metrics snapshots to identify improvements.

        Computes delta and improvement status for key metrics.
        "Improved" means:
        - Lower singleton_ratio (fewer singletons)
        - Higher suggestion_acceptance_rate (better suggestions)
        - Higher avg_intra_cluster_similarity (tighter clusters)
        - Lower min_intra_cluster_similarity threshold violations

        Args:
            before: Baseline metrics snapshot.
            after: Post-change metrics snapshot.

        Returns:
            Dictionary mapping metric names to comparison results with
            before, after, delta, and improved flag.

        Example:
            >>> before = ClusteringMetrics(singleton_ratio=0.40)
            >>> after = ClusteringMetrics(singleton_ratio=0.25)
            >>> diff = ClusteringMetrics.compare(before, after)
            >>> diff["singleton_ratio"]["improved"]
            True
        """
        result: dict[str, dict[str, Any]] = {}

        # Metrics where LOWER is better
        lower_is_better = {"singleton_ratio", "merge_rate", "split_rate"}

        # Metrics where HIGHER is better
        higher_is_better = {
            "suggestion_acceptance_rate",
            "avg_intra_cluster_similarity",
            "min_intra_cluster_similarity",
            "avg_cluster_size",
        }

        before_dict = asdict(before)
        after_dict = asdict(after)

        for key in before_dict:
            before_val = before_dict[key]
            after_val = after_dict[key]

            # Skip non-numeric comparisons
            if not isinstance(before_val, (int, float)):
                continue

            delta = after_val - before_val

            if key in lower_is_better:
                improved = delta < 0
            elif key in higher_is_better:
                improved = delta > 0
            else:
                # Neutral metrics (like total_identities, batch_size)
                improved = None

            result[key] = {
                "before": before_val,
                "after": after_val,
                "delta": delta,
                "improved": improved,
            }

        return result
