"""Tests for clustering metrics collection (Section 1: Metrics & Observability)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

import pytest

from recognition.application.metrics import ClusteringMetrics


class TestClusteringMetricsDataclass:
    """Tests for the ClusteringMetrics dataclass structure."""

    def test_default_values(self) -> None:
        """Metrics should have sensible defaults."""
        metrics = ClusteringMetrics()

        assert metrics.total_identities == 0
        assert metrics.total_clusters == 0
        assert metrics.singleton_count == 0
        assert metrics.singleton_ratio == 0.0
        assert metrics.avg_cluster_size == 0.0
        assert metrics.median_cluster_size == 0.0
        assert metrics.max_cluster_size == 0
        assert metrics.avg_intra_cluster_similarity == 0.0
        assert metrics.min_intra_cluster_similarity == 0.0
        assert metrics.suggestion_acceptance_rate == 0.0
        assert metrics.merge_rate == 0.0
        assert metrics.split_rate == 0.0
        assert metrics.clustering_duration_ms == 0.0
        assert metrics.batch_size == 0

    def test_all_fields_serializable(self) -> None:
        """Metrics should be convertible to dict for JSON serialization."""
        metrics = ClusteringMetrics(
            total_identities=100,
            total_clusters=25,
            singleton_count=10,
            singleton_ratio=0.40,
            avg_cluster_size=4.0,
            median_cluster_size=3.0,
            max_cluster_size=15,
            avg_intra_cluster_similarity=0.85,
            min_intra_cluster_similarity=0.65,
            suggestion_acceptance_rate=0.70,
            merge_rate=0.05,
            split_rate=0.02,
            clustering_duration_ms=150.5,
            batch_size=50,
        )

        data = asdict(metrics)
        assert isinstance(data, dict)
        assert data["total_identities"] == 100
        assert data["singleton_ratio"] == 0.40

    def test_computed_singleton_ratio(self) -> None:
        """Singleton ratio should be singleton_count / total_clusters."""
        metrics = ClusteringMetrics(
            total_clusters=20,
            singleton_count=8,
            singleton_ratio=8 / 20,  # 0.40
        )
        assert abs(metrics.singleton_ratio - 0.40) < 0.001

    def test_immutable_after_creation(self) -> None:
        """Metrics should be frozen (immutable) after creation."""
        metrics = ClusteringMetrics(total_identities=100)

        with pytest.raises(Exception):  # FrozenInstanceError
            metrics.total_identities = 200  # type: ignore


class TestClusteringMetricsSnapshot:
    """Tests for metrics snapshot functionality."""

    def test_snapshot_includes_timestamp(self) -> None:
        """A snapshot should include when it was taken."""
        metrics = ClusteringMetrics(total_identities=50)
        snapshot = metrics.to_snapshot()

        assert "timestamp" in snapshot
        assert "metrics" in snapshot
        assert snapshot["metrics"]["total_identities"] == 50

    def test_snapshot_includes_tenant_id(self) -> None:
        """Snapshot should include tenant context when provided."""
        metrics = ClusteringMetrics(total_identities=50)
        tenant_id = uuid4()
        snapshot = metrics.to_snapshot(tenant_id=tenant_id)

        assert snapshot["tenant_id"] == str(tenant_id)

    def test_snapshot_includes_label(self) -> None:
        """Snapshot can include a descriptive label."""
        metrics = ClusteringMetrics(total_identities=50)
        snapshot = metrics.to_snapshot(label="baseline_before_slice_a")

        assert snapshot["label"] == "baseline_before_slice_a"


class TestClusteringMetricsComparison:
    """Tests for comparing metrics snapshots."""

    def test_compare_singleton_improvement(self) -> None:
        """Should detect singleton ratio improvement."""
        before = ClusteringMetrics(
            total_clusters=100,
            singleton_count=40,
            singleton_ratio=0.40,
        )
        after = ClusteringMetrics(
            total_clusters=80,
            singleton_count=20,
            singleton_ratio=0.25,
        )

        diff = ClusteringMetrics.compare(before, after)

        assert diff["singleton_ratio"]["before"] == 0.40
        assert diff["singleton_ratio"]["after"] == 0.25
        assert abs(diff["singleton_ratio"]["delta"] - (-0.15)) < 0.001
        assert diff["singleton_ratio"]["improved"] is True

    def test_compare_acceptance_rate_improvement(self) -> None:
        """Should detect suggestion acceptance rate improvement."""
        before = ClusteringMetrics(suggestion_acceptance_rate=0.60)
        after = ClusteringMetrics(suggestion_acceptance_rate=0.75)

        diff = ClusteringMetrics.compare(before, after)

        assert abs(diff["suggestion_acceptance_rate"]["delta"] - 0.15) < 0.001
        assert diff["suggestion_acceptance_rate"]["improved"] is True

    def test_compare_intra_cluster_similarity_improvement(self) -> None:
        """Should detect intra-cluster similarity improvement."""
        before = ClusteringMetrics(avg_intra_cluster_similarity=0.75)
        after = ClusteringMetrics(avg_intra_cluster_similarity=0.82)

        diff = ClusteringMetrics.compare(before, after)

        # Higher similarity is better
        assert diff["avg_intra_cluster_similarity"]["improved"] is True
