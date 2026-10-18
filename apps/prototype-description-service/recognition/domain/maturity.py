"""Domain types for cluster maturity."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from recognition.application.settings.clustering import MaturitySettings


class ClusterMaturityLevel(IntEnum):
    """Maturity level affecting adaptive threshold adjustments."""

    COLD = 0  # Below nascent thresholds, not confirmed
    NASCENT = 1  # Meets nascent thresholds, not confirmed
    CONFIRMED = 2  # user_confirmed=True
    MATURE = 3  # Meets mature thresholds for members + representatives


@dataclass(frozen=True, slots=True)
class ClusterMaturityInfo:
    """Maturity information for a cluster."""

    level: ClusterMaturityLevel
    identity_count: int
    representative_count: int
    user_confirmed: bool
    threshold_adjustment: float  # Delta to apply
    pose_bucket_coverage: float = 0.0  # Fraction of pose buckets filled (0-1)


def compute_maturity_level(
    *,
    identity_count: int,
    representative_count: int,
    user_confirmed: bool,
    settings: MaturitySettings,
    pose_bucket_coverage: float = 0.0,
) -> ClusterMaturityLevel:
    """Compute maturity level from cluster metrics.

    A cluster is considered MATURE only when it has sufficient members,
    representatives, AND pose diversity. This prevents clusters with many
    same-angle faces from being overconfident in matching.

    Args:
        identity_count: Number of members in the cluster.
        representative_count: Number of representatives.
        user_confirmed: Whether user has confirmed the cluster.
        settings: Maturity settings.
        pose_bucket_coverage: Fraction of pose buckets filled (0-1).

    Returns:
        ClusterMaturityLevel enum value.
    """
    if user_confirmed:
        return ClusterMaturityLevel.CONFIRMED

    # MATURE requires: enough members + enough reps + pose diversity
    if (
        identity_count >= settings.mature_min_members
        and representative_count >= settings.mature_min_representatives
        and pose_bucket_coverage >= settings.mature_min_pose_coverage
    ):
        return ClusterMaturityLevel.MATURE

    if identity_count >= settings.nascent_min_members:
        return ClusterMaturityLevel.NASCENT

    return ClusterMaturityLevel.COLD


def compute_maturity_adjustment(
    level: ClusterMaturityLevel,
    settings: MaturitySettings,
) -> float:
    """Return threshold adjustment for a maturity level.

    Args:
        level: Cluster maturity level.
        settings: Maturity settings.

    Returns:
        Float adjustment (positive = stricter, negative = more lenient).
    """
    match level:
        case ClusterMaturityLevel.COLD:
            return settings.cold_adjustment
        case ClusterMaturityLevel.NASCENT:
            return settings.nascent_adjustment
        case ClusterMaturityLevel.CONFIRMED:
            return settings.confirmed_adjustment
        case ClusterMaturityLevel.MATURE:
            return settings.mature_adjustment
