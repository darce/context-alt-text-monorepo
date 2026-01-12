"""Graph discovery core interfaces and result types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.domain.identity import MediaIdentity


@dataclass
class AnchorIdentity:
    """Lightweight wrapper for anchor nodes."""

    id: str
    cluster_id: str
    confidence: float = 1.0


class GraphDiscoveryResult:
    """Result of graph discovery including matched candidates and new clusters."""

    def __init__(
        self,
        candidates: list[AssignmentCandidate],
        new_clusters: list[tuple[list[MediaIdentity], list[float]]],
    ) -> None:
        self.candidates = candidates
        self.new_clusters = new_clusters


class GraphAlgorithm(ABC):
    """Interface for graph clustering algorithms."""

    @abstractmethod
    def cluster(
        self,
        embeddings: Sequence[np.ndarray],
        identities: Sequence[MediaIdentity] | None = None,
    ) -> list[int]:
        """Cluster embeddings and return integer labels."""
        ...
