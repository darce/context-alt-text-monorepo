"""Eligibility checks for suggestion targets."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class EligibleCluster(Protocol):
    """Minimum cluster shape required by suggestion eligibility checks."""

    id: str | None
    tenant_id: str
    user_confirmed: bool
    label: str | None


def is_eligible_cluster(cluster: EligibleCluster, tenant_id: str) -> bool:
    """Return True if a cluster can be surfaced as a suggestion target.

    Eligibility requirements (v4.12.0 - confirmed-only):
    1. Cluster must match the specified tenant_id (case-insensitive)
    2. Cluster must be user_confirmed = True
    3. Cluster must have a human-assigned label (not None, not "cluster-*")

    Args:
        cluster: Cluster-like object exposing tenant_id, user_confirmed, label, and id.
        tenant_id: Tenant ID to match against.

    Returns:
        True if cluster is eligible for suggestions; False otherwise.
    """
    if tenant_id and str(cluster.tenant_id).lower() != tenant_id.lower():
        logger.info("[suggestions] Skipping suggestion: tenant mismatch cluster_id=%s", cluster.id)
        return False

    # Must be user-confirmed
    if not cluster.user_confirmed:
        return False

    # Must have a label
    label = cluster.label
    if not label:
        return False

    # Must not be an auto-generated "cluster-*" label
    return not str(label).startswith("cluster-")
