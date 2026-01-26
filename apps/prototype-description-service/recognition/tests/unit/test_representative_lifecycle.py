"""Domain completeness tests for representative lifecycle (Task 75vb)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.assignment.decision import AssignmentDecision, AssignmentOutcome
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, MemberRepository
from recognition.domain.representative import ClusterRepresentative


@pytest.fixture
def mock_cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_representative_count.return_value = 0
    repo.get_all_representatives.return_value = []
    repo.get_curriculum_t.return_value = 0.5
    return repo


@pytest.fixture
def mock_member_repo() -> AsyncMock:
    return AsyncMock(spec=MemberRepository)


@pytest.fixture
def settings() -> ClusteringSettings:
    return ClusteringSettings(
        max_representatives_per_cluster=5,
        representative_diversity_threshold=0.9,
    )


@pytest.fixture
def writer(
    settings: ClusteringSettings,
    mock_cluster_repo: AsyncMock,
    mock_member_repo: AsyncMock,
) -> AssignmentWriter:
    return AssignmentWriter(settings, mock_cluster_repo, mock_member_repo)


def _make_candidate(cluster_id: str, identity_id: str = "id-1") -> AssignmentCandidate:
    vector = _unit_vector(0)
    return AssignmentCandidate(
        identity=MediaIdentity(
            id=identity_id,
            tenant_id="tenant-1",
            media_id="media-1",
            embedding=vector,
            confidence=0.95,
            bbox_width=100,
            bbox_height=100,
        ),
        identity_vector=vector,
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.92,
    )


def _unit_vector(index: int, length: int = 512) -> np.ndarray:
    vec = np.zeros(length, dtype=np.float32)
    vec[index] = 1.0
    return vec


@pytest.mark.asyncio
async def test_accept_evaluates_candidacy(
    writer: AssignmentWriter,
    mock_cluster_repo: AsyncMock,
) -> None:
    """Test that an ACCEPT decision triggers representative evaluation."""
    cluster_id = str(uuid.uuid4())
    candidate = _make_candidate(cluster_id)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["all"],
        checks_failed=[],
    )

    # Setup: Cluster allows new reps (count < max)
    mock_cluster_repo.get_representative_count.return_value = 1
    mock_cluster_repo.get_all_representatives.return_value = [
        # One existing rep with different embedding
        np.zeros(512, dtype=np.float32)
    ]

    await writer.persist_assignment(decision)

    # Should get all reps to check count and diversity
    mock_cluster_repo.get_all_representatives.assert_awaited_with(cluster_id)

    # Should add as representative because count < max and diversity is good
    mock_cluster_repo.add_representative.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_skips_candidacy(
    writer: AssignmentWriter,
    mock_cluster_repo: AsyncMock,
) -> None:
    """Test that a REJECT decision is rejected by persist_assignment."""
    cluster_id = str(uuid.uuid4())
    candidate = _make_candidate(cluster_id)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.REJECT,
        candidate=candidate,
        checks_passed=[],
        checks_failed=["check"],
    )

    # persist_assignment only accepts ACCEPT decisions
    with pytest.raises(ValueError, match="Cannot persist non-ACCEPT decision"):
        await writer.persist_assignment(decision)

    # Should NOT check rep count or add rep
    mock_cluster_repo.get_all_representatives.assert_not_awaited()
    mock_cluster_repo.add_representative.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_rep_triggers_centroid(
    writer: AssignmentWriter,
    mock_cluster_repo: AsyncMock,
) -> None:
    """Test that adding a new representative triggers centroid recomputation."""
    cluster_id = str(uuid.uuid4())
    val = _unit_vector(1)
    cluster = IdentityCluster(
        id=cluster_id,
        tenant_id="tenant-1",
        label="Cluster 1",
        centroid=val,
        created_at=None,
        is_labeled=False,
        identity_count=1,
    )
    mock_cluster_repo.get_by_id.return_value = cluster

    candidate = _make_candidate(cluster_id)
    decision = AssignmentDecision(
        outcome=AssignmentOutcome.ACCEPT,
        candidate=candidate,
        checks_passed=["all"],
        checks_failed=[],
    )

    # Setup: Allow new rep (count=0 means first rep will be added)
    mock_cluster_repo.get_representative_count.return_value = 0
    # First call returns [] to allow adding rep, subsequent calls return the new rep
    mock_cluster_repo.get_all_representatives.side_effect = [
        [],  # First call during _should_add_representative - empty, allows adding
        [candidate.identity_vector],  # Second call during recompute_centroid - includes new rep
    ]

    await writer.persist_assignment(decision)

    # Should update cluster with new centroid
    mock_cluster_repo.update.assert_awaited_once()
