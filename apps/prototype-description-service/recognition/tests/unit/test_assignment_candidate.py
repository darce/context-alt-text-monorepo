"""Unit tests for AssignmentCandidate dataclass."""

from __future__ import annotations

import numpy as np

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def test_candidate_stores_identity_and_metadata() -> None:
    """Candidate should preserve the identity, vector, cluster, method, and similarity."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=np.ones(4, dtype=np.float32),
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    vector = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
    cluster_id = str(generate_id())

    candidate = AssignmentCandidate(
        identity=identity,
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.87,
    )

    assert candidate.identity is identity
    assert candidate.identity_vector is vector
    assert candidate.cluster_id == cluster_id
    assert candidate.discovery_method is DiscoveryMethod.REPRESENTATIVE
    assert candidate.discovery_similarity == 0.87
