"""Unit tests for extended embedding builder functions.

These tests verify the 1024D embedding construction that combines
512D face identity vectors with metadata (pose, age, gender, etc.).
"""

from __future__ import annotations

import numpy as np
import pytest

from recognition.domain.embeddings.builder import (
    build_extended_embedding,
    extract_face_embedding,
    prepare_embedding,
)
from recognition.domain.embeddings.layout import (
    AGE_IDX,
    AGE_SCALE,
    BBOX_AREA_IDX,
    BBOX_AREA_SCALE,
    DET_SCORE_IDX,
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    LANDMARK_STD_SCALE,
    POSE_SCALE,
    POSE_START,
)


class TestBuildExtendedEmbedding:
    """Tests for build_extended_embedding function."""

    def test_output_is_1024d_float32(self) -> None:
        """Extended embedding should be exactly 1024D float32."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 200, 250),
        )

        assert result.shape == (EXTENDED_EMBEDDING_DIM,)
        assert result.dtype == np.float32

    def test_face_embedding_is_normalized(self) -> None:
        """The 512D face portion should be L2 normalized."""
        # Create a non-normalized face embedding
        face_emb = np.ones(512, dtype=np.float32) * 10.0

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
        )

        # Extract face portion and check norm
        face_portion = result[:512]
        norm = np.linalg.norm(face_portion)
        assert np.isclose(norm, 1.0, atol=1e-5)

    def test_det_score_stored_correctly(self) -> None:
        """Detection score should be stored at DET_SCORE_IDX."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.87,
            bbox=(0, 0, 50, 50),
        )

        assert np.isclose(result[DET_SCORE_IDX], 0.87, atol=1e-5)

    def test_pose_normalized_by_90_degrees(self) -> None:
        """Pose angles should be normalized by dividing by 90."""
        face_emb = np.random.randn(512).astype(np.float32)
        pitch, yaw, roll = 45.0, -30.0, 15.0

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
            pose=(pitch, yaw, roll),
        )

        assert np.isclose(result[POSE_START], pitch / POSE_SCALE, atol=1e-5)
        assert np.isclose(result[POSE_START + 1], yaw / POSE_SCALE, atol=1e-5)
        assert np.isclose(result[POSE_START + 2], roll / POSE_SCALE, atol=1e-5)

    def test_age_normalized_by_100(self) -> None:
        """Age should be normalized by dividing by 100."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
            age=35,
        )

        assert np.isclose(result[AGE_IDX], 35 / AGE_SCALE, atol=1e-5)

    def test_gender_stored_as_float(self) -> None:
        """Gender (0=female, 1=male) should be stored directly."""
        face_emb = np.random.randn(512).astype(np.float32)

        result_female = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
            gender=0,
        )
        result_male = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
            gender=1,
        )

        assert result_female[GENDER_IDX] == 0.0
        assert result_male[GENDER_IDX] == 1.0

    def test_bbox_area_normalized_and_clamped(self) -> None:
        """Bbox area should be normalized by BBOX_AREA_SCALE and clamped to 1.0."""
        face_emb = np.random.randn(512).astype(np.float32)

        # Small bbox
        result_small = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),  # area = 10000
        )
        assert np.isclose(result_small[BBOX_AREA_IDX], 10000 / BBOX_AREA_SCALE, atol=1e-5)

        # Large bbox (should clamp to 1.0)
        result_large = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 500, 500),  # area = 250000 > 50000
        )
        assert result_large[BBOX_AREA_IDX] == 1.0

    def test_landmark_quality_computed(self) -> None:
        """Landmark quality should be std of landmarks normalized by 100."""
        face_emb = np.random.randn(512).astype(np.float32)
        landmarks = np.array([[10.0, 20.0], [15.0, 25.0], [12.0, 22.0]])
        expected_std = float(np.std(landmarks.flatten()))

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
            landmarks=landmarks,
        )

        assert np.isclose(
            result[LANDMARK_QUALITY_IDX],
            expected_std / LANDMARK_STD_SCALE,
            atol=1e-5,
        )

    def test_optional_fields_default_to_zero(self) -> None:
        """Optional fields (pose, age, gender, landmarks) should be zero when not provided."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.9,
            bbox=(0, 0, 100, 100),
        )

        # Pose
        assert result[POSE_START] == 0.0
        assert result[POSE_START + 1] == 0.0
        assert result[POSE_START + 2] == 0.0
        # Age, gender
        assert result[AGE_IDX] == 0.0
        assert result[GENDER_IDX] == 0.0
        # Landmark quality
        assert result[LANDMARK_QUALITY_IDX] == 0.0


class TestExtractFaceEmbedding:
    """Tests for extract_face_embedding function."""

    def test_extracts_first_512_dimensions(self) -> None:
        """Should extract exactly the first 512 dimensions."""
        extended = np.arange(1024, dtype=np.float32)

        face = extract_face_embedding(extended)

        assert face.shape == (FACE_EMBEDDING_DIM,)
        np.testing.assert_array_equal(face, extended[:512])

    def test_returns_copy_not_view(self) -> None:
        """Extracted embedding should be a copy, not a view."""
        extended = np.ones(1024, dtype=np.float32)

        face = extract_face_embedding(extended)
        face[0] = 999.0

        # Original should be unchanged
        assert extended[0] == 1.0


class TestPrepareEmbedding:
    """Tests for prepare_embedding function."""

    def test_converts_list_to_numpy(self) -> None:
        """Should convert Python list to numpy array."""
        embedding_list = [1.0] * 1024

        result = prepare_embedding(embedding_list)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32

    def test_normalizes_by_default(self) -> None:
        """Should L2 normalize by default."""
        embedding = [1.0] * 1024

        result = prepare_embedding(embedding, normalize=True)

        norm = np.linalg.norm(result)
        assert np.isclose(norm, 1.0, atol=1e-5)

    def test_skip_normalization_when_disabled(self) -> None:
        """Should skip normalization when normalize=False."""
        embedding = [2.0] * 1024

        result = prepare_embedding(embedding, normalize=False)

        # Should preserve original values
        assert np.allclose(result, 2.0)

    def test_handles_numpy_input(self) -> None:
        """Should handle numpy array input."""
        embedding = np.random.randn(1024)

        result = prepare_embedding(embedding)

        assert result.dtype == np.float32
        norm = np.linalg.norm(result)
        assert np.isclose(norm, 1.0, atol=1e-5)

    def test_handles_zero_vector_gracefully(self) -> None:
        """Should handle zero vector without division by zero."""
        embedding = [0.0] * 1024

        result = prepare_embedding(embedding, normalize=True)

        # Should return the zero vector unchanged
        assert np.allclose(result, 0.0)
