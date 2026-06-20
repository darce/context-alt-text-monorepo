"""Unit tests for CentroidMaintainer (Slice 9 increment 2: extracted from AssignmentWriter)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.persistence.centroid_maintainer import CentroidMaintainer
from recognition.application.settings.clustering import ClusteringSettings
from recognition.domain.repositories import ClusterRepository, MemberRepository


def _rep(vec: np.ndarray) -> object:
    return type("Rep", (), {"embedding": vec})()


@pytest.fixture
def cluster_repo() -> AsyncMock:
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_all_representatives.return_value = []
    return repo


@pytest.mark.asyncio
async def test_recompute_centroid_returns_unit_normalized_mean(cluster_repo: AsyncMock) -> None:
    cluster_repo.get_all_representatives.return_value = [
        _rep(np.array([3.0, 0.0, 0.0], dtype=np.float32)),
        _rep(np.array([0.0, 4.0, 0.0], dtype=np.float32)),
    ]

    centroid = await CentroidMaintainer(cluster_repo).recompute_centroid("c1")

    assert centroid is not None
    # mean of the two orthogonal vectors, then L2-normalized to a unit vector.
    assert float(np.linalg.norm(centroid)) == pytest.approx(1.0, abs=1e-6)
    assert centroid[:2] == pytest.approx([0.6, 0.8], abs=1e-6)


@pytest.mark.asyncio
async def test_recompute_centroid_returns_none_without_representatives(cluster_repo: AsyncMock) -> None:
    cluster_repo.get_all_representatives.return_value = []

    assert await CentroidMaintainer(cluster_repo).recompute_centroid("c1") is None


@pytest.mark.asyncio
async def test_assignment_writer_delegates_to_centroid_maintainer() -> None:
    """AssignmentWriter preserves its public centroid API by delegating to CentroidMaintainer."""
    repo = AsyncMock(spec=ClusterRepository)
    repo.get_all_representatives.return_value = [_rep(np.ones(512, dtype=np.float32))]
    writer = AssignmentWriter(ClusteringSettings(), repo, AsyncMock(spec=MemberRepository))

    assert isinstance(writer._centroids, CentroidMaintainer)
    assert writer._centroids._clusters is repo

    centroid = await writer.recompute_centroid("c1")
    assert centroid is not None
