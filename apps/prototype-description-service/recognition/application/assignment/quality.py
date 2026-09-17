"""Identity quality score computation."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

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
    Representative ranking uses :class:`RepresentativeQuality`, not ``score``.
    """

    score: float  # 0.0 to 1.0
    confidence: float
    size_factor: float
    threshold_adjustment: float  # Delta to apply


@dataclass(frozen=True, slots=True)
class RepresentativeQuality:
    """C4 representative composite plus the components stored beside it.

    ``composite`` is the value written to the existing ``quality_score`` column.
    ``components`` is the ``quality_components`` JSON payload (UXR-15):
    confidence, bbox_area, sharpness, occlusion_severity.
    """

    composite: float
    confidence: float
    bbox_term: float
    bbox_area: float
    occlusion_severity: float
    occlusion_term: float
    sharpness: float | None
    sharpness_term: float
    k_occ: float

    def components(self) -> dict[str, float]:
        """Wire/storage payload; sharpness 0.0 when the signal is missing."""
        return {
            "confidence": self.confidence,
            "bbox_area": self.bbox_area,
            "sharpness": 0.0 if self.sharpness is None else float(self.sharpness),
            "occlusion_severity": self.occlusion_severity,
        }


def min_bbox_area_from_settings(settings: QualitySettings | None = None) -> float:
    """Area floor for the C4 bbox term.

    ``QualitySettings`` has ``min_face_size`` (px), not ``min_bbox_area``. The
    area floor is ``min_face_size²`` so a face that saturates the linear size
    factor also saturates the area term. Not a named-identity fit.
    """
    size = float((settings or _default_settings).min_face_size)
    return max(size * size, 1.0)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _geometric_mean(left: float, right: float) -> float:
    if left <= 0.0 or right <= 0.0:
        return 0.0
    return sqrt(left * right)


def _bbox_term(bbox_width: int, bbox_height: int, settings: QualitySettings) -> float:
    area = max(0.0, float(bbox_width) * float(bbox_height))
    return min(1.0, area / min_bbox_area_from_settings(settings))


def _occlusion_term(occlusion_severity: float | None, k_occ: float) -> float:
    severity = 0.0 if occlusion_severity is None else _clamp01(occlusion_severity)
    return max(0.0, 1.0 - severity * max(0.0, float(k_occ)))


def _sharpness_term(sharpness: float | None, settings: QualitySettings) -> float:
    """Laplacian variance has no calibrated scale until the sharpness floor is active.

    Missing sharpness does not penalize (insightface). No-op floor (0.0) keeps
    the term at 1.0 so we do not invent a Laplacian reference.
    """
    if sharpness is None:
        return 1.0
    floor = float(settings.factor_floor_sharpness)
    if floor <= 0.0:
        return 1.0
    return min(1.0, max(0.0, float(sharpness) / max(floor * 2.0, 1e-6)))


def occlusion_rank(occlusion_severity: float | None) -> float:
    """Primary representative sort key: lower is better; missing is not penalized."""
    if occlusion_severity is None:
        return 0.0
    return _clamp01(occlusion_severity)


def compute_representative_quality(
    *,
    confidence: float,
    bbox_width: int,
    bbox_height: int,
    sharpness: float | None = None,
    occlusion_severity: float | None = None,
    settings: QualitySettings | None = None,
) -> RepresentativeQuality:
    """C4 composite: geomean(confidence, bbox_term) × (1 − occ·k_occ) × sharpness.

    ``k_occ`` is ``QualitySettings.oact_coefficient`` (C1 policy alias; default
    0.0, not a promoted runtime rename). Unoccluded-first ranking is a separate
    lexicographic key in :func:`representative_sort_key` so an occluded face
    loses to an unoccluded one even while ``k_occ`` stays 0.
    """
    s = settings or _default_settings
    conf = _clamp01(confidence)
    bbox_term = _bbox_term(bbox_width, bbox_height, s)
    k_occ = float(s.oact_coefficient)
    occ_term = _occlusion_term(occlusion_severity, k_occ)
    sharp_term = _sharpness_term(sharpness, s)
    occ_sev = 0.0 if occlusion_severity is None else _clamp01(occlusion_severity)
    composite = round(_clamp01(_geometric_mean(conf, bbox_term) * occ_term * sharp_term), 3)
    return RepresentativeQuality(
        composite=composite,
        confidence=conf,
        bbox_term=round(bbox_term, 6),
        bbox_area=float(max(0, bbox_width) * max(0, bbox_height)),
        occlusion_severity=occ_sev,
        occlusion_term=occ_term,
        sharpness=sharpness,
        sharpness_term=sharp_term,
        k_occ=k_occ,
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
