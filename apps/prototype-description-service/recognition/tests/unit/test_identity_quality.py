"""Tests for identity quality score computation."""

import pytest

from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_quality_adjustment,
)
from recognition.application.embedding.detector import _compute_detection_quality
from recognition.application.settings import QualitySettings
from recognition.domain.maturity import ClusterMaturityLevel


def test_compute_detection_quality_uses_corner_bbox_not_edge_as_size() -> None:
    """GROKHARM-02 [SERVE-08, PROV-06]: corner (x1,y1,x2,y2) must not treat x2/y2 as w/h.

    An 80px face at (500,400,580,480) must score like width=80 height=80, not like
    absolute edges 580/480. A 40px face far from the origin must not be size-boosted
    to size_factor=1.0 (min_face_size default 80).
    """
    conf = 0.9
    # Finding anchor: 80×80 at far origin offset.
    corner_80 = (500, 400, 580, 480)
    score_80 = _compute_detection_quality(
        confidence=conf,
        bbox=corner_80,
    )
    expected_80 = compute_identity_quality(
        confidence=conf,
        bbox_width=80,
        bbox_height=80,
    ).score
    wrong_edge_80 = compute_identity_quality(
        confidence=conf,
        bbox_width=580,
        bbox_height=480,
    ).score
    assert score_80 == expected_80
    # Note: at min_face_size=80, wrong edges (580/480) also size-saturate → same score.
    # Discriminating case is a sub-min face far from origin (fail-first under the bug).
    _ = wrong_edge_80

    corner_40 = (500, 400, 540, 440)  # 40×40 far from origin
    score_40 = _compute_detection_quality(
        confidence=conf,
        bbox=corner_40,
    )
    expected_40 = compute_identity_quality(
        confidence=conf,
        bbox_width=40,
        bbox_height=40,
    ).score
    wrong_edge_40 = compute_identity_quality(
        confidence=conf,
        bbox_width=540,
        bbox_height=440,
    ).score
    assert score_40 == expected_40
    assert score_40 < wrong_edge_40  # fail-first under edge-as-width bug


class TestComputeIdentityQuality:
    def test_high_confidence_frontal_large_face(self) -> None:
        info = compute_identity_quality(
            confidence=0.95,
            bbox_width=200,
            bbox_height=200,
        )
        assert info.score >= 0.9
        assert info.threshold_adjustment <= 0.0  # Lenient

    def test_low_confidence_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.5,
            bbox_width=100,
            bbox_height=100,
        )
        assert info.score < 0.6
        assert info.threshold_adjustment > 0.0  # Stricter

    def test_extreme_pose_not_penalized(self) -> None:
        """FIR2-BR-03: canonical quality is pose-neutral (no extreme-pose penalty).

        Pose remains optional for diversity/buckets; threshold quality uses
        confidence + bbox only so models without pose are not disadvantaged.
        """
        extreme = compute_identity_quality(
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
        )
        frontal = compute_identity_quality(
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
        )
        missing = compute_identity_quality(
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
        )
        assert extreme.score == frontal.score == missing.score
        assert extreme.score == pytest.approx(0.9, abs=0.001)

    def test_small_face_penalized(self) -> None:
        info = compute_identity_quality(
            confidence=0.9,
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

    def test_positive_oact_coefficient_tightens_with_occlusion(self) -> None:
        settings = QualitySettings(oact_coefficient=0.2)
        without_occlusion = compute_quality_adjustment(
            0.85,
            settings=settings,
            occlusion_severity=0.0,
        )
        with_occlusion = compute_quality_adjustment(
            0.85,
            settings=settings,
            occlusion_severity=0.5,
        )

        assert with_occlusion > without_occlusion
