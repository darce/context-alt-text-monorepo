"""Tests for MaturityCheck ensuring clusters are sufficiently representative."""

from __future__ import annotations

import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.maturity import MaturityCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


class FakeClusterRepository:
    """Stub repository returning configurable representative counts."""

    def __init__(self, rep_counts: dict[str, int]) -> None:
        self._rep_counts = rep_counts

    async def get_representative_count(self, cluster_id: str) -> int:
        return self._rep_counts.get(cluster_id, 0)

    # Unused abstract methods
    async def get_unclustered(self, tenant_id: str):  # pragma: no cover
        raise NotImplementedError

    async def get_all_representatives(self, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def get_member_embeddings(self, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def save_cluster(self, cluster):  # pragma: no cover
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def add_representative(self, representative):  # pragma: no cover
        raise NotImplementedError


def make_settings(min_reps: int = 2) -> ClusteringSettings:
    """Create settings with adjustable maturity threshold."""
    return ClusteringSettings(
        similarity_threshold=0.75,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=min_reps,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=None,
    )


def make_candidate(cluster_id: str | None = None) -> AssignmentCandidate:
    """Create a simple candidate for maturity tests."""
    identity = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=[],
        confidence=0.9,
        bbox_width=10,
        bbox_height=12,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=[],
        cluster_id=cluster_id or str(generate_id()),
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.8,
    )


@pytest.mark.asyncio
async def test_maturity_suggests_when_below_threshold() -> None:
    """Should return fatal suggestion when cluster has too few representatives."""
    cluster_id = str(generate_id())
    check = MaturityCheck(
        settings=make_settings(min_reps=2),
        cluster_repository=FakeClusterRepository({cluster_id: 1}),
    )

    result = await check.evaluate(make_candidate(cluster_id))

    assert result.passed is False
    assert result.is_fatal is True
    assert result.should_reject is False
    assert result.metadata == {"representative_count": 1}


@pytest.mark.asyncio
async def test_maturity_passes_when_threshold_met() -> None:
    """Should pass once cluster has enough representatives."""
    cluster_id = str(generate_id())
    check = MaturityCheck(
        settings=make_settings(min_reps=2),
        cluster_repository=FakeClusterRepository({cluster_id: 3}),
    )

    result = await check.evaluate(make_candidate(cluster_id))

    assert result.passed is True
    assert result.metadata == {"representative_count": 3}


def test_maturity_disabled_when_min_reps_nonpositive() -> None:
    """is_enabled should return False when maturity guard is configured off."""
    check = MaturityCheck(
        settings=make_settings(min_reps=0),
        cluster_repository=FakeClusterRepository({}),
    )

    assert check.is_enabled() is False
