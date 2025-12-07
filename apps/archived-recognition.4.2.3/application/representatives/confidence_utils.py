"""Confidence weighting utilities for clustering (Slice A: Option C).

This module implements detection quality-based confidence weighting to adjust
similarity thresholds dynamically. High-quality detections (large faces with
high det_score) get easier matching, while low-quality detections require
higher similarity to prevent false positives.

See: docs/tasks/4.0/4.2.3/clustering-algorithm-comprehensive-analysis.md (Q10)
"""

from __future__ import annotations

import numpy as np


def compute_detection_confidence(
    det_score: float,
    bbox_area: int,
    min_bbox_area: int = 10000,
) -> float:
    """
    Compute confidence factor from detection quality.

    Uses geometric mean of detection score and size confidence to produce
    a balanced confidence metric that penalizes both low detection quality
    and small face sizes.

    Args:
        det_score: Detection confidence from face detector (0-1).
        bbox_area: Area of bounding box in pixels (width * height).
        min_bbox_area: Minimum bbox area for full size confidence.
            Faces smaller than this are penalized proportionally.

    Returns:
        float: Confidence factor in [0, 1]. Higher values indicate
        more reliable detections suitable for lower matching thresholds.

    Example:
        >>> compute_detection_confidence(det_score=0.95, bbox_area=40000)
        0.975...  # High quality, large face
        >>> compute_detection_confidence(det_score=0.65, bbox_area=2500)
        0.403...  # Low quality, small face
    """
    # Detection confidence (direct from detector)
    det_conf = float(det_score)

    # Size confidence (penalize small faces)
    # Clamp to [0, 1] to handle oversized faces
    size_conf = min(1.0, bbox_area / min_bbox_area) if min_bbox_area > 0 else 1.0

    # Handle edge case of zero area
    if bbox_area <= 0:
        size_conf = 0.0

    # Geometric mean balances both factors
    # sqrt(a * b) ensures neither factor dominates
    product = det_conf * size_conf
    if product <= 0:
        return 0.0

    return float(np.sqrt(product))


def compute_pair_confidence(
    source_det_score: float,
    source_bbox_area: int,
    target_det_score: float,
    target_bbox_area: int,
    min_bbox_area: int = 10000,
) -> float:
    """
    Compute confidence for a pair of detections.

    Uses geometric mean of individual confidences to ensure both
    detections contribute to the pair quality assessment.

    Args:
        source_det_score: Detection score of source face.
        source_bbox_area: Bounding box area of source face.
        target_det_score: Detection score of target face.
        target_bbox_area: Bounding box area of target face.
        min_bbox_area: Minimum bbox area for full size confidence.

    Returns:
        float: Pair confidence in [0, 1]. Used to adjust similarity
        thresholds for this specific comparison.

    Example:
        >>> compute_pair_confidence(0.95, 30000, 0.92, 25000)
        0.93...  # Both high quality
        >>> compute_pair_confidence(0.95, 40000, 0.65, 3000)
        0.72...  # Mixed quality
    """
    source_conf = compute_detection_confidence(source_det_score, source_bbox_area, min_bbox_area)
    target_conf = compute_detection_confidence(target_det_score, target_bbox_area, min_bbox_area)

    product = source_conf * target_conf
    if product <= 0:
        return 0.0

    return float(np.sqrt(product))


def adaptive_threshold(
    base_threshold: float,
    confidence: float,
    confidence_midpoint: float = 0.85,
    threshold_max_adjustment: float = 0.10,
) -> float:
    """
    Adjust threshold based on detection confidence.

    High confidence detections get a lower threshold (easier to match),
    while low confidence detections get a higher threshold (harder to match).
    This implements "Option C" from the clustering analysis document.

    The adjustment formula:
        adjustment = max_adj * (confidence - midpoint) / (1.0 - midpoint)
        adjusted_threshold = base_threshold - adjustment

    Args:
        base_threshold: Default similarity threshold (e.g., 0.65).
        confidence: Pair or detection confidence in [0, 1].
        confidence_midpoint: Confidence level at which no adjustment occurs.
            Default 0.85 means faces with 85% confidence match at base threshold.
        threshold_max_adjustment: Maximum threshold change in either direction.
            Default 0.10 means threshold can vary from base ± 0.10.

    Returns:
        float: Adjusted threshold. Lower for high confidence (easier matching),
        higher for low confidence (stricter matching).

    Example:
        >>> adaptive_threshold(0.65, confidence=0.95)  # High confidence
        0.583...  # Lower threshold, easier to match
        >>> adaptive_threshold(0.65, confidence=0.70)  # Low confidence
        0.75  # Higher threshold, harder to match
    """
    # Calculate raw adjustment
    # Positive when confidence > midpoint (should lower threshold)
    # Negative when confidence < midpoint (should raise threshold)
    if confidence_midpoint >= 1.0:
        # Avoid division by zero
        adjustment = 0.0
    else:
        adjustment = threshold_max_adjustment * (confidence - confidence_midpoint) / (1.0 - confidence_midpoint)

    # Clamp adjustment to bounds
    adjustment = float(np.clip(adjustment, -threshold_max_adjustment, threshold_max_adjustment))

    # Apply adjustment (subtract because positive adjustment should lower threshold)
    return base_threshold - adjustment
