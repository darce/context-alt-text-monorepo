"""Eligibility checks for suggestion targets."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def is_eligible_cluster(cluster: object, tenant_id: str) -> bool:
    """Return True if a cluster can be surfaced as a suggestion target.

    Eligible clusters must have a meaningful label (user or auto-assigned).
    """
    if tenant_id and getattr(cluster, "tenant_id", "").lower() != tenant_id.lower():
        logger.info("[suggestions] Skipping suggestion: tenant mismatch cluster_id=%s", getattr(cluster, "id", None))
        return False

    label = getattr(cluster, "label", None)
    if not label or str(label).startswith("cluster-"):
        logger.info(
            "[suggestions] Skipping suggestion: cluster missing meaningful label cluster_id=%s",
            getattr(cluster, "id", None),
        )
        return False

    return True
