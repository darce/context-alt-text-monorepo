"""Tests for pairwise validation in graph discovery helpers."""

import numpy as np
import pytest

from recognition.application.discovery.graph.helpers import validate_pairwise_similarities


class TestValidatePairwiseSimilarities:
    """Test cases for validate_pairwise_similarities function."""

    def test_two_similar_vectors_pass(self) -> None:
        """Two vectors with high similarity should pass validation."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([0.95, 0.31, 0.0], dtype=np.float32)
        vec2 = vec2 / np.linalg.norm(vec2)  # normalize

        is_valid, min_sim = validate_pairwise_similarities([vec1, vec2], 0.80)

        assert is_valid is True
        assert min_sim >= 0.80

    def test_two_dissimilar_vectors_fail(self) -> None:
        """Two vectors with low similarity should fail validation."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([0.1, 0.99, 0.0], dtype=np.float32)
        vec2 = vec2 / np.linalg.norm(vec2)

        is_valid, min_sim = validate_pairwise_similarities([vec1, vec2], 0.80)

        assert is_valid is False
        assert min_sim < 0.80

    def test_media_6665_6689_false_positive_scenario(self) -> None:
        """Simulate the false positive where 14.7% similar faces were grouped.

        This test verifies that the fix would reject the cluster that
        incorrectly grouped Ochre Ridgeway (6665) with Sable Verity (6689).
        """
        # Simulate ~14.7% cosine similarity
        vec_faith = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec_laura = np.array([0.147, 0.989, 0.0], dtype=np.float32)
        vec_laura = vec_laura / np.linalg.norm(vec_laura)

        is_valid, min_sim = validate_pairwise_similarities([vec_faith, vec_laura], 0.80)

        assert is_valid is False, "14.7% similarity should be rejected"
        assert min_sim < 0.20, f"Expected min_sim < 0.20, got {min_sim}"

    def test_single_vector_always_valid(self) -> None:
        """A single vector (singleton) should always be valid."""
        vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)

        is_valid, min_sim = validate_pairwise_similarities([vec], 0.80)

        assert is_valid is True
        assert min_sim == 1.0

    def test_empty_list_valid(self) -> None:
        """An empty list should be valid (edge case)."""
        is_valid, min_sim = validate_pairwise_similarities([], 0.80)

        assert is_valid is True
        assert min_sim == 1.0

    def test_three_vectors_one_pair_fails(self) -> None:
        """If any pair fails, the whole group should fail."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([0.9, 0.436, 0.0], dtype=np.float32)  # ~0.90 sim to vec1
        vec2 = vec2 / np.linalg.norm(vec2)
        vec3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)  # ~0.0 sim to vec1

        is_valid, min_sim = validate_pairwise_similarities([vec1, vec2, vec3], 0.80)

        assert is_valid is False, "Should fail when any pair is below threshold"
        assert min_sim < 0.80

    def test_three_similar_vectors_pass(self) -> None:
        """Three vectors all similar to each other should pass."""
        vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        vec2 = np.array([0.95, 0.31, 0.0], dtype=np.float32)
        vec2 = vec2 / np.linalg.norm(vec2)
        vec3 = np.array([0.92, 0.39, 0.0], dtype=np.float32)
        vec3 = vec3 / np.linalg.norm(vec3)

        is_valid, min_sim = validate_pairwise_similarities([vec1, vec2, vec3], 0.80)

        assert is_valid is True
        assert min_sim >= 0.80
