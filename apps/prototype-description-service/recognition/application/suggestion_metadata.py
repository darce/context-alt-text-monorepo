"""Utility for extracting human-readable metadata from 1024D embeddings.

This module provides functions to decode the metadata stored in extended
embeddings (indices 512+) into human-readable format for the suggestion UI.

See: docs/tasks/4.0/4.2.3/improve-suggestion-ux-reduce-false-negatives.md
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from recognition.domain.embeddings.layout import (
    AGE_IDX,
    AGE_SCALE,
    BBOX_AREA_IDX,
    BBOX_AREA_SCALE,
    DET_SCORE_IDX,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    LANDMARK_STD_SCALE,
    POSE_SCALE,
    POSE_START,
)


@dataclass
class SuggestionMetadata:
    """Human-readable metadata extracted from 1024D embedding.

    Used to provide context in the suggestion review UI, helping users
    understand why a match may have lower confidence.
    """

    # Pose information (in degrees)
    pose_pitch: float
    pose_yaw: float
    pose_roll: float

    # Demographics (optional - may not be available)
    age: int | None
    gender: str | None  # "female", "male", or None

    # Quality metrics
    detection_score: float  # InsightFace confidence [0-1]
    face_size_quality: str  # "large", "medium", "small"
    landmark_quality: str  # "excellent", "good", "fair", "poor"

    # Raw values for advanced display
    bbox_area: float  # pixels^2
    landmark_std: float  # standard deviation

    @property
    def pose_description(self) -> str:
        """Human-readable pose description for UI display."""
        # Check yaw first (left/right rotation)
        if abs(self.pose_yaw) > 45:
            direction = "right" if self.pose_yaw > 0 else "left"
            return f"Profile view ({direction})"
        if abs(self.pose_yaw) > 30:
            direction = "right" if self.pose_yaw > 0 else "left"
            return f"Three-quarter view ({direction})"

        # Check pitch (up/down)
        if abs(self.pose_pitch) > 30:
            return "Looking up" if self.pose_pitch > 0 else "Looking down"
        if abs(self.pose_pitch) > 20:
            direction = "up" if self.pose_pitch > 0 else "down"
            return f"Slightly {direction}"

        return "Frontal view"

    @property
    def detection_quality(self) -> str:
        """Classify detection quality for UI display."""
        if self.detection_score >= 0.9:
            return "high"
        if self.detection_score >= 0.7:
            return "medium"
        return "low"

    @property
    def quality_score(self) -> float:
        """Combined quality score 0-1 for ranking suggestions.

        Weights:
        - Detection score: 50% (primary signal from InsightFace)
        - Face size: 30% (larger faces = more reliable embeddings)
        - Landmark quality: 20% (frontal faces match better)
        """
        return self.detection_score * 0.5 + self._face_size_score() * 0.3 + self._landmark_score() * 0.2

    def _face_size_score(self) -> float:
        """Convert face size to 0-1 score."""
        if self.face_size_quality == "large":
            return 1.0
        if self.face_size_quality == "medium":
            return 0.7
        return 0.4

    def _landmark_score(self) -> float:
        """Convert landmark quality to 0-1 score."""
        scores = {"excellent": 1.0, "good": 0.8, "fair": 0.5, "poor": 0.2}
        return scores.get(self.landmark_quality, 0.5)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "pose_pitch": round(self.pose_pitch, 1),
            "pose_yaw": round(self.pose_yaw, 1),
            "pose_roll": round(self.pose_roll, 1),
            "pose_description": self.pose_description,
            "age": self.age,
            "gender": self.gender,
            "detection_score": round(self.detection_score, 3),
            "detection_quality": self.detection_quality,
            "face_size_quality": self.face_size_quality,
            "landmark_quality": self.landmark_quality,
            "quality_score": round(self.quality_score, 3),
        }


def _classify_face_size(bbox_area: float) -> str:
    """Classify face size based on bounding box area.

    Thresholds are based on typical webcam/photo resolutions:
    - Large: > 20,000 px² (e.g., 150x150+ face in frame)
    - Medium: 5,000 - 20,000 px² (typical portrait)
    - Small: < 5,000 px² (group photo or distant face)
    """
    if bbox_area > 20000:
        return "large"
    if bbox_area > 5000:
        return "medium"
    return "small"


def _classify_landmark_quality(landmark_std: float) -> str:
    """Classify landmark quality based on standard deviation.

    The std dev of facial landmark positions indicates face orientation
    and detection reliability:
    - Low std (< 40): Frontal, well-detected face
    - High std (> 80): Profile view or partially occluded
    """
    if landmark_std < 40:
        return "excellent"
    if landmark_std < 60:
        return "good"
    if landmark_std < 80:
        return "fair"
    return "poor"


def extract_suggestion_metadata(embedding: np.ndarray) -> SuggestionMetadata:
    """Extract human-readable metadata from a 1024D extended embedding.

    Args:
        embedding: The 1024D extended embedding array

    Returns:
        SuggestionMetadata with decoded values for UI display

    Example:
        >>> metadata = extract_suggestion_metadata(identity.embedding)
        >>> print(f"Pose: {metadata.pose_description}")
        >>> print(f"Quality: {metadata.detection_quality}")
    """
    # Decode pose (stored as degrees / 90.0)
    pose_pitch = float(embedding[POSE_START]) * POSE_SCALE
    pose_yaw = float(embedding[POSE_START + 1]) * POSE_SCALE
    pose_roll = float(embedding[POSE_START + 2]) * POSE_SCALE

    # Decode age (stored as age / 100.0)
    raw_age = float(embedding[AGE_IDX])
    age = round(raw_age * AGE_SCALE) if raw_age > 0 else None

    # Decode gender (0=female, 1=male)
    raw_gender = float(embedding[GENDER_IDX])
    if raw_gender == 0:
        gender = "female"
    elif raw_gender == 1:
        gender = "male"
    else:
        gender = None

    # Detection score is stored directly as [0, 1]
    detection_score = float(embedding[DET_SCORE_IDX])

    # Decode bbox area (stored as area / 50000)
    bbox_area = float(embedding[BBOX_AREA_IDX]) * BBOX_AREA_SCALE
    face_size_quality = _classify_face_size(bbox_area)

    # Decode landmark std (stored as std / 100.0)
    landmark_std = float(embedding[LANDMARK_QUALITY_IDX]) * LANDMARK_STD_SCALE
    landmark_quality = _classify_landmark_quality(landmark_std)

    return SuggestionMetadata(
        pose_pitch=pose_pitch,
        pose_yaw=pose_yaw,
        pose_roll=pose_roll,
        age=age,
        gender=gender,
        detection_score=detection_score,
        face_size_quality=face_size_quality,
        landmark_quality=landmark_quality,
        bbox_area=bbox_area,
        landmark_std=landmark_std,
    )


def extract_metadata_for_comparison(
    identity_embedding: np.ndarray,
    representative_embedding: np.ndarray | None = None,
) -> dict[str, object]:
    """Extract metadata for both identity and representative for comparison UI.

    Args:
        identity_embedding: The candidate identity's embedding
        representative_embedding: Optional cluster representative embedding

    Returns:
        Dictionary with identity metadata and optional representative metadata
    """
    result: dict[str, object] = {
        "identity": extract_suggestion_metadata(identity_embedding).to_dict(),
    }

    if representative_embedding is not None:
        result["representative"] = extract_suggestion_metadata(representative_embedding).to_dict()

    return result
