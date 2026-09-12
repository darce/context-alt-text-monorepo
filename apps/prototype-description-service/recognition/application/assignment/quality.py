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
    OACT may add a separate threshold_adjustment term from occlusion_severity
    (FIR-6 S1); the score formula itself stays pose/occlusion-neutral (EVAL-08).
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
    occlusion_severity: float | None = None,
) -> IdentityQualityInfo:
    """Compute identity quality score from detection metrics.

    Score depends only on confidence and bbox size (FIR2-BR-03). Pose remains
    available on FaceDetection / MediaIdentity for explicit pose-bucket /
    diversity logic, not for threshold quality. Occlusion severity feeds the
    OACT ``threshold_adjustment`` channel only (never the score).

    Args:
        confidence: Detection confidence (0-1).
        bbox_width: Bounding box width in pixels.
        bbox_height: Bounding box height in pixels.
        settings: Optional quality settings. Uses defaults if not provided.
        maturity: Optional cluster maturity level to dampen adjustments.
        occlusion_severity: Optional [0,1] occlusion factor for OACT; None ⇒ 0 term.

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
        threshold_adjustment=compute_quality_adjustment(
            score,
            settings=s,
            maturity=maturity,
            occlusion_severity=occlusion_severity,
        ),
    )


def compute_quality_adjustment(
    quality_score: float,
    settings: QualitySettings | None = None,
    maturity: ClusterMaturityLevel | None = None,
    occlusion_severity: float | None = None,
) -> float:
    """Return threshold adjustment for a quality score (+ optional OACT term).

    Args:
        quality_score: Identity quality (0-1).
        settings: Optional quality settings. Uses defaults if not provided.
        maturity: Optional maturity dampening for the base quality band.
        occlusion_severity: Optional occlusion for OACT; None or coefficient 0
            ⇒ no extra term (dark default).

    Returns:
        Float adjustment (positive = stricter, negative = more lenient).

    Design notes (FIR-6 S1 exact form, FIR6S1-M-09):
        * OACT term is ``+(oact_coefficient × clamp(severity, 0, 1))`` added
          **undamped** after maturity scaling of the base quality band only.
          COLD clusters therefore get 0.25× band adjustment but full OACT
          tightening. Maturity dampening models cluster certainty; occlusion is
          a per-observation property independent of cluster age, so it is not
          double-discounted. Revisit only with S4 measured before/after deltas.
        * Callers that discard ``threshold_adjustment`` (detector score path,
          representative_selector score path) may still thread
          ``occlusion_severity`` for API symmetry / future use — inert until
          they consume the adjustment channel.
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

    if maturity is not None:
        dampening = {
            ClusterMaturityLevel.COLD: 0.25,
            ClusterMaturityLevel.NASCENT: 0.50,
            ClusterMaturityLevel.CONFIRMED: 0.75,
            ClusterMaturityLevel.MATURE: 1.0,
        }
        base_adjustment = base_adjustment * dampening.get(maturity, 1.0)

    # OACT: undamped +(coeff × severity); maturity damps base band only (see notes).
    oact_term = 0.0
    if occlusion_severity is not None:
        coeff = float(s.oact_coefficient)
        if coeff != 0.0:
            severity = max(0.0, min(1.0, float(occlusion_severity)))
            oact_term = +(coeff * severity)

    return base_adjustment + oact_term
