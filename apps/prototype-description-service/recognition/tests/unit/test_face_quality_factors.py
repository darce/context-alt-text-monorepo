"""FIR-6 S1: quality factors, embed pre-norm capture, OACT dark scaffold, knobs."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.confidence import ConfidenceCheck
from recognition.application.assignment.quality import (
    compute_identity_quality,
    compute_quality_adjustment,
)
from recognition.application.settings import ClusteringSettings, QualitySettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.maturity import ClusterMaturityInfo, ClusterMaturityLevel
from recognition.infrastructure.embeddings.face_quality_factors import (
    compute_face_quality_factors,
    compute_occlusion_severity,
    compute_sharpness,
    passes_factor_floors,
)
from recognition.infrastructure.face_pipeline._common import (
    SFACE_CROP_SIZE,
    SFACE_EMBEDDING_DIM,
    EmbedBatchResult,
    embed_batch,
)
from recognition.shared.ids import generate_id


def _crop_pattern(*, scale: float = 1.0, blur_box: int = 1) -> np.ndarray:
    """Synthetic 112×112 BGR with controllable high-frequency energy."""
    yy, xx = np.mgrid[0:SFACE_CROP_SIZE, 0:SFACE_CROP_SIZE]
    base = ((xx + yy) % 17) * scale
    img = np.stack([base, base * 0.8, base * 0.6], axis=-1)
    if blur_box > 1:
        # Box blur by local mean (reduce high-frequency energy / sharpness).
        k = blur_box
        pad = k // 2
        padded = np.pad(img, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        acc = np.zeros_like(img, dtype=np.float64)
        for dy in range(k):
            for dx in range(k):
                acc += padded[dy : dy + SFACE_CROP_SIZE, dx : dx + SFACE_CROP_SIZE]
        img = acc / (k * k)
    return np.clip(img, 0, 255).astype(np.uint8)


def _frontal_landmarks() -> np.ndarray:
    return np.array(
        [
            [38.3, 51.7],
            [73.5, 51.5],
            [56.0, 71.7],
            [41.5, 92.4],
            [70.7, 92.2],
        ],
        dtype=np.float64,
    )


class TestFactorDiscrimination:
    def test_blurred_less_sharp_than_sharp(self) -> None:
        sharp = compute_sharpness(_crop_pattern(scale=12.0, blur_box=1))
        blurred = compute_sharpness(_crop_pattern(scale=12.0, blur_box=9))
        assert blurred < sharp

    def test_occluded_eye_patch_higher_severity(self) -> None:
        clean = _crop_pattern(scale=10.0)
        occluded = clean.copy()
        # Paint both eye regions black (low variance / edge energy).
        occluded[40:65, 25:50] = 0
        occluded[40:65, 60:85] = 0
        assert compute_occlusion_severity(occluded) > compute_occlusion_severity(clean)

    def test_factors_bundle_includes_norm_and_pose(self) -> None:
        crop = _crop_pattern(scale=8.0)
        factors = compute_face_quality_factors(
            crop_bgr=crop,
            embedding_norm=3.5,
            landmarks=_frontal_landmarks(),
        )
        assert factors.embedding_norm == pytest.approx(3.5)
        assert factors.sharpness > 0.0
        assert 0.0 <= factors.occlusion_severity <= 1.0
        assert factors.pose_yaw is not None
        assert factors.pose_roll is not None


class TestEmbedNormCapture:
    def test_norms_vary_and_post_norm_reconstruction_fails(self) -> None:
        crop = np.full((SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3), 40, dtype=np.uint8)

        def _feature_a(_c: np.ndarray) -> np.ndarray:
            return np.arange(SFACE_EMBEDDING_DIM, dtype=np.float32) + 1.0

        def _feature_b(_c: np.ndarray) -> np.ndarray:
            return (np.arange(SFACE_EMBEDDING_DIM, dtype=np.float32) + 1.0) * 4.0

        a = embed_batch([crop], feature_fn=_feature_a, embedding_dim=SFACE_EMBEDDING_DIM)
        b = embed_batch([crop], feature_fn=_feature_b, embedding_dim=SFACE_EMBEDDING_DIM)
        assert isinstance(a, EmbedBatchResult)
        assert float(a.norms[0]) != pytest.approx(float(b.norms[0]), rel=0.1)
        # Unit vectors are similar directionally; reconstructed post-norm norms are ~1.
        post_norm_a = float(np.linalg.norm(a.vectors[0]))
        post_norm_b = float(np.linalg.norm(b.vectors[0]))
        assert post_norm_a == pytest.approx(1.0, abs=1e-5)
        assert post_norm_b == pytest.approx(1.0, abs=1e-5)
        # Captured pre-norm magnitudes must not collapse to the unit post-norm.
        assert float(a.norms[0]) != pytest.approx(1.0, abs=0.05)
        assert float(b.norms[0]) != pytest.approx(1.0, abs=0.05)
        # Mutation guard: post-norm "norms" lose the pre-norm discrimination that
        # EmbedBatchResult.norms must preserve (EMB-03 / FIR6S1-M-07).
        assert float(a.norms[0]) != pytest.approx(post_norm_a, abs=0.05)
        assert float(b.norms[0]) != pytest.approx(post_norm_b, abs=0.05)
        assert abs(float(a.norms[0]) - float(b.norms[0])) > abs(post_norm_a - post_norm_b)


class TestOactDarkScaffold:
    def test_zero_coefficient_bitwise_parity(self) -> None:
        base = compute_identity_quality(
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
            occlusion_severity=0.8,
            settings=QualitySettings(oact_coefficient=0.0),
        )
        none_sev = compute_identity_quality(
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
            occlusion_severity=None,
            settings=QualitySettings(oact_coefficient=0.0),
        )
        assert base.threshold_adjustment == none_sev.threshold_adjustment
        assert base.score == none_sev.score

    def test_nonzero_coefficient_moves_adjustment(self) -> None:
        off = compute_quality_adjustment(
            0.85,
            settings=QualitySettings(oact_coefficient=0.0),
            occlusion_severity=0.5,
        )
        on = compute_quality_adjustment(
            0.85,
            settings=QualitySettings(oact_coefficient=0.2),
            occlusion_severity=0.5,
        )
        assert on == pytest.approx(off + 0.1)
        assert on > off

    @pytest.mark.asyncio
    async def test_oact_moves_gate_time_threshold_adjustment(self) -> None:
        """Discrimination must go through confidence.py, not quality.py alone."""
        settings_off = ClusteringSettings(
            similarity_threshold=0.75,
            suggestion_floor=0.65,
            suggestion_ceiling=0.75,
            quality=QualitySettings(oact_coefficient=0.0),
        )
        settings_on = ClusteringSettings(
            similarity_threshold=0.75,
            suggestion_floor=0.65,
            suggestion_ceiling=0.75,
            quality=QualitySettings(oact_coefficient=0.4),
        )
        repo = Mock()
        repo.get_maturity_info = AsyncMock(
            return_value=ClusterMaturityInfo(
                level=ClusterMaturityLevel.MATURE,
                identity_count=10,
                representative_count=5,
                user_confirmed=False,
                threshold_adjustment=0.0,
            )
        )
        repo.get_curriculum_t = AsyncMock(return_value=0.0)

        identity = MediaIdentity(
            id=str(generate_id()),
            tenant_id=str(generate_id()),
            media_id=str(generate_id()),
            embedding=np.zeros(128, dtype=np.float32),
            confidence=0.9,
            bbox_width=100,
            bbox_height=100,
            # Frontal pose so pose-safety does not alter the OACT adjustment.
            pose_pitch=0.0,
            pose_yaw=0.0,
            pose_roll=0.0,
            occlusion_severity=0.5,
        )
        candidate = AssignmentCandidate(
            identity=identity,
            identity_vector=np.zeros(128, dtype=np.float32),
            cluster_id="cluster-1",
            discovery_method=DiscoveryMethod.REPRESENTATIVE,
            discovery_similarity=0.70,
        )

        off = await ConfidenceCheck(settings_off, repo).evaluate(candidate)
        on = await ConfidenceCheck(settings_on, repo).evaluate(candidate)
        assert on.metadata["quality_adj"] > off.metadata["quality_adj"]
        assert on.metadata["final_threshold"] > off.metadata["final_threshold"]


class TestNoopFloors:
    def test_noop_floors_exclude_nothing(self) -> None:
        assert passes_factor_floors(
            sharpness=0.0,
            embedding_norm=0.0,
            occlusion_severity=1.0,
            floor_sharpness=0.0,
            floor_embedding_norm=0.0,
            ceiling_occlusion=1.0,
        )
        assert passes_factor_floors(
            sharpness=None,
            embedding_norm=None,
            occlusion_severity=None,
        )

    def test_floor_rejects_below_sharpness(self) -> None:
        assert not passes_factor_floors(
            sharpness=5.0,
            embedding_norm=10.0,
            occlusion_severity=0.1,
            floor_sharpness=10.0,
            floor_embedding_norm=0.0,
            ceiling_occlusion=1.0,
        )

    def test_floor_rejects_below_embedding_norm(self) -> None:
        assert not passes_factor_floors(
            sharpness=50.0,
            embedding_norm=1.0,
            occlusion_severity=0.1,
            floor_sharpness=0.0,
            floor_embedding_norm=3.0,
            ceiling_occlusion=1.0,
        )

    def test_ceiling_rejects_high_occlusion(self) -> None:
        assert not passes_factor_floors(
            sharpness=50.0,
            embedding_norm=10.0,
            occlusion_severity=0.9,
            floor_sharpness=0.0,
            floor_embedding_norm=0.0,
            ceiling_occlusion=0.5,
        )

    def test_active_floors_accept_passing_observation(self) -> None:
        assert passes_factor_floors(
            sharpness=50.0,
            embedding_norm=10.0,
            occlusion_severity=0.2,
            floor_sharpness=10.0,
            floor_embedding_norm=3.0,
            ceiling_occlusion=0.5,
        )


class TestOactDefaultPin:
    def test_quality_settings_oact_default_is_zero(self) -> None:
        """Dark-by-default pin: flipping the default to non-zero must fail this test."""
        assert QualitySettings().oact_coefficient == 0.0
        assert QualitySettings.model_fields["oact_coefficient"].default == 0.0

    def test_quality_settings_oact_coefficient_rejects_negative(self) -> None:
        """FIR6RC-01: QualitySettings.oact_coefficient is ge=0 (negative rewards occlusion)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            QualitySettings(oact_coefficient=-0.1)
        with pytest.raises(ValidationError):
            QualitySettings(oact_coefficient=-1e-9)
        assert QualitySettings(oact_coefficient=0.0).oact_coefficient == 0.0
        assert QualitySettings(oact_coefficient=0.5).oact_coefficient == 0.5


class TestInsightfaceFactorsNone:
    def test_face_detection_defaults_none(self) -> None:
        from recognition.application.embedding.detector import FaceDetection

        det = FaceDetection(
            media_id="m",
            bbox=(0, 0, 10, 10),
            confidence=0.9,
        )
        assert det.sharpness is None
        assert det.embedding_norm is None
        assert det.occlusion_severity is None

    def test_domain_identity_defaults_none(self) -> None:
        ident = MediaIdentity(
            id="i",
            tenant_id="t",
            media_id="m",
            embedding=np.zeros(4, dtype=np.float32),
            confidence=0.9,
            bbox_width=10,
            bbox_height=10,
        )
        assert ident.sharpness is None
        assert ident.embedding_norm is None
        assert ident.occlusion_severity is None
