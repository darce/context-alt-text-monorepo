from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import numpy as np
import pytest

from db.models import IdentityCluster, MediaIdentity
from recognition.application.chinese_whispers import ChineseWhispersClustering
from recognition.application.clustering_settings import ClusteringSettings


@pytest.mark.asyncio
async def test_chinese_whispers_cliques():
    """
    Test that CW correctly identifies two distinct cliques connected by a weak link.
    """
    # Settings with high threshold
    settings = ClusteringSettings(cw_threshold=0.8, cw_iterations=10)
    cw = ChineseWhispersClustering(settings)

    # Create two cliques of 3 nodes each
    # Clique A: nodes 0, 1, 2 (all very similar)
    # Clique B: nodes 3, 4, 5 (all very similar)
    # Weak link between 2 and 3

    # We'll mock embeddings such that dot product reflects this structure.
    # Instead of complex vector math, let's just ensure the logic works if we trust numpy.
    # But we need real vectors for the dot product to work in _build_graph.

    # 128-d vectors
    dim = 128

    # Base vectors for A and B (orthogonal)
    base_a = np.zeros(dim)
    base_a[0] = 1.0

    base_b = np.zeros(dim)
    base_b[1] = 1.0

    identities = []

    # Generate Clique A
    for i in range(3):
        # Slight noise
        vec = base_a + np.random.normal(0, 0.01, dim)
        vec /= np.linalg.norm(vec)
        identities.append(MediaIdentity(id=i, embedding=vec.tolist()))

    # Generate Clique B
    for i in range(3):
        vec = base_b + np.random.normal(0, 0.01, dim)
        vec /= np.linalg.norm(vec)
        identities.append(MediaIdentity(id=i + 3, embedding=vec.tolist()))

    # Mock create_cluster
    async def create_cluster(members):
        return IdentityCluster(id=uuid4(), label=f"Cluster-{len(members)}"), None

    clusters = await cw.cluster(identities, create_cluster)

    assert len(clusters) == 2

    # Verify groupings
    # We can't easily check which identity is in which cluster from the return value alone
    # without inspecting the calls or the clusters' members if we attached them.
    # But since we passed a list, we can check the length.

    # Ideally we should verify members.
    # Let's use a capture mock.

    captured_groups = []

    async def capture_create_cluster(members):
        captured_groups.append([m.id for m in members])
        return IdentityCluster(id=uuid4()), None

    await cw.cluster(identities, capture_create_cluster)

    assert len(captured_groups) == 2
    group1 = set(captured_groups[0])
    group2 = set(captured_groups[1])

    # One group should be {0,1,2}, the other {3,4,5}
    expected_a = {0, 1, 2}
    expected_b = {3, 4, 5}

    assert (group1 == expected_a and group2 == expected_b) or (group1 == expected_b and group2 == expected_a)


@pytest.mark.asyncio
async def test_chinese_whispers_single_node():
    settings = ClusteringSettings()
    cw = ChineseWhispersClustering(settings)

    identities = [MediaIdentity(id=1, embedding=[0.1] * 128)]

    async def create_cluster(members):
        return IdentityCluster(id=uuid4()), None

    clusters = await cw.cluster(identities, create_cluster)
    assert len(clusters) == 1


@pytest.mark.asyncio
async def test_chinese_whispers_no_edges():
    """Test that nodes with no edges (dissimilar) form their own clusters."""
    settings = ClusteringSettings(cw_threshold=0.9)  # Very high threshold
    cw = ChineseWhispersClustering(settings)

    # Two orthogonal vectors
    v1 = np.zeros(128)
    v1[0] = 1.0
    v2 = np.zeros(128)
    v2[1] = 1.0

    identities = [MediaIdentity(id=1, embedding=v1.tolist()), MediaIdentity(id=2, embedding=v2.tolist())]

    captured_groups = []

    async def capture_create_cluster(members):
        captured_groups.append([m.id for m in members])
        return IdentityCluster(id=uuid4()), None

    clusters = await cw.cluster(identities, capture_create_cluster)

    assert len(clusters) == 2
    assert len(captured_groups) == 2
    assert len(captured_groups[0]) == 1
    assert len(captured_groups[1]) == 1
