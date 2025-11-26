"""Tests for extended embedding builder utilities."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.domain.embeddings import (
    build_extended_embedding,
    extract_face_embedding,
    prepare_embedding,
)
from recognition.domain.embeddings.layout import (
    AGE_IDX,
    BBOX_AREA_IDX,
    DET_SCORE_IDX,
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    POSE_START,
)


class TestBuildExtendedEmbedding:
    """Tests for build_extended_embedding function."""

    def test_returns_correct_dimension(self) -> None:
        """Extended embedding should be 1024D."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
        )

        assert result.shape == (EXTENDED_EMBEDDING_DIM,)

    def test_face_embedding_normalized(self) -> None:
        """Face embedding slice should be L2 normalized."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
        )

        face_slice = result[:FACE_EMBEDDING_DIM]
        norm = np.linalg.norm(face_slice)
        assert norm == pytest.approx(1.0, abs=1e-5)

    def test_pose_normalized_to_minus_one_to_one(self) -> None:
        """Pose values should be normalized by dividing by 90."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            pose=(45.0, -30.0, 10.0),  # pitch, yaw, roll
        )

        assert result[POSE_START] == pytest.approx(45.0 / 90.0)
        assert result[POSE_START + 1] == pytest.approx(-30.0 / 90.0)
        assert result[POSE_START + 2] == pytest.approx(10.0 / 90.0)

    def test_age_normalized(self) -> None:
        """Age should be normalized by dividing by 100."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            age=35,
        )

        assert result[AGE_IDX] == pytest.approx(0.35)

    def test_gender_stored_as_float(self) -> None:
        """Gender should be stored as 0.0 or 1.0."""
        face_emb = np.random.randn(512).astype(np.float32)

        result_male = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            gender=1,
        )

        result_female = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            gender=0,
        )

        assert result_male[GENDER_IDX] == 1.0
        assert result_female[GENDER_IDX] == 0.0

    def test_det_score_stored_directly(self) -> None:
        """Detection score should be stored as-is."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.87,
            bbox=(100, 100, 300, 400),
        )

        assert result[DET_SCORE_IDX] == pytest.approx(0.87)

    def test_bbox_area_normalized(self) -> None:
        """Bbox area should be normalized by 50000 and clamped to 1.0."""
        face_emb = np.random.randn(512).astype(np.float32)

        # Small bbox: 200x300 = 60000 pixels -> 60000/50000 = 1.2 -> clamped to 1.0
        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),  # 200x300 = 60000
        )

        assert result[BBOX_AREA_IDX] == pytest.approx(1.0)

        # Very small bbox: 50x50 = 2500 -> 2500/50000 = 0.05
        result_small = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 150, 150),  # 50x50 = 2500
        )

        assert result_small[BBOX_AREA_IDX] == pytest.approx(0.05)

    def test_landmark_quality_normalized(self) -> None:
        """Landmark std should be normalized by 100."""
        face_emb = np.random.randn(512).astype(np.float32)
        landmarks = np.array([[50, 50], [100, 60], [75, 100], [60, 120], [90, 120]])

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            landmarks=landmarks,
        )

        expected_std = np.std(landmarks.flatten()) / 100.0
        assert result[LANDMARK_QUALITY_IDX] == pytest.approx(expected_std)

    def test_none_values_leave_zeros(self) -> None:
        """Optional fields left as None should remain zero."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            pose=None,
            age=None,
            gender=None,
            landmarks=None,
        )

        # Pose should be zero
        assert result[POSE_START] == 0.0
        assert result[POSE_START + 1] == 0.0
        assert result[POSE_START + 2] == 0.0

        # Age should be zero
        assert result[AGE_IDX] == 0.0

        # Gender should be zero
        assert result[GENDER_IDX] == 0.0

        # Landmark quality should be zero
        assert result[LANDMARK_QUALITY_IDX] == 0.0

    def test_reserved_bytes_are_zero(self) -> None:
        """Reserved bytes (616-1023) should all be zero."""
        face_emb = np.random.randn(512).astype(np.float32)

        result = build_extended_embedding(
            face_embedding=face_emb,
            det_score=0.95,
            bbox=(100, 100, 300, 400),
            pose=(45.0, -30.0, 10.0),
            age=35,
            gender=1,
        )

        # Check reserved region
        reserved = result[616:1024]
        assert np.allclose(reserved, 0.0)


class TestExtractFaceEmbedding:
    """Tests for extract_face_embedding function."""

    def test_extracts_first_512_dimensions(self) -> None:
        """Should extract first 512 dimensions from 1024D embedding."""
        emb_1024 = np.random.randn(1024).astype(np.float32)

        result = extract_face_embedding(emb_1024)

        assert result.shape == (512,)
        assert np.allclose(result, emb_1024[:512])


class TestPrepareEmbedding:
    """Tests for prepare_embedding utility function."""

    def test_converts_list_to_numpy(self) -> None:
        """Should convert Python list to numpy array."""
        emb_list = [0.1] * 1024

        result = prepare_embedding(emb_list)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float32

    def test_keeps_1024d_shape(self) -> None:
        """1024D input should remain 1024D."""
        emb_1024 = np.random.randn(1024).astype(np.float32)

        result = prepare_embedding(emb_1024)

        assert result.shape == (1024,)

    def test_normalizes_by_default(self) -> None:
        """Should L2 normalize the embedding by default."""
        emb = np.array([1.0] * 1024, dtype=np.float32)

        result = prepare_embedding(emb)

        norm = np.linalg.norm(result)
        assert norm == pytest.approx(1.0, abs=1e-5)

    def test_skip_normalize_when_false(self) -> None:
        """Should not normalize when normalize=False."""
        emb = np.array([2.0] * 1024, dtype=np.float32)

        result = prepare_embedding(emb, normalize=False)

        # Should match input (not normalized)
        assert np.allclose(result, emb)

    def test_handles_database_format(self) -> None:
        """Should handle list format from database."""
        # Simulate database storage format
        db_embedding = [float(x) for x in np.random.randn(1024)]

        result = prepare_embedding(db_embedding)

        assert result.shape == (1024,)
        assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-5)
