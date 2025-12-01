"""Tests for suggestion metadata extraction utility."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.suggestion_metadata import (
    SuggestionMetadata,
    _classify_face_size,
    _classify_landmark_quality,
    extract_metadata_for_comparison,
    extract_suggestion_metadata,
)
from recognition.domain.embeddings.layout import (
    AGE_IDX,
    AGE_SCALE,
    BBOX_AREA_IDX,
    BBOX_AREA_SCALE,
    DET_SCORE_IDX,
    EXTENDED_EMBEDDING_DIM,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    LANDMARK_STD_SCALE,
    POSE_SCALE,
    POSE_START,
)


def _create_test_embedding(
    pose_pitch: float = 0.0,
    pose_yaw: float = 0.0,
    pose_roll: float = 0.0,
    age: int | None = 30,
    gender: str | None = "male",
    det_score: float = 0.95,
    bbox_area: float = 15000.0,
    landmark_std: float = 35.0,
) -> np.ndarray:
    """Create a test embedding with specified metadata values."""
    embedding = np.zeros(EXTENDED_EMBEDDING_DIM, dtype=np.float32)

    # Set pose (normalized by POSE_SCALE)
    embedding[POSE_START] = pose_pitch / POSE_SCALE
    embedding[POSE_START + 1] = pose_yaw / POSE_SCALE
    embedding[POSE_START + 2] = pose_roll / POSE_SCALE

    # Set age (normalized by AGE_SCALE)
    if age is not None:
        embedding[AGE_IDX] = age / AGE_SCALE

    # Set gender (0=female, 1=male)
    if gender == "female":
        embedding[GENDER_IDX] = 0
    elif gender == "male":
        embedding[GENDER_IDX] = 1
    else:
        embedding[GENDER_IDX] = -1  # Unknown

    # Set detection score (already [0, 1])
    embedding[DET_SCORE_IDX] = det_score

    # Set bbox area (normalized by BBOX_AREA_SCALE)
    embedding[BBOX_AREA_IDX] = bbox_area / BBOX_AREA_SCALE

    # Set landmark std (normalized by LANDMARK_STD_SCALE)
    embedding[LANDMARK_QUALITY_IDX] = landmark_std / LANDMARK_STD_SCALE

    return embedding


class TestExtractSuggestionMetadata:
    """Tests for extract_suggestion_metadata function."""

    def test_extracts_pose_correctly(self) -> None:
        """Test that pose values are decoded correctly."""
        embedding = _create_test_embedding(pose_pitch=15.0, pose_yaw=-30.0, pose_roll=5.0)
        metadata = extract_suggestion_metadata(embedding)

        assert pytest.approx(metadata.pose_pitch, abs=0.1) == 15.0
        assert pytest.approx(metadata.pose_yaw, abs=0.1) == -30.0
        assert pytest.approx(metadata.pose_roll, abs=0.1) == 5.0

    def test_extracts_age_correctly(self) -> None:
        """Test that age is decoded correctly."""
        embedding = _create_test_embedding(age=45)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.age == 45

    def test_age_none_when_zero(self) -> None:
        """Test that age is None when not available."""
        embedding = _create_test_embedding(age=None)
        embedding[AGE_IDX] = 0  # Explicitly set to zero
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.age is None

    def test_extracts_gender_female(self) -> None:
        """Test gender decoding for female."""
        embedding = _create_test_embedding(gender="female")
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.gender == "female"

    def test_extracts_gender_male(self) -> None:
        """Test gender decoding for male."""
        embedding = _create_test_embedding(gender="male")
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.gender == "male"

    def test_gender_none_when_unknown(self) -> None:
        """Test gender is None when not available."""
        embedding = _create_test_embedding(gender=None)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.gender is None

    def test_extracts_detection_score(self) -> None:
        """Test detection score extraction."""
        embedding = _create_test_embedding(det_score=0.87)
        metadata = extract_suggestion_metadata(embedding)

        assert pytest.approx(metadata.detection_score, abs=0.01) == 0.87

    def test_extracts_bbox_area(self) -> None:
        """Test bbox area extraction and classification."""
        embedding = _create_test_embedding(bbox_area=25000.0)
        metadata = extract_suggestion_metadata(embedding)

        assert pytest.approx(metadata.bbox_area, abs=100) == 25000.0
        assert metadata.face_size_quality == "large"

    def test_extracts_landmark_std(self) -> None:
        """Test landmark std extraction and classification."""
        embedding = _create_test_embedding(landmark_std=45.0)
        metadata = extract_suggestion_metadata(embedding)

        assert pytest.approx(metadata.landmark_std, abs=1) == 45.0
        assert metadata.landmark_quality == "good"


class TestSuggestionMetadataPoseDescription:
    """Tests for pose_description property."""

    def test_frontal_view(self) -> None:
        """Test frontal view detection."""
        embedding = _create_test_embedding(pose_pitch=5.0, pose_yaw=10.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Frontal view"

    def test_profile_view_right(self) -> None:
        """Test right profile view detection."""
        embedding = _create_test_embedding(pose_yaw=50.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Profile view (right)"

    def test_profile_view_left(self) -> None:
        """Test left profile view detection."""
        embedding = _create_test_embedding(pose_yaw=-50.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Profile view (left)"

    def test_three_quarter_view(self) -> None:
        """Test three-quarter view detection."""
        embedding = _create_test_embedding(pose_yaw=35.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Three-quarter view (right)"

    def test_looking_up(self) -> None:
        """Test looking up detection."""
        embedding = _create_test_embedding(pose_pitch=35.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Looking up"

    def test_looking_down(self) -> None:
        """Test looking down detection."""
        embedding = _create_test_embedding(pose_pitch=-35.0)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.pose_description == "Looking down"


class TestSuggestionMetadataDetectionQuality:
    """Tests for detection_quality property."""

    def test_high_quality(self) -> None:
        """Test high quality detection."""
        embedding = _create_test_embedding(det_score=0.95)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.detection_quality == "high"

    def test_medium_quality(self) -> None:
        """Test medium quality detection."""
        embedding = _create_test_embedding(det_score=0.75)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.detection_quality == "medium"

    def test_low_quality(self) -> None:
        """Test low quality detection."""
        embedding = _create_test_embedding(det_score=0.55)
        metadata = extract_suggestion_metadata(embedding)

        assert metadata.detection_quality == "low"


class TestClassifyFaceSize:
    """Tests for _classify_face_size helper."""

    def test_large_face(self) -> None:
        """Test large face classification."""
        assert _classify_face_size(25000.0) == "large"

    def test_medium_face(self) -> None:
        """Test medium face classification."""
        assert _classify_face_size(10000.0) == "medium"

    def test_small_face(self) -> None:
        """Test small face classification."""
        assert _classify_face_size(3000.0) == "small"

    def test_boundary_large_medium(self) -> None:
        """Test boundary between large and medium."""
        assert _classify_face_size(20001.0) == "large"
        assert _classify_face_size(20000.0) == "medium"

    def test_boundary_medium_small(self) -> None:
        """Test boundary between medium and small."""
        assert _classify_face_size(5001.0) == "medium"
        assert _classify_face_size(5000.0) == "small"


class TestClassifyLandmarkQuality:
    """Tests for _classify_landmark_quality helper."""

    def test_excellent_quality(self) -> None:
        """Test excellent landmark quality."""
        assert _classify_landmark_quality(30.0) == "excellent"

    def test_good_quality(self) -> None:
        """Test good landmark quality."""
        assert _classify_landmark_quality(50.0) == "good"

    def test_fair_quality(self) -> None:
        """Test fair landmark quality."""
        assert _classify_landmark_quality(70.0) == "fair"

    def test_poor_quality(self) -> None:
        """Test poor landmark quality."""
        assert _classify_landmark_quality(90.0) == "poor"


class TestSuggestionMetadataQualityScore:
    """Tests for quality_score computation."""

    def test_high_quality_score(self) -> None:
        """Test quality score for high quality detection."""
        embedding = _create_test_embedding(
            det_score=0.95,  # High
            bbox_area=25000.0,  # Large
            landmark_std=30.0,  # Excellent
        )
        metadata = extract_suggestion_metadata(embedding)

        # 0.95 * 0.5 + 1.0 * 0.3 + 1.0 * 0.2 = 0.475 + 0.3 + 0.2 = 0.975
        assert pytest.approx(metadata.quality_score, abs=0.01) == 0.975

    def test_low_quality_score(self) -> None:
        """Test quality score for low quality detection."""
        embedding = _create_test_embedding(
            det_score=0.5,  # Low
            bbox_area=3000.0,  # Small
            landmark_std=90.0,  # Poor
        )
        metadata = extract_suggestion_metadata(embedding)

        # 0.5 * 0.5 + 0.4 * 0.3 + 0.2 * 0.2 = 0.25 + 0.12 + 0.04 = 0.41
        assert pytest.approx(metadata.quality_score, abs=0.01) == 0.41


class TestSuggestionMetadataToDict:
    """Tests for to_dict serialization."""

    def test_to_dict_contains_all_fields(self) -> None:
        """Test that to_dict includes all expected fields."""
        embedding = _create_test_embedding()
        metadata = extract_suggestion_metadata(embedding)
        result = metadata.to_dict()

        expected_keys = {
            "pose_pitch",
            "pose_yaw",
            "pose_roll",
            "pose_description",
            "age",
            "gender",
            "detection_score",
            "detection_quality",
            "face_size_quality",
            "landmark_quality",
            "quality_score",
        }
        assert set(result.keys()) == expected_keys

    def test_to_dict_values_are_serializable(self) -> None:
        """Test that all values are JSON-serializable types."""
        embedding = _create_test_embedding()
        metadata = extract_suggestion_metadata(embedding)
        result = metadata.to_dict()

        import json

        # Should not raise
        json.dumps(result)


class TestExtractMetadataForComparison:
    """Tests for extract_metadata_for_comparison function."""

    def test_identity_only(self) -> None:
        """Test extraction with identity only."""
        embedding = _create_test_embedding()
        result = extract_metadata_for_comparison(embedding)

        assert "identity" in result
        assert "representative" not in result

    def test_with_representative(self) -> None:
        """Test extraction with both identity and representative."""
        identity_embedding = _create_test_embedding(age=25)
        rep_embedding = _create_test_embedding(age=30)

        result = extract_metadata_for_comparison(identity_embedding, rep_embedding)

        assert "identity" in result
        assert "representative" in result
        assert result["identity"]["age"] == 25
        assert result["representative"]["age"] == 30
