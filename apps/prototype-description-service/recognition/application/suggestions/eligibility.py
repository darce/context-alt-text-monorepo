"""Eligibility checks for suggestion targets."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    """Return True if a cluster can be surfaced as a suggestion target.

    All clusters are eligible for suggestions. The UI is responsible for
    filtering suggestions to labeled clusters if needed. This allows
    suggestions to be created during initial clustering before any
    clusters have been labeled by the user.
    """
    if tenant_id and getattr(cluster, "tenant_id", "").lower() != tenant_id.lower():
        logger.info("[suggestions] Skipping suggestion: tenant mismatch cluster_id=%s", getattr(cluster, "id", None))
        return False

    # NOTE: Label check removed to fix chicken-and-egg problem where
    # suggestions require labeled clusters but initial clustering produces
    # unlabeled clusters. See docs/tasks/4.0/4.11.1/pipeline-analysis-2026-01-26.md
    return True
