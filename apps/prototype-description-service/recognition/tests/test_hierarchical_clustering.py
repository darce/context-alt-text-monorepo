"""Tests for HierarchicalClustering."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering


class TestHierarchicalClustering:
    """Test the HierarchicalClustering algorithm."""

    def test_cluster_similar_embeddings_stay_together(self) -> None:
        """Very similar embeddings should stay in one cluster."""
        hierarchical = HierarchicalClustering(distance_threshold=0.30)

        # 3 nearly identical embeddings (will form one cluster)
        base = np.random.randn(512)
        base = base / np.linalg.norm(base)

        embeddings = np.array(
            [
                base,
                base + np.random.randn(512) * 0.01,  # Very small noise
                base + np.random.randn(512) * 0.01,
            ]
        )
        # Normalize
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        labels = hierarchical.cluster_embeddings(embeddings)

        # All should be in the same cluster
        assert len(set(labels)) == 1

    def test_cluster_different_embeddings_separate(self) -> None:
        """Dissimilar embeddings should form separate clusters."""
        hierarchical = HierarchicalClustering(distance_threshold=0.30)

        # 2 groups of embeddings that are very different
        group1_base = np.zeros(512)
        group1_base[0:256] = 1.0
        group1_base = group1_base / np.linalg.norm(group1_base)

        group2_base = np.zeros(512)
        group2_base[256:512] = 1.0
        group2_base = group2_base / np.linalg.norm(group2_base)

        embeddings = np.array(
            [
                group1_base,
                group1_base + np.random.randn(512) * 0.02,
                group2_base,
                group2_base + np.random.randn(512) * 0.02,
            ]
        )
        # Normalize
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        labels = hierarchical.cluster_embeddings(embeddings)

        # Should form 2 clusters
        assert len(set(labels)) == 2
        # First two should be in same cluster
        assert labels[0] == labels[1]
        # Last two should be in same cluster
        assert labels[2] == labels[3]
        # But different from first group
        assert labels[0] != labels[2]

    def test_force_n_clusters(self) -> None:
        """When n_clusters is specified, should produce exactly that many."""
        hierarchical = HierarchicalClustering(distance_threshold=0.30)

        # Create 4 moderately different embeddings
        embeddings = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.9, 0.1, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.9, 0.1],
            ]
        )
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

        labels = hierarchical.cluster_embeddings(embeddings, n_clusters=2)

        assert len(set(labels)) == 2

    def test_single_embedding_returns_single_cluster(self) -> None:
        """Single embedding should return single cluster label."""
        hierarchical = HierarchicalClustering()

        embedding = np.random.randn(1, 512)
        embedding = embedding / np.linalg.norm(embedding)

        labels = hierarchical.cluster_embeddings(embedding)

        assert len(labels) == 1
        assert labels[0] == 0

    def test_split_identities_groups_correctly(self) -> None:
        """split_identities should return dict mapping labels to identities."""
        from unittest.mock import MagicMock

        hierarchical = HierarchicalClustering(distance_threshold=0.30)

        # Create mock identities with embeddings
        def make_identity(embedding: np.ndarray) -> MagicMock:
            mock = MagicMock()
            mock.embedding = embedding
            mock.id = id(embedding)  # Use memory address as unique ID
            return mock

        # Two distinct groups
        group1_base = np.array([1.0, 0.0, 0.0, 0.0])
        group2_base = np.array([0.0, 0.0, 1.0, 0.0])

        identities = [
            make_identity(group1_base),
            make_identity(group1_base * 0.99 + 0.01 * np.random.randn(4)),
            make_identity(group2_base),
            make_identity(group2_base * 0.99 + 0.01 * np.random.randn(4)),
        ]

        result = hierarchical.split_identities(identities)

        # Should have 2 groups
        assert len(result) == 2
        # Each group should have 2 members
        assert all(len(members) == 2 for members in result.values())
