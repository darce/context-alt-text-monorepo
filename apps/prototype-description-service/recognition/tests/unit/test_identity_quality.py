"""Tests for identity quality score computation."""

import pytest

from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_quality_adjustment,
)
from recognition.domain.maturity import ClusterMaturityLevel


class TestComputeIdentityQuality:
    def test_high_confidence_frontal_large_face(self) -> None:
        info = compute_identity_quality(
            confidence=0.95,
            pose_pitch=0.0,
            pose_yaw=0.0,
            pose_roll=0.0,
            bbox_width=200,
            bbox_height=200,
        )
        assert info.score >= 0.9
        assert info.threshold_adjustment <= 0.0  # Lenient

    def test_low_confidence_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.5,
            pose_pitch=0.0,
            pose_yaw=0.0,
            pose_roll=0.0,
            bbox_width=100,
            bbox_height=100,
        )
        assert info.score < 0.6
        assert info.threshold_adjustment > 0.0  # Stricter

    def test_extreme_pose_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.9,
            pose_pitch=45.0,
            pose_yaw=0.0,
            pose_roll=0.0,
            bbox_width=100,
            bbox_height=100,
        )
        assert info.pose_penalty < 1.0
        assert info.score < 0.9

    def test_small_face_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.9,
            pose_pitch=0.0,
            pose_yaw=0.0,
            pose_roll=0.0,
            bbox_width=32,
            bbox_height=32,
        )
        assert info.size_factor < 0.5


class TestComputeQualityAdjustment:
    @pytest.mark.parametrize(
        "quality,expected_sign",
        [
            (0.3, 1),  # Positive (stricter)
            (0.6, 1),  # Positive (stricter)
            (0.85, 0),  # Zero (neutral)
            (0.98, -1),  # Negative (lenient)
        ],
    )
    def test_adjustment_direction(self, quality: float, expected_sign: int) -> None:
        adjustment = compute_quality_adjustment(quality)
        if expected_sign == 1:
            assert adjustment > 0
        elif expected_sign == -1:
            assert adjustment < 0
        else:
            assert adjustment == pytest.approx(0.0, abs=0.001)

    def test_adjustment_dampened_for_cold_clusters(self) -> None:
        adjustment = compute_quality_adjustment(0.3, maturity=ClusterMaturityLevel.COLD)
        assert adjustment == pytest.approx(0.0125, abs=0.0001)
