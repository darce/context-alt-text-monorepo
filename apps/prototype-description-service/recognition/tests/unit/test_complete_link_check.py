"""Tests for CompleteLinkCheck similarity validation."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.checks.complete_link import CompleteLinkCheck
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


class FakeClusterRepository:
    """In-memory repository stub for representative lookups."""

    def __init__(self, representatives: dict[str, list[np.ndarray]]) -> None:
        self._representatives = representatives

    async def get_all_representatives(self, cluster_id: str) -> list[np.ndarray]:
        return self._representatives.get(cluster_id, [])

    async def get_representative_count(self, cluster_id: str) -> int:  # pragma: no cover - convenience
        return len(self._representatives.get(cluster_id, []))

    async def get_member_embeddings(self, cluster_id: str):  # pragma: no cover - not used here
        return []

    # Unused abstract methods for interface compatibility
    async def get_unclustered(self, tenant_id: str):  # pragma: no cover - not used
        raise NotImplementedError

    async def save_cluster(self, cluster):  # pragma: no cover - not used
        raise NotImplementedError

    async def assign_identity_to_cluster(self, identity: MediaIdentity, cluster_id: str):  # pragma: no cover
        raise NotImplementedError

    async def add_representative(self, representative):  # pragma: no cover - not used
        raise NotImplementedError


def make_candidate(vector: np.ndarray, cluster_id: str | None = None) -> AssignmentCandidate:
    """Create a candidate with the provided vector and cluster."""
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


def make_settings() -> ClusteringSettings:
    """Create clustering settings with complete-link enabled."""
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


def normalize(vector: np.ndarray) -> np.ndarray:
    """Return a unit-normalized copy of the vector."""
    norm = float(np.linalg.norm(vector))
    return vector.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_complete_link_passes_when_all_reps_similar() -> None:
    """Check should pass when candidate matches all representatives above thresholds."""
    cluster_id = str(generate_id())
    base = normalize(np.array([1.0, 0.0, 0.0]))
    rep1 = normalize(base + np.array([0.01, 0.0, 0.0]))
    rep2 = normalize(base + np.array([0.0, 0.01, 0.0]))
    reps = {cluster_id: [rep1, rep2]}

    candidate = make_candidate(normalize(base + np.array([0.02, 0.01, 0.0])), cluster_id=cluster_id)
    check = CompleteLinkCheck(settings=make_settings(), cluster_repository=FakeClusterRepository(reps))

    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.is_fatal is False
    assert result.metadata is not None
    assert result.metadata["min_similarity"] >= 0.75 - 1e-3
    assert result.metadata["avg_similarity"] >= 0.85 - 1e-3


@pytest.mark.asyncio
async def test_complete_link_suggests_when_min_similarity_falls_below_floor() -> None:
    """Check should fail fatally (suggest) when any representative is too dissimilar."""
    cluster_id = str(generate_id())
    rep_front = normalize(np.array([1.0, 0.0, 0.0]))
    rep_side = normalize(np.array([0.0, 1.0, 0.0]))
    reps = {cluster_id: [rep_front, rep_side]}

    candidate = make_candidate(normalize(np.array([1.0, 0.0, 0.2])), cluster_id=cluster_id)
    check = CompleteLinkCheck(settings=make_settings(), cluster_repository=FakeClusterRepository(reps))

    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.is_fatal is True
    assert result.should_reject is False
    assert result.reason is not None
    assert result.metadata is not None
    assert result.metadata["min_similarity"] < 0.75


@pytest.mark.asyncio
async def test_complete_link_skips_when_insufficient_representatives() -> None:
    """Check should pass without enforcing thresholds when fewer than 2 representatives exist."""
    cluster_id = str(generate_id())
    reps = {cluster_id: [normalize(np.array([1.0, 0.0, 0.0]))]}
    candidate = make_candidate(normalize(np.array([1.0, 0.0, 0.0])), cluster_id=cluster_id)
    check = CompleteLinkCheck(settings=make_settings(), cluster_repository=FakeClusterRepository(reps))

    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.is_fatal is False
    assert result.metadata is not None
    assert result.metadata["min_similarity"] == 1.0
    assert result.metadata["avg_similarity"] == 1.0


def test_complete_link_disabled_when_thresholds_missing() -> None:
    """is_enabled should return False when thresholds are non-positive."""
    settings = make_settings()
    settings.complete_link_min_floor = 0.0
    settings.complete_link_avg_threshold = 0.0
    check = CompleteLinkCheck(settings=settings, cluster_repository=FakeClusterRepository({}))

    assert check.is_enabled() is False
