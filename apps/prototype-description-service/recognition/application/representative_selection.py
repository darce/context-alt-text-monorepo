"""Helpers for selecting representative embeddings for clusters."""

from __future__ import annotations

import logging

import numpy as np

from recognition.application.centroid_utils import _normalize_vector, compute_similarity

logger = logging.getLogger(__name__)


def decide_representative_acceptance(
    existing_reps: list[np.ndarray],
    candidate_embedding: np.ndarray,
    quality_score: float,
    current_media_count: int,
    max_reps_per_media: int,
    min_diversity_similarity: float,
    quality_weight: float,
    diversity_weight: float,
) -> tuple[bool, float, float]:
    """
    Decide whether to accept a candidate representative embedding.

    Returns a tuple of (accept: bool, combined_score: float, diversity_score: float).
    - diversity_score is the minimum similarity to existing reps (1.0 for first rep).
    - combined_score uses a weighted blend of quality and diversity.
    """

    if current_media_count >= max_reps_per_media:
        logger.debug(
            "REJECT representative: media already has %d reps (max=%d)",
            current_media_count,
            max_reps_per_media,
        )
        return False, 0.0, 0.0

    normalized_candidate = _normalize_vector(np.array(candidate_embedding, dtype=np.float32))

    if not existing_reps:
        diversity_score = 1.0
        logger.debug("ACCEPT representative: first rep for cluster (quality=%.3f)", quality_score)
    else:
        similarities = [
            compute_similarity(normalized_candidate, _normalize_vector(rep.astype(np.float32))) for rep in existing_reps
        ]
        diversity_score = min(similarities)
        logger.debug(
            "Representative diversity check: min_similarity=%.3f (threshold=%.3f, existing_reps=%d)",
            diversity_score,
            min_diversity_similarity,
            len(existing_reps),
        )

    if existing_reps and diversity_score > min_diversity_similarity:
        logger.info(
            "REJECT representative: too similar to existing (diversity=%.3f > threshold=%.3f)",
            diversity_score,
            min_diversity_similarity,
        )
        return False, 0.0, diversity_score

    combined_score = quality_weight * quality_score + diversity_weight * (1.0 - diversity_score)
    logger.info(
        "ACCEPT representative: diversity=%.3f, quality=%.3f, combined=%.3f",
        diversity_score,
        quality_score,
        combined_score,
    )
    return True, combined_score, diversity_score
