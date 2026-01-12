"""Split plan types for cluster splitting."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SplitStrategy(str, Enum):
    """Strategy used to split a cluster."""

    HIERARCHICAL = "hierarchical"
    ANCHOR_FORCED = "anchor_forced"


class SplitScope(str, Enum):
    """Scope hint for split operations."""

    CLUSTER = "cluster"
    MEDIA = "media"
    ANCHOR = "anchor"


@dataclass(frozen=True)
class SplitPlan:
    """Plan describing how a user-initiated split should be executed."""

    cluster_id: str
    n_clusters: int
    anchor_identity_id: str | None
    strategy: SplitStrategy
    split_mode: str | None = None
