"""Assignment guardrails for clustering."""

from __future__ import annotations

import logging


def log_borderline_assignment(
    logger: logging.Logger,
    identity_id,
    cluster_id,
    similarity: float,
    threshold: float,
    window: float,
) -> None:
    """Log when an assignment is within the configured window of the threshold."""

    if abs(similarity - threshold) <= window:
        logger.warning(
            "Borderline assignment: identity %s to cluster %s (similarity %.4f, threshold %.4f)",
            identity_id,
            cluster_id,
            similarity,
            threshold,
        )
