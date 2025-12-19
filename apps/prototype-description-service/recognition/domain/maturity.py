"""Domain types for cluster maturity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ClusterMaturityLevel(IntEnum):
    """Maturity level affecting adaptive threshold adjustments."""

    COLD = 0  # identity_count=1, not confirmed
    NASCENT = 1  # identity_count 2-5, not confirmed
    CONFIRMED = 2  # user_confirmed=True
    MATURE = 3  # identity_count>10 AND representative_count>=3


@dataclass(frozen=True, slots=True)
class ClusterMaturityInfo:
    """Maturity information for a cluster."""

    level: ClusterMaturityLevel
    identity_count: int
    representative_count: int
    user_confirmed: bool
    threshold_adjustment: float  # Delta to apply


def compute_maturity_level(
    *,
    identity_count: int,
    representative_count: int,
    user_confirmed: bool,
) -> ClusterMaturityLevel:
    """Compute maturity level from cluster metrics.

    Args:
        identity_count: Number of members in the cluster.
        representative_count: Number of representatives.
        user_confirmed: Whether user has confirmed the cluster.

    Returns:
        ClusterMaturityLevel enum value.
    """
    if user_confirmed:
        return ClusterMaturityLevel.CONFIRMED

    if identity_count > 10 and representative_count >= 3:
        return ClusterMaturityLevel.MATURE

    if identity_count > 1:
        return ClusterMaturityLevel.NASCENT

    return ClusterMaturityLevel.COLD


def compute_maturity_adjustment(level: ClusterMaturityLevel) -> float:
    """Return threshold adjustment for a maturity level.

    Args:
        level: Cluster maturity level.

    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    match level:
        case ClusterMaturityLevel.COLD:
            return 0.05
        case ClusterMaturityLevel.NASCENT:
            return 0.02
        case ClusterMaturityLevel.CONFIRMED:
            return -0.02
        case ClusterMaturityLevel.MATURE:
            return -0.03
