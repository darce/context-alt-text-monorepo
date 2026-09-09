"""
Cluster domain model that groups related media identities.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from recognition.domain.representative import ClusterRepresentative


class ReservedClusterLabelError(ValueError):
    """Raised when an operator attempts to use a machine-reserved cluster label."""

    def __init__(self, label: str | None) -> None:
        super().__init__(f"Cluster label uses a reserved machine-label shape: {label!r}")
        self.label = label


def is_reserved_label_shape(label: str | None) -> bool:
    """Return whether a label starts with the reserved ``cluster-``/``cluster_`` shape."""
    if label is None:
        return False
    return label.strip().lower().startswith(("cluster-", "cluster_"))


@dataclass
class IdentityCluster:
    """Represents a cluster of identities that belong to the same subject."""

    tenant_id: str
    is_labeled: bool
    identity_count: int
    label: str | None = None
    id: str | None = None
    representative_identity_id: str | None = None
    created_at: datetime | None = None
    clustering_algorithm: str = "graph"
    user_confirmed: bool = False
    dismissed_at: datetime | None = None
    representatives: Sequence[ClusterRepresentative] | None = None
    centroid: Any | None = None
    # FIR23-01: majority embedding_model of loaded representatives. None when
    # unresolved (legacy unstamped rows). Appended last for positional safety.
    embedding_model: str | None = None

    @property
    def is_auto_label(self) -> bool:
        """Returns True if the label was automatically generated (not user confirmed)."""
        return not self.user_confirmed
