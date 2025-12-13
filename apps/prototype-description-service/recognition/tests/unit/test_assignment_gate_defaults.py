"""Integration-style tests for AssignmentGate default checks."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentOutcome
from recognition.application.assignment.gate import AssignmentGate
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository
from recognition.shared.ids import generate_id


class GateRepoStub(ClusterRepository):
    """Repository stub providing data for all default checks."""

    def __init__(self, reps: dict[str, list[np.ndarray]], members: dict[str, list[np.ndarray]]) -> None:
        self._reps = reps
        self._members = members

    async def get_by_id(self, cluster_id: str):
        return None

    async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0):
        return []

    async def save(self, cluster):
        return cluster

    async def update(self, cluster):
        return cluster

    async def delete(self, cluster_id: str) -> None:
        return None

    async def refresh_centroids_view(self) -> None:
        pass

    async def get_unclustered(self, tenant_id: str):
        return []

    async def get_representative_count(self, cluster_id: str) -> int:
        return len(self._reps.get(cluster_id, []))

    async def get_all_representatives(self, cluster_id: str) -> list[np.ndarray]:
        return self._reps.get(cluster_id, [])

    async def get_member_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        return self._members.get(cluster_id, [])

    async def save_cluster(self, cluster):
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity, cluster_id: str):
        raise NotImplementedError

    async def add_representative(self, representative):
        raise NotImplementedError

    async def count_labeled(self) -> int:
        return 10  # Return a mature count so adaptive threshold is relaxed


def make_settings() -> ClusteringSettings:
    """Create clustering settings enabling all default checks."""
    return ClusteringSettings(
        similarity_threshold=0.75,
        complete_link_min_floor=0.7,
        complete_link_avg_threshold=0.8,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.7,
        member_validation_avg_threshold=0.8,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_candidate(vector: np.ndarray, cluster_id: str, similarity: float) -> AssignmentCandidate:
    """Create an assignment candidate."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vector,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=similarity,
    )


def normalize(vector: np.ndarray) -> np.ndarray:
    """Return a normalized copy of the vector."""
    norm = float(np.linalg.norm(vector))
    return vector.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_default_checks_accept_when_all_pass() -> None:
    """Default gate should accept when every check passes."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    reps = {cluster_id: [base, normalize(base + np.array([0.0, 0.1, 0.0]))]}
    members = {cluster_id: [normalize(base + np.array([0.05, 0.0, 0.0]))]}

    gate = AssignmentGate(settings=make_settings(), cluster_repository=GateRepoStub(reps, members))
    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.95))

    assert decision.outcome is AssignmentOutcome.ACCEPT
    assert decision.checks_failed == []
    assert set(decision.checks_passed) == {"maturity", "complete_link", "member_distribution", "confidence"}


@pytest.mark.asyncio
async def test_default_checks_suggest_on_low_confidence() -> None:
    """Default gate should suggest when confidence check fails after others pass."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    reps = {cluster_id: [base, normalize(base + np.array([0.0, 0.1, 0.0]))]}
    members = {cluster_id: [normalize(base + np.array([0.05, 0.0, 0.0]))]}

    gate = AssignmentGate(settings=make_settings(), cluster_repository=GateRepoStub(reps, members))
    decision = await gate.evaluate(make_candidate(normalize(base + np.array([0.05, 0.02, 0.0])), cluster_id, 0.5))

    assert decision.outcome is AssignmentOutcome.SUGGEST
    assert "confidence" in decision.checks_failed
    assert "maturity" in decision.checks_passed
    assert "complete_link" in decision.checks_passed
    assert "member_distribution" in decision.checks_passed
