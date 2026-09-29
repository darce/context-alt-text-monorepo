"""Identity quality score computation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Final, Literal

from recognition.application.settings import QualitySettings
from recognition.domain.maturity import ClusterMaturityLevel

logger = logging.getLogger(__name__)

# Default settings instance for backward compatibility
_default_settings = QualitySettings()

RepresentativeQualityPolicy = Literal["legacy", "composite"]
_LEGACY_REPRESENTATIVE_QUALITY_POLICY: Final[RepresentativeQualityPolicy] = "legacy"
_COMPOSITE_REPRESENTATIVE_QUALITY_POLICY: Final[RepresentativeQualityPolicy] = "composite"


@dataclass(frozen=True, slots=True)
class IdentityQualityInfo:
    """Quality information for an identity.

    Canonical threshold quality is pose-neutral (confidence + bbox size only)
    so model profiles that cannot emit pose are not silently disadvantaged.
    OACT may add a separate threshold_adjustment term from occlusion_severity
    (FIR-6 S1); the score formula itself stays pose/occlusion-neutral (EVAL-08).
    Representative ranking uses :class:`RepresentativeQuality`, not ``score``.
    """

    score: float  # 0.0 to 1.0
    confidence: float
    size_factor: float
    threshold_adjustment: float  # Delta to apply


@dataclass(frozen=True, slots=True)
class RepresentativeQuality:
    """Selected representative score plus the components stored beside it.

    ``composite`` is the value written to the existing ``quality_score`` column.
    It follows the legacy confidence×bbox path until the composite policy is
    explicitly enabled in :class:`QualitySettings`. ``score_policy`` records
    which path produced that value.
    ``components`` is the ``quality_components`` JSON payload (UXR-15):
    confidence, bbox_area, sharpness, occlusion_severity.
    """

    composite: float
    confidence: float
    bbox_term: float
    bbox_area: float
    occlusion_severity: float | None
    occlusion_term: float
    sharpness: float | None
    sharpness_term: float
    k_occ: float
    score_policy: RepresentativeQualityPolicy = _LEGACY_REPRESENTATIVE_QUALITY_POLICY

    def components(self) -> dict[str, float | None]:
        """Return all four wire components, preserving missing signals as null."""
        return {
            "confidence": float(self.confidence),
            "bbox_area": float(self.bbox_area),
            "sharpness": None if self.sharpness is None else float(self.sharpness),
            "occlusion_severity": (None if self.occlusion_severity is None else float(self.occlusion_severity)),
        }


def min_bbox_area_from_settings(settings: QualitySettings | None = None) -> float:
    """Representative-only area floor for the C4 bbox term."""
    area = _finite_float((settings or _default_settings).min_bbox_area, "min_bbox_area")
    if area <= 0.0:
        raise ValueError("min_bbox_area must be greater than zero")
    return max(area, 1.0)


def _finite_float(value: float, name: str) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{name} must be finite")
    return numeric


def _clamp01(value: float, name: str = "quality factor") -> float:
    return max(0.0, min(1.0, _finite_float(value, name)))


def _geometric_mean(left: float, right: float) -> float:
    if left <= 0.0 or right <= 0.0:
        return 0.0
    return sqrt(left * right)


def _bbox_area(bbox_width: int, bbox_height: int) -> float:
    width = max(0.0, _finite_float(bbox_width, "bbox_width"))
    height = max(0.0, _finite_float(bbox_height, "bbox_height"))
    area = width * height
    if not isfinite(area):
        raise ValueError("bbox area must be finite")
    return area


def _bbox_term(area: float, settings: QualitySettings) -> float:
    return min(1.0, area / min_bbox_area_from_settings(settings))


def _occlusion_term(occlusion_severity: float | None, k_occ: float) -> float:
    coefficient = _finite_float(k_occ, "oact_coefficient")
    severity = 0.0 if occlusion_severity is None else _clamp01(occlusion_severity, "occlusion_severity")
    return max(0.0, 1.0 - severity * max(0.0, coefficient))


def _sharpness_term(sharpness: float | None, settings: QualitySettings) -> float:
    """Laplacian variance has no calibrated scale until the sharpness floor is active.

    Missing sharpness does not penalize (insightface). No-op floor (0.0) keeps
    the term at 1.0 so we do not invent a Laplacian reference.
    """
    floor = _finite_float(settings.factor_floor_sharpness, "factor_floor_sharpness")
    if sharpness is None:
        return 1.0
    measured_sharpness = _finite_float(sharpness, "sharpness")
    if floor <= 0.0:
        return 1.0
    return min(1.0, max(0.0, measured_sharpness / max(floor * 2.0, 1e-6)))


def occlusion_rank(occlusion_severity: float | None) -> float:
    """Primary representative sort key: lower is better; missing is not penalized."""
    if occlusion_severity is None:
        return 0.0
    return _clamp01(occlusion_severity, "occlusion_severity")


def compute_representative_quality(
    *,
    confidence: float,
    bbox_width: int,
    bbox_height: int,
    sharpness: float | None = None,
    occlusion_severity: float | None = None,
    settings: QualitySettings | None = None,
) -> RepresentativeQuality:
    """Select the legacy score or gated C4 composite for representative use.

    ``k_occ`` is ``QualitySettings.oact_coefficient`` (C1 policy alias; default
    0.0, not a promoted runtime rename). Unoccluded-first ranking is a separate
    lexicographic key in :func:`representative_sort_key` so an occluded face
    loses to an unoccluded one even while ``k_occ`` stays 0. The C4 composite
    is selected only when ``representative_quality_composite_enabled`` is true;
    the default keeps the pre-composite confidence×bbox score.
    """
    s = settings or _default_settings
    confidence_value = _finite_float(confidence, "confidence")
    bbox_area = _bbox_area(bbox_width, bbox_height)
    conf = _clamp01(confidence_value)
    bbox_term = _bbox_term(bbox_area, s)
    k_occ = _finite_float(s.oact_coefficient, "oact_coefficient")
    occ_term = _occlusion_term(occlusion_severity, k_occ)
    sharp_term = _sharpness_term(sharpness, s)
    occ_sev = None if occlusion_severity is None else _clamp01(occlusion_severity, "occlusion_severity")
    composite_score = round(
        _clamp01(_geometric_mean(conf, bbox_term) * occ_term * sharp_term),
        3,
    )
    legacy_score = compute_identity_quality(
        confidence=confidence_value,
        bbox_width=bbox_width,
        bbox_height=bbox_height,
        settings=s,
    ).score
    use_composite = s.representative_quality_composite_enabled
    score_policy: RepresentativeQualityPolicy = (
        _COMPOSITE_REPRESENTATIVE_QUALITY_POLICY if use_composite else _LEGACY_REPRESENTATIVE_QUALITY_POLICY
    )
    selected_score = composite_score if use_composite else legacy_score
    logger.debug(
        "representative quality score selected",
        extra={"quality_score": selected_score, "score_policy": score_policy},
    )
    return RepresentativeQuality(
        composite=selected_score,
        confidence=conf,
        bbox_term=round(bbox_term, 6),
        bbox_area=bbox_area,
        occlusion_severity=occ_sev,
        occlusion_term=occ_term,
        sharpness=sharpness,
        sharpness_term=sharp_term,
        k_occ=k_occ,
        score_policy=score_policy,
    )


def representative_sort_key(
    *,
    confidence: float,
    bbox_width: int,
    bbox_height: int,
    sharpness: float | None = None,
    occlusion_severity: float | None = None,
    identity_id: str = "",
    settings: QualitySettings | None = None,
) -> tuple[float, float, str]:
    """Unoccluded-first, then highest composite, then id. Sort ascending."""
    quality = compute_representative_quality(
        confidence=confidence,
        bbox_width=bbox_width,
        bbox_height=bbox_height,
        sharpness=sharpness,
        occlusion_severity=occlusion_severity,
        settings=settings,
    )
    return (occlusion_rank(occlusion_severity), -quality.composite, identity_id)


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
    confidence_value = _finite_float(confidence, "confidence")
    width = _finite_float(bbox_width, "bbox_width")
    height = _finite_float(bbox_height, "bbox_height")
    min_face_size = _finite_float(s.min_face_size, "min_face_size")
    if min_face_size <= 0.0:
        raise ValueError("min_face_size must be greater than zero")

    # Size factor: punish faces below min_face_size
    min_dim = min(width, height)
    size_factor = min(1.0, min_dim / min_face_size)

    # Combined score (confidence × size only)
    raw_score = confidence_value * size_factor
    score = round(_clamp01(raw_score), 3)

    return IdentityQualityInfo(
        score=score,
        confidence=confidence_value,
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
    quality_score = _finite_float(quality_score, "quality_score")
    coefficient = _finite_float(s.oact_coefficient, "oact_coefficient")

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
        severity = _clamp01(occlusion_severity, "occlusion_severity")
        if coefficient != 0.0:
            oact_term = +(coefficient * severity)

    return base_adjustment + oact_term
