"""Identity quality score computation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdentityQualityInfo:
    """Quality information for an identity."""

    score: float  # 0.0 to 1.0
    confidence: float
    pose_penalty: float
    size_factor: float
    threshold_adjustment: float  # Delta to apply


def compute_identity_quality(
    *,
    confidence: float,
    pose_pitch: float | None,
    pose_yaw: float | None,
    pose_roll: float | None,
    bbox_width: int,
    bbox_height: int,
) -> IdentityQualityInfo:
    """Compute identity quality score from detection metrics.

    Args:
        confidence: Detection confidence (0-1).
        pose_pitch: Head pitch angle in degrees.
        pose_yaw: Head yaw angle in degrees.
        pose_roll: Head roll angle in degrees.
        bbox_width: Bounding box width in pixels.
        bbox_height: Bounding box height in pixels.

    Returns:
        IdentityQualityInfo with computed score and adjustment.
    """
    # 1. Pose penalty: angles > 20 deg start reducing quality rapidly
    # Approx logic: 1.0 at 0 deg, 0.5 at 45 deg
    # Using simplistic linear penalty for now
    total_angle = abs(pose_pitch or 0) + abs(pose_yaw or 0) + abs(pose_roll or 0)
    pose_penalty = max(0.0, 1.0 - (total_angle / 90.0))  # Zero at 90 deg deviation

    # 2. Size factor: punish faces < 50px
    min_dim = min(bbox_width, bbox_height)
    size_factor = min(1.0, min_dim / 80.0)

    # 3. Combined score
    raw_score = confidence * pose_penalty * size_factor
    score = round(max(0.0, min(1.0, raw_score)), 3)

    return IdentityQualityInfo(
        score=score,
        confidence=confidence,
        pose_penalty=pose_penalty,
        size_factor=size_factor,
        threshold_adjustment=compute_quality_adjustment(score),
    )


def compute_quality_adjustment(quality_score: float) -> float:
    """Return threshold adjustment for a quality score.

    Args:
        quality_score: Identity quality (0-1).

    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    if quality_score >= 0.9:
        return -0.05  # Highly trusted: loosen threshold significantly
    if quality_score >= 0.8:
        return 0.0  # Neutral zone
    if quality_score >= 0.6:
        return 0.02  # Mediocre: tighten slightly

    # Poor quality: tighten significantly
    return 0.05
