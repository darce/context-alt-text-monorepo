"""
Assignment candidate model produced by discovery algorithms.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from recognition.domain.identity import MediaIdentity


class DiscoveryMethod(Enum):
    """Origin of an assignment candidate."""

    REPRESENTATIVE = "representative"
    CENTROID = "centroid"
    GRAPH = "graph"


@dataclass
class AssignmentCandidate:
    """Proposed identity-to-cluster assignment awaiting validation."""

    identity: MediaIdentity
    identity_vector: np.ndarray
    cluster_id: str
    discovery_method: DiscoveryMethod
    discovery_similarity: float
