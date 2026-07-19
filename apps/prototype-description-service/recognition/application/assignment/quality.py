"""Identity quality score computation."""

from __future__ import annotations

from dataclasses import dataclass

from recognition.application.settings import QualitySettings
from recognition.domain.maturity import ClusterMaturityLevel

# Default settings instance for backward compatibility
_default_settings = QualitySettings()


@dataclass(frozen=True, slots=True)
class IdentityQualityInfo:
    """Quality information for an identity.

    Canonical threshold quality is pose-neutral (confidence + bbox size only)
    so model profiles that cannot emit pose are not silently disadvantaged.
    """

    score: float  # 0.0 to 1.0
    confidence: float
    size_factor: float
    threshold_adjustment: float  # Delta to apply


def compute_identity_quality(
    *,
    confidence: float,
    bbox_width: int,
    bbox_height: int,
    settings: QualitySettings | None = None,
    maturity: ClusterMaturityLevel | None = None,
) -> IdentityQualityInfo:
    """Compute identity quality score from detection metrics.

    Score depends only on confidence and bbox size (FIR2-BR-03). Pose remains
    available on FaceDetection / MediaIdentity for explicit pose-bucket /
    diversity logic, not for threshold quality.

    Args:
        confidence: Detection confidence (0-1).
        bbox_width: Bounding box width in pixels.
        bbox_height: Bounding box height in pixels.
        settings: Optional quality settings. Uses defaults if not provided.
        maturity: Optional cluster maturity level to dampen adjustments.

    Returns:
        IdentityQualityInfo with computed score and adjustment.
    """
    s = settings or _default_settings

    # Size factor: punish faces below min_face_size
    min_dim = min(bbox_width, bbox_height)
    size_factor = min(1.0, min_dim / s.min_face_size)

    # Combined score (confidence × size only)
    raw_score = confidence * size_factor
    score = round(max(0.0, min(1.0, raw_score)), 3)

    return IdentityQualityInfo(
        score=score,
        confidence=confidence,
        size_factor=size_factor,
        threshold_adjustment=compute_quality_adjustment(score, settings=s, maturity=maturity),
    )


def compute_quality_adjustment(
    quality_score: float,
    settings: QualitySettings | None = None,
    maturity: ClusterMaturityLevel | None = None,
) -> float:
    """Return threshold adjustment for a quality score.

    Args:
        quality_score: Identity quality (0-1).
        settings: Optional quality settings. Uses defaults if not provided.

    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    s = settings or _default_settings

    if quality_score >= s.high_quality_threshold:
        base_adjustment = s.high_quality_adjustment
    elif quality_score >= s.neutral_quality_threshold:
        base_adjustment = s.neutral_quality_adjustment
    elif quality_score >= s.mediocre_quality_threshold:
        base_adjustment = s.mediocre_quality_adjustment
    else:
        base_adjustment = s.poor_quality_adjustment

    if maturity is None:
        return base_adjustment

    dampening = {
        ClusterMaturityLevel.COLD: 0.25,
        ClusterMaturityLevel.NASCENT: 0.50,
        ClusterMaturityLevel.CONFIRMED: 0.75,
        ClusterMaturityLevel.MATURE: 1.0,
    }

    return base_adjustment * dampening.get(maturity, 1.0)
