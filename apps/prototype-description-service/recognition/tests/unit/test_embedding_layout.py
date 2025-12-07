"""Unit tests for embedding layout utilities.

These tests verify the 1024D embedding layout constants and
the decode_debug_metrics function for extracting metadata.
"""

from __future__ import annotations

import pytest

from recognition.domain.embeddings.layout import (
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    FACE_EMBEDDING_END,
    FACE_EMBEDDING_START,
    POSE_DIM,
    POSE_END,
    POSE_START,
    decode_debug_metrics,
    get_face_embedding_slice,
    get_metadata_slice,
    get_pose_slice,
)


class TestLayoutConstants:
    """Tests for embedding layout constants."""

    def test_extended_embedding_is_1024d(self) -> None:
        """Extended embedding dimension should be 1024."""
        assert EXTENDED_EMBEDDING_DIM == 1024

    def test_face_embedding_is_512d(self) -> None:
        """Face embedding should occupy first 512 dimensions."""
        assert FACE_EMBEDDING_DIM == 512
        assert FACE_EMBEDDING_START == 0
        assert FACE_EMBEDDING_END == 512

    def test_pose_is_3d(self) -> None:
        """Pose should be 3 dimensions (pitch, yaw, roll)."""
        assert POSE_DIM == 3
        assert POSE_START == 512
        assert POSE_END == 515


class TestSliceFunctions:
    """Tests for slice helper functions."""

    def test_face_embedding_slice(self) -> None:
        """Face embedding slice should cover 0:512."""
        s = get_face_embedding_slice()
        assert s.start == 0
        assert s.stop == 512

    def test_pose_slice(self) -> None:
        """Pose slice should cover 512:515."""
        s = get_pose_slice()
        assert s.start == 512
        assert s.stop == 515

    def test_metadata_slice(self) -> None:
        """Metadata slice should cover 512:1024."""
        s = get_metadata_slice()
        assert s.start == 512
        assert s.stop == 1024


class TestDecodeDebugMetrics:
    """Tests for decode_debug_metrics function."""

    def test_returns_none_for_short_embedding(self) -> None:
        """Should return None for embeddings shorter than 1024D."""
        short_embedding = [0.0] * 512

        result = decode_debug_metrics(short_embedding)

        assert result is None

    def test_decodes_pose_angles(self) -> None:
        """Should denormalize pose angles from normalized values."""
        embedding = [0.0] * 1024
        # Set normalized pose values (pitch=0.5, yaw=-0.333, roll=0.1)
        embedding[512] = 0.5  # pitch: 45 degrees
        embedding[513] = -1 / 3  # yaw: -30 degrees
        embedding[514] = 0.1  # roll: 9 degrees

        result = decode_debug_metrics(embedding)

        assert result is not None
        assert result["pose"]["pitch"] == pytest.approx(45.0, abs=0.1)
        assert result["pose"]["yaw"] == pytest.approx(-30.0, abs=0.1)
        assert result["pose"]["roll"] == pytest.approx(9.0, abs=0.1)

    def test_decodes_age(self) -> None:
        """Should denormalize age from normalized value."""
        embedding = [0.0] * 1024
        embedding[515] = 0.35  # age: 35

        result = decode_debug_metrics(embedding)

        assert result is not None
        assert result["age"] == pytest.approx(35.0, abs=0.1)

    def test_decodes_gender(self) -> None:
        """Should decode gender as 'female' (<0.5) or 'male' (>=0.5)."""
        embedding_female = [0.0] * 1024
        embedding_female[516] = 0.0

        embedding_male = [0.0] * 1024
        embedding_male[516] = 1.0

        result_female = decode_debug_metrics(embedding_female)
        result_male = decode_debug_metrics(embedding_male)

        assert result_female is not None
        assert result_female["gender"] == "female"
        assert result_male is not None
        assert result_male["gender"] == "male"

    def test_decodes_det_score(self) -> None:
        """Should return detection score unchanged."""
        embedding = [0.0] * 1024
        embedding[517] = 0.95

        result = decode_debug_metrics(embedding)

        assert result is not None
        assert result["det_score"] == pytest.approx(0.95, abs=0.001)

    def test_decodes_bbox_area(self) -> None:
        """Should denormalize bbox area."""
        embedding = [0.0] * 1024
        embedding[518] = 0.2  # 0.2 * 50000 = 10000 pixels²

        result = decode_debug_metrics(embedding)

        assert result is not None
        assert result["bbox_area"] == 10000

    def test_decodes_landmark_quality(self) -> None:
        """Should denormalize landmark quality."""
        embedding = [0.0] * 1024
        embedding[519] = 0.15  # 0.15 * 100 = 15

        result = decode_debug_metrics(embedding)

        assert result is not None
        assert result["landmark_quality"] == pytest.approx(15.0, abs=0.01)

    def test_full_decode_round_trip(self) -> None:
        """Encode then decode should recover original values."""
        # This test uses the builder to create an embedding, then decodes it
        import numpy as np

        from recognition.domain.embeddings.builder import build_extended_embedding

        face_emb = np.random.randn(512).astype(np.float32)
        original_det_score = 0.92
        original_bbox = (100, 100, 300, 350)  # area = 50000
        original_pose = (20.0, -10.0, 5.0)
        original_age = 42

        extended = build_extended_embedding(
            face_embedding=face_emb,
            det_score=original_det_score,
            bbox=original_bbox,
            pose=original_pose,
            age=original_age,
            gender=1,
        )

        decoded = decode_debug_metrics(extended.tolist())

        assert decoded is not None
        assert decoded["det_score"] == pytest.approx(original_det_score, abs=0.01)
        assert decoded["pose"]["pitch"] == pytest.approx(original_pose[0], abs=0.5)
        assert decoded["pose"]["yaw"] == pytest.approx(original_pose[1], abs=0.5)
        assert decoded["pose"]["roll"] == pytest.approx(original_pose[2], abs=0.5)
        assert decoded["age"] == pytest.approx(original_age, abs=0.5)
        assert decoded["gender"] == "male"
        # bbox area = 200 * 250 = 50000, clamped to 1.0 in normalized form
        assert decoded["bbox_area"] == 50000
