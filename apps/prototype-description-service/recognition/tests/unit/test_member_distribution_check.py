"""Tests for MemberDistributionCheck alignment with cluster members."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.member_distribution import MemberDistributionCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


class FakeClusterRepository:
    """Stub repository returning predefined member embeddings."""

    def __init__(self, members: dict[str, list[np.ndarray]]) -> None:
        self._members = members

    async def get_member_embeddings(self, cluster_id: str) -> list[np.ndarray]:
        return self._members.get(cluster_id, [])

    # Unused abstract methods
    async def get_unclustered(self, tenant_id: str):  # pragma: no cover
        raise NotImplementedError

    async def get_representative_count(self, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def get_all_representatives(self, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def save_cluster(self, cluster):  # pragma: no cover
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def add_representative(self, representative):  # pragma: no cover
        raise NotImplementedError


def make_settings() -> ClusteringSettings:
    """Settings with member distribution thresholds enabled."""
    return ClusteringSettings(
        similarity_threshold=0.75,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_candidate(vector: np.ndarray, cluster_id: str | None = None) -> AssignmentCandidate:
    """Create a candidate with supplied embedding and cluster."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vector,
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=vector,
        cluster_id=cluster_id or str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.8,
    )


def normalize(vec: np.ndarray) -> np.ndarray:
    """Return unit-normalized vector."""
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_member_distribution_rejects_when_avg_below_threshold() -> None:
    """Should reject when candidate does not align with member distribution."""
    cluster_id = str(generate_id())
    members = {
        cluster_id: [
            normalize(np.array([1.0, 0.0, 0.0])),
            normalize(np.array([1.0, 0.1, 0.0])),
        ],
    }
    candidate = make_candidate(normalize(np.array([0.2, 1.0, 0.0])), cluster_id=cluster_id)
    check = MemberDistributionCheck(settings=make_settings(), cluster_repository=FakeClusterRepository(members))

    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.is_fatal is True
    assert result.should_reject is True
    assert result.reason is not None
    assert result.metadata is not None
    assert result.metadata["avg_similarity"] < 0.85


@pytest.mark.asyncio
async def test_member_distribution_passes_when_thresholds_met() -> None:
    """Should pass when candidate similarity to members meets thresholds."""
    cluster_id = str(generate_id())
    members = {
        cluster_id: [
            normalize(np.array([1.0, 0.0, 0.0])),
            normalize(np.array([0.9, 0.1, 0.0])),
        ],
    }
    candidate = make_candidate(normalize(np.array([0.95, 0.05, 0.0])), cluster_id=cluster_id)
    check = MemberDistributionCheck(settings=make_settings(), cluster_repository=FakeClusterRepository(members))

    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.is_fatal is False
    assert result.metadata is not None
    assert result.metadata["min_similarity"] >= 0.8 - 1e-3
    assert result.metadata["avg_similarity"] >= 0.85 - 1e-3


@pytest.mark.asyncio
async def test_member_distribution_skips_when_no_members() -> None:
    """Should pass with sentinel values when cluster has no members."""
    cluster_id = str(generate_id())
    candidate = make_candidate(normalize(np.array([1.0, 0.0, 0.0])), cluster_id=cluster_id)
    check = MemberDistributionCheck(settings=make_settings(), cluster_repository=FakeClusterRepository({}))

    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.metadata is not None
    assert result.metadata["member_count"] == 0
    assert result.metadata["min_similarity"] == 1.0
    assert result.metadata["avg_similarity"] == 1.0


def test_member_distribution_disabled_when_thresholds_zero() -> None:
    """is_enabled should return False when thresholds are disabled."""
    settings = make_settings()
    settings.member_validation_min_floor = 0.0
    settings.member_validation_avg_threshold = 0.0
    check = MemberDistributionCheck(settings=settings, cluster_repository=FakeClusterRepository({}))

    assert check.is_enabled() is False
