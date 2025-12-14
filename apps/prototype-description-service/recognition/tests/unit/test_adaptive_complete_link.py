from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate
from recognition.application.assignment.checks.complete_link import CompleteLinkCheck
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.repositories import ClusterRepository


@pytest.fixture
def settings():
    # Use strict base thresholds to force failure without adaptive logic
    # Base: min=0.80, avg=0.85
    # Adaptive: min=0.75, avg=0.80 (with relaxation=0.05)
    return ClusteringSettings(
        complete_link_min_floor=0.80,
        complete_link_avg_threshold=0.85,
        adaptive_threshold_maturity_point=5,
        adaptive_relaxation_amount=0.05,
    )


@pytest.fixture
def repository():
    return AsyncMock(spec=ClusterRepository)


@pytest.mark.asyncio
async def test_adaptive_relaxation_applied_when_mature(settings, repository):
    """Verify that thresholds are relaxed when the cluster is mature."""
    check = CompleteLinkCheck(settings, repository)

    # Mock a mature cluster (5 reps)
    # Representatives that yield similarity ~0.78 (fail base 0.80, pass adaptive 0.75)
    # candidate vector [1, 0], rep vectors ~[0.99, 0.1]? No, simpler:
    # dot product = 0.78.
    # Let's mock the get_all_representatives to return simplified vectors if possible,
    # or just rely on the dot product math.
    # The check computes dot products of normalized vectors.

    # Let's say candidate is [1.0, 0.0]
    # We need 5 reps.
    # Reps should give min_sim = 0.78, avg_sim = 0.82
    # Base requires min=0.80 (FAIL), avg=0.85 (FAIL)
    # Adaptive requires min=0.75 (PASS), avg=0.80 (PASS)

    candidate_vec = np.array([1.0, 0.0], dtype=np.float32)

    # cos(35 deg) ~= 0.819
    # [0.82, 0.57] -> norm=1 -> dot([1,0], [0.82, .57]) = 0.82
    rep_vec = np.array([0.82, 0.57], dtype=np.float32)  # Normalized approx

    # 5 identical reps for simplicity
    repository.get_all_representatives.return_value = [rep_vec] * 5

    candidate = Mock(spec=AssignmentCandidate)
    candidate.cluster_id = "test-cluster"
    candidate.identity_vector = candidate_vec
    candidate.discovery_similarity = 0.82

    result = await check.evaluate(candidate)

    assert result.passed is True
    assert result.metadata is not None
    assert result.metadata.get("adaptive_relaxation_applied") is True
    assert result.metadata.get("relaxation_amount") == 0.05
    assert result.metadata["min_similarity"] >= 0.75


@pytest.mark.asyncio
async def test_adaptive_relaxation_not_applied_when_immature(settings, repository):
    """Verify that thresholds are NOT relaxed when the cluster is immature."""
    check = CompleteLinkCheck(settings, repository)

    # Mock an immature cluster (4 reps < 5)
    # Same vectors as above (0.78 similarity)
    # Should FAIL because base threshold is 0.80

    candidate_vec = np.array([1.0, 0.0], dtype=np.float32)
    rep_vec = np.array([0.78, 0.62], dtype=np.float32)

    repository.get_all_representatives.return_value = [rep_vec] * 4  # Only 4 reps

    candidate = Mock(spec=AssignmentCandidate)
    candidate.cluster_id = "test-cluster"
    candidate.identity_vector = candidate_vec
    candidate.discovery_similarity = 0.78

    result = await check.evaluate(candidate)

    assert result.passed is False
    assert result.is_fatal is True
    assert result.metadata is None or result.metadata.get("adaptive_relaxation_applied") is None
