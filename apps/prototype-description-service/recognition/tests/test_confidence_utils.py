"""Tests for confidence weighting utilities (Slice A: Option C)."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.confidence_utils import (
    adaptive_threshold,
    compute_detection_confidence,
    compute_pair_confidence,
)
from recognition.application.representatives.representative_matcher import RepresentativeMatcher


class TestComputeDetectionConfidence:
    """Tests for single detection confidence calculation."""

    def test_high_quality_large_face_returns_high_confidence(self) -> None:
        """A high det_score with large bbox should yield high confidence."""
        # det_score=0.98, bbox_area=40000 (well above min 10000)
        result = compute_detection_confidence(det_score=0.98, bbox_area=40000)
        assert result >= 0.95, f"Expected >= 0.95, got {result}"

    def test_low_quality_small_face_returns_low_confidence(self) -> None:
        """A low det_score with small bbox should yield low confidence."""
        # det_score=0.65, bbox_area=2500 (25% of min)
        result = compute_detection_confidence(det_score=0.65, bbox_area=2500)
        assert result < 0.65, f"Expected < 0.65, got {result}"

    def test_high_quality_small_face_penalized(self) -> None:
        """High det_score but small face should be penalized."""
        # det_score=0.95, bbox_area=5000 (50% of min)
        result = compute_detection_confidence(det_score=0.95, bbox_area=5000)
        # Geometric mean of 0.95 and 0.5 = sqrt(0.475) ≈ 0.689
        assert 0.65 < result < 0.75, f"Expected 0.65-0.75, got {result}"

    def test_low_quality_large_face_penalized(self) -> None:
        """Low det_score but large face should be penalized."""
        # det_score=0.70, bbox_area=50000 (clamped to 1.0)
        result = compute_detection_confidence(det_score=0.70, bbox_area=50000)
        # Geometric mean of 0.70 and 1.0 = sqrt(0.70) ≈ 0.837
        assert 0.80 < result < 0.90, f"Expected 0.80-0.90, got {result}"

    def test_custom_min_bbox_area(self) -> None:
        """Custom min_bbox_area should affect size confidence calculation."""
        # With min_bbox_area=5000, a 5000px face is 100% size confidence
        result = compute_detection_confidence(det_score=0.90, bbox_area=5000, min_bbox_area=5000)
        # Geometric mean of 0.90 and 1.0 = sqrt(0.90) ≈ 0.949
        assert result > 0.94, f"Expected > 0.94, got {result}"

    def test_returns_value_in_valid_range(self) -> None:
        """Confidence should always be in [0, 1]."""
        # Edge cases
        assert 0.0 <= compute_detection_confidence(0.0, 0) <= 1.0
        assert 0.0 <= compute_detection_confidence(1.0, 100000) <= 1.0
        assert 0.0 <= compute_detection_confidence(0.5, 5000) <= 1.0


class TestComputePairConfidence:
    """Tests for pair confidence calculation."""

    def test_both_high_quality_returns_high_confidence(self) -> None:
        """Two high-quality detections should yield high pair confidence."""
        result = compute_pair_confidence(
            source_det_score=0.95,
            source_bbox_area=30000,
            target_det_score=0.92,
            target_bbox_area=25000,
        )
        assert result >= 0.90, f"Expected >= 0.90, got {result}"

    def test_both_low_quality_returns_low_confidence(self) -> None:
        """Two low-quality detections should yield low pair confidence."""
        result = compute_pair_confidence(
            source_det_score=0.65,
            source_bbox_area=3000,
            target_det_score=0.60,
            target_bbox_area=2500,
        )
        assert result < 0.55, f"Expected < 0.55, got {result}"

    def test_mixed_quality_returns_medium_confidence(self) -> None:
        """One high-quality and one low-quality should yield medium confidence."""
        result = compute_pair_confidence(
            source_det_score=0.95,
            source_bbox_area=40000,
            target_det_score=0.65,
            target_bbox_area=3000,
        )
        assert 0.60 < result < 0.80, f"Expected 0.60-0.80, got {result}"

    def test_symmetric_inputs(self) -> None:
        """Swapping source and target should yield same result."""
        result1 = compute_pair_confidence(
            source_det_score=0.90,
            source_bbox_area=20000,
            target_det_score=0.75,
            target_bbox_area=8000,
        )
        result2 = compute_pair_confidence(
            source_det_score=0.75,
            source_bbox_area=8000,
            target_det_score=0.90,
            target_bbox_area=20000,
        )
        assert abs(result1 - result2) < 0.01, f"Expected symmetric, got {result1} vs {result2}"


class TestAdaptiveThreshold:
    """Tests for adaptive threshold adjustment."""

    def test_high_confidence_lowers_threshold(self) -> None:
        """High confidence should make matching easier (lower threshold)."""
        base_threshold = 0.65
        high_confidence = 0.95

        result = adaptive_threshold(
            base_threshold=base_threshold,
            confidence=high_confidence,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )

        assert result < base_threshold, f"Expected < {base_threshold}, got {result}"
        # With confidence=0.95, midpoint=0.85, max_adj=0.10:
        # adjustment = 0.10 * (0.95 - 0.85) / (1.0 - 0.85) = 0.10 * 0.10 / 0.15 ≈ 0.067
        # result = 0.65 - 0.067 ≈ 0.583
        assert 0.55 < result < 0.62, f"Expected 0.55-0.62, got {result}"

    def test_low_confidence_raises_threshold(self) -> None:
        """Low confidence should make matching harder (higher threshold)."""
        base_threshold = 0.65
        low_confidence = 0.70

        result = adaptive_threshold(
            base_threshold=base_threshold,
            confidence=low_confidence,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )

        assert result > base_threshold, f"Expected > {base_threshold}, got {result}"
        # With confidence=0.70, midpoint=0.85, max_adj=0.10:
        # adjustment = 0.10 * (0.70 - 0.85) / (1.0 - 0.85) = 0.10 * (-0.15) / 0.15 = -0.10
        # Clipped to -0.10
        # result = 0.65 - (-0.10) = 0.75
        assert 0.72 < result < 0.78, f"Expected 0.72-0.78, got {result}"

    def test_midpoint_confidence_no_change(self) -> None:
        """Confidence at midpoint should not adjust threshold."""
        base_threshold = 0.65

        result = adaptive_threshold(
            base_threshold=base_threshold,
            confidence=0.85,  # At midpoint
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )

        assert abs(result - base_threshold) < 0.01, f"Expected ~{base_threshold}, got {result}"

    def test_adjustment_clamped_to_max(self) -> None:
        """Adjustment should be clamped to max_adjustment bounds."""
        base_threshold = 0.65

        # Very high confidence - should be clamped
        result_high = adaptive_threshold(
            base_threshold=base_threshold,
            confidence=1.0,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )
        assert result_high >= base_threshold - 0.10 - 0.01  # Allow small float error

        # Very low confidence - should be clamped
        result_low = adaptive_threshold(
            base_threshold=base_threshold,
            confidence=0.50,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )
        assert result_low <= base_threshold + 0.10 + 0.01  # Allow small float error

    def test_different_base_thresholds(self) -> None:
        """Adaptive threshold should work with different base thresholds."""
        # Stricter base
        result1 = adaptive_threshold(
            base_threshold=0.75,
            confidence=0.90,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )
        assert 0.70 < result1 < 0.75

        # Looser base
        result2 = adaptive_threshold(
            base_threshold=0.55,
            confidence=0.90,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
        )
        assert 0.50 < result2 < 0.55


class TestRepresentativeMatcherConfidenceWeighting:
    """Integration tests for RepresentativeMatcher with confidence weighting."""

    @staticmethod
    def _make_mock_identity(
        det_score: float = 0.95,
        bbox_width: int = 200,
        bbox_height: int = 200,
        embedding: np.ndarray | None = None,
    ):
        """Create a mock MediaIdentity-like object for testing."""
        from unittest.mock import MagicMock

        identity = MagicMock()
        identity.id = uuid4()
        identity.confidence = det_score
        identity.bbox_width = bbox_width
        identity.bbox_height = bbox_height
        identity.embedding = embedding if embedding is not None else np.random.randn(512).astype(np.float32)
        # Normalize embedding
        identity.embedding = identity.embedding / np.linalg.norm(identity.embedding)
        return identity

    def test_compute_effective_threshold_without_settings(self) -> None:
        """Without settings, should return base threshold."""

        async def noop_assign(*args):
            pass

        async def noop_add_rep(*args):
            return None

        matcher = RepresentativeMatcher(
            threshold=0.65,
            add_representative_embedding=noop_add_rep,
            assign_to_cluster_by_id=noop_assign,
            settings=None,
        )

        identity = self._make_mock_identity(det_score=0.95)
        effective = matcher._compute_effective_threshold(identity)

        assert effective == 0.65

    def test_compute_effective_threshold_with_weighting_disabled(self) -> None:
        """With weighting disabled, should return base threshold."""

        async def noop_assign(*args):
            pass

        async def noop_add_rep(*args):
            return None

        settings = ClusteringSettings(confidence_weighting_enabled=False)
        matcher = RepresentativeMatcher(
            threshold=0.65,
            add_representative_embedding=noop_add_rep,
            assign_to_cluster_by_id=noop_assign,
            settings=settings,
        )

        identity = self._make_mock_identity(det_score=0.95)
        effective = matcher._compute_effective_threshold(identity)

        assert effective == 0.65

    def test_compute_effective_threshold_high_quality_lowers_threshold(self) -> None:
        """High-quality detection should lower the effective threshold."""

        async def noop_assign(*args):
            pass

        async def noop_add_rep(*args):
            return None

        settings = ClusteringSettings(
            confidence_weighting_enabled=True,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
            min_bbox_area=10000,
        )
        matcher = RepresentativeMatcher(
            threshold=0.65,
            add_representative_embedding=noop_add_rep,
            assign_to_cluster_by_id=noop_assign,
            settings=settings,
        )

        # High-quality: det_score=0.98, large face (200x200 = 40000 > 10000)
        identity = self._make_mock_identity(det_score=0.98, bbox_width=200, bbox_height=200)
        effective = matcher._compute_effective_threshold(identity)

        # Should be lower than base threshold
        assert effective < 0.65, f"Expected < 0.65, got {effective}"
        # But not too low (clamped by max_adjustment)
        assert effective >= 0.55, f"Expected >= 0.55, got {effective}"

    def test_compute_effective_threshold_low_quality_raises_threshold(self) -> None:
        """Low-quality detection should raise the effective threshold."""

        async def noop_assign(*args):
            pass

        async def noop_add_rep(*args):
            return None

        settings = ClusteringSettings(
            confidence_weighting_enabled=True,
            confidence_midpoint=0.85,
            threshold_max_adjustment=0.10,
            min_bbox_area=10000,
        )
        matcher = RepresentativeMatcher(
            threshold=0.65,
            add_representative_embedding=noop_add_rep,
            assign_to_cluster_by_id=noop_assign,
            settings=settings,
        )

        # Low-quality: det_score=0.70, small face (50x50 = 2500 < 10000)
        identity = self._make_mock_identity(det_score=0.70, bbox_width=50, bbox_height=50)
        effective = matcher._compute_effective_threshold(identity)

        # Should be higher than base threshold
        assert effective > 0.65, f"Expected > 0.65, got {effective}"
        # But not too high (clamped by max_adjustment)
        assert effective <= 0.75, f"Expected <= 0.75, got {effective}"
