"""Unit tests for HAC refinement pipeline.

Tests the constrained hierarchical agglomerative clustering pass that runs
after HDBSCAN to merge remaining singletons per Apple's two-pass strategy.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from recognition.application.clustering.constrained_hac import ConstrainedHAC
from recognition.application.orchestration.clustering.discovery_pipeline import (
    run_hac_refinement,
    run_singleton_hac_refinement,
)
from recognition.application.settings import HACSettings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity

if TYPE_CHECKING:
    from recognition.domain.repositories import ConstrainedHACProtocol


def _make_identity(embedding: np.ndarray, media_id: int = 1) -> MediaIdentity:
    """Create a MediaIdentity with given embedding for testing."""
    return MediaIdentity(
        id=str(uuid.uuid4()),
        media_id=str(media_id),
        tenant_id=str(uuid.uuid4()),
        bbox_x=0,
        bbox_y=0,
        bbox_width=100,
        bbox_height=100,
        confidence=0.99,
        embedding=embedding,
    )


class FakeConstrainedHAC:
    """Fake implementation of ConstrainedHACProtocol for testing."""

    def __init__(self, cluster_assignments: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        """Initialize with optional predetermined cluster assignments.

        Args:
            cluster_assignments: Map of identity_id -> cluster_id to return.
        """
        self._cluster_assignments = cluster_assignments or {}
        self.refine_clusters_calls: list[tuple[uuid.UUID, dict[uuid.UUID, np.ndarray], float | None]] = []

    async def refine_clusters(
        self,
        *,
        tenant_id: uuid.UUID,
        embeddings: dict[uuid.UUID, np.ndarray],
        distance_threshold_override: float | None = None,
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Return predetermined cluster assignments."""
        self.refine_clusters_calls.append((tenant_id, embeddings, distance_threshold_override))
        return self._cluster_assignments


class SingletonClusterRepoStub:
    def __init__(self, identities: list[MediaIdentity], clusters: dict[str, IdentityCluster]) -> None:
        self._identities = identities
        self._clusters = clusters
        self.deleted: list[str] = []
        self.updated: list[IdentityCluster] = []

    async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None) -> list[MediaIdentity]:
        return self._identities if limit is None else self._identities[:limit]

    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        return self._clusters.get(cluster_id)

    async def update(self, cluster: IdentityCluster) -> IdentityCluster:
        self.updated.append(cluster)
        self._clusters[cluster.id] = cluster
        return cluster

    async def delete(self, cluster_id: str) -> None:
        self.deleted.append(cluster_id)
        self._clusters.pop(cluster_id, None)


class SingletonMemberRepoStub:
    def __init__(self) -> None:
        self.moves: list[tuple[str, str]] = []

    async def move_members(self, source_cluster_id: str, target_cluster_id: str) -> int:
        self.moves.append((source_cluster_id, target_cluster_id))
        return 1


class SingletonWriterStub:
    def __init__(self, cluster_repo: SingletonClusterRepoStub, member_repo: SingletonMemberRepoStub) -> None:
        self.cluster_repository = cluster_repo
        self.member_repository = member_repo
        self.recompute_representatives = AsyncMock()
        self.recompute_centroid = AsyncMock()
        self.refresh_centroids_view = AsyncMock()


@pytest.fixture
def hac_settings() -> HACSettings:
    """Default HAC settings for tests."""
    return HACSettings(
        max_scope_size=500,
        distance_threshold=0.4,
        constraint_penalty=1.0,
    )


@pytest.fixture
def assignment_writer() -> MagicMock:
    """Mock assignment writer for tests."""
    writer = MagicMock()
    writer.persist_new_cluster = AsyncMock(return_value=MagicMock(id=str(uuid.uuid4())))
    return writer


@pytest.mark.asyncio
async def test_hac_refinement_skips_when_no_hac_service(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement returns 0 when constrained_hac is None."""
    identities = [_make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32))]

    result = await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=None,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    assert result == 0
    assignment_writer.persist_new_cluster.assert_not_called()


@pytest.mark.asyncio
async def test_hac_refinement_skips_when_no_settings(
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement returns 0 when hac_settings is None."""
    identities = [_make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32))]
    fake_hac = FakeConstrainedHAC()

    result = await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=None,
        assignment_writer=assignment_writer,
    )

    assert result == 0
    assert len(fake_hac.refine_clusters_calls) == 0


@pytest.mark.asyncio
async def test_hac_refinement_skips_when_empty_unclustered(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement returns 0 when no unclustered identities."""
    fake_hac = FakeConstrainedHAC()

    result = await run_hac_refinement(
        still_unclustered=[],
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    assert result == 0
    assert len(fake_hac.refine_clusters_calls) == 0


@pytest.mark.asyncio
async def test_hac_refinement_skips_when_exceeds_max_scope(
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement returns 0 when identity count exceeds max_scope_size."""
    # Settings with max_scope_size=2
    settings = HACSettings(max_scope_size=2)
    fake_hac = FakeConstrainedHAC()

    # 3 identities exceeds max_scope_size=2
    identities = [_make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=i) for i in range(3)]

    result = await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=settings,
        assignment_writer=assignment_writer,
    )

    assert result == 0
    assert len(fake_hac.refine_clusters_calls) == 0


@pytest.mark.asyncio
async def test_hac_refinement_creates_clusters_from_assignments(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement creates clusters when HAC returns groupings."""
    # Create 3 identities
    id1 = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=1)
    id2 = _make_identity(np.array([0.99, 0.1, 0.0], dtype=np.float32), media_id=2)
    id3 = _make_identity(np.array([0.0, 1.0, 0.0], dtype=np.float32), media_id=3)
    identities = [id1, id2, id3]

    # HAC groups id1 and id2 into one cluster, id3 alone (no cluster)
    cluster_uuid = uuid.uuid4()
    cluster_assignments = {
        uuid.UUID(id1.id): cluster_uuid,
        uuid.UUID(id2.id): cluster_uuid,
        # id3 not included = remains singleton
    }
    fake_hac = FakeConstrainedHAC(cluster_assignments=cluster_assignments)

    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    result = await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=tenant_id,
        job_id=job_id,
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    # Should create 1 cluster with 2 members
    assert result == 1
    assignment_writer.persist_new_cluster.assert_called_once()
    call_kwargs = assignment_writer.persist_new_cluster.call_args.kwargs
    assert call_kwargs["tenant_id"] == tenant_id
    assert len(call_kwargs["identities"]) == 2
    assert len(call_kwargs["similarities"]) == 2
    assert all(isinstance(similarity, float) for similarity in call_kwargs["similarities"])
    assert call_kwargs["algorithm"] == "constrained_hac"


@pytest.mark.asyncio
async def test_hac_refinement_skips_singleton_groups(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement doesn't create clusters for single-member groups."""
    id1 = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=1)
    id2 = _make_identity(np.array([0.0, 1.0, 0.0], dtype=np.float32), media_id=2)
    identities = [id1, id2]

    # Each identity in its own cluster (singletons)
    cluster_assignments = {
        uuid.UUID(id1.id): uuid.uuid4(),
        uuid.UUID(id2.id): uuid.uuid4(),
    }
    fake_hac = FakeConstrainedHAC(cluster_assignments=cluster_assignments)

    result = await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    # No clusters created because each group has only 1 member
    assert result == 0
    assignment_writer.persist_new_cluster.assert_not_called()


@pytest.mark.asyncio
async def test_singleton_hac_refinement_merges_singleton_clusters() -> None:
    """Singleton HAC refinement should merge singleton clusters into one."""
    tenant_id = str(uuid.uuid4())

    id1 = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=1)
    id2 = _make_identity(np.array([0.99, 0.05, 0.0], dtype=np.float32), media_id=2)
    id1.cluster_id = str(uuid.uuid4())
    id2.cluster_id = str(uuid.uuid4())

    cluster_a = IdentityCluster(
        id=id1.cluster_id,
        tenant_id=tenant_id,
        label=None,
        is_labeled=False,
        identity_count=1,
    )
    cluster_b = IdentityCluster(
        id=id2.cluster_id,
        tenant_id=tenant_id,
        label=None,
        is_labeled=False,
        identity_count=1,
    )

    if cluster_a.id is None or cluster_b.id is None:
        raise AssertionError("Test setup requires cluster IDs")
    cluster_repo = SingletonClusterRepoStub([id1, id2], {cluster_a.id: cluster_a, cluster_b.id: cluster_b})
    member_repo = SingletonMemberRepoStub()
    writer = SingletonWriterStub(cluster_repo, member_repo)

    group_id = uuid.uuid4()
    fake_hac = FakeConstrainedHAC(cluster_assignments={uuid.UUID(id1.id): group_id, uuid.UUID(id2.id): group_id})

    merged = await run_singleton_hac_refinement(
        tenant_id=tenant_id,
        constrained_hac=fake_hac,
        hac_settings=HACSettings(max_scope_size=10),
        assignment_writer=writer,
    )

    assert merged == 1
    assert member_repo.moves == [(id2.cluster_id, id1.cluster_id)]
    assert cluster_repo.deleted == [id2.cluster_id]
    assert writer.recompute_representatives.await_count == 1
    assert writer.recompute_centroid.await_count == 1
    assert writer.refresh_centroids_view.await_count == 1


@pytest.mark.asyncio
async def test_hac_refinement_passes_embeddings_to_hac(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement passes correct embeddings to the HAC service."""
    vec1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec2 = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    id1 = _make_identity(vec1, media_id=1)
    id2 = _make_identity(vec2, media_id=2)
    identities = [id1, id2]

    fake_hac = FakeConstrainedHAC()
    tenant_id = str(uuid.uuid4())

    await run_hac_refinement(
        still_unclustered=identities,
        tenant_id=tenant_id,
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    # Verify HAC was called with correct tenant and embeddings
    assert len(fake_hac.refine_clusters_calls) == 1
    call_tenant_id, call_embeddings, _threshold = fake_hac.refine_clusters_calls[0]
    assert str(call_tenant_id) == tenant_id
    assert uuid.UUID(id1.id) in call_embeddings
    assert uuid.UUID(id2.id) in call_embeddings
    np.testing.assert_array_equal(call_embeddings[uuid.UUID(id1.id)], vec1)
    np.testing.assert_array_equal(call_embeddings[uuid.UUID(id2.id)], vec2)


@pytest.mark.asyncio
async def test_hac_refinement_reduces_singletons_with_real_hac(
    assignment_writer: MagicMock,
) -> None:
    """HAC refinement should merge similar singletons into a new cluster."""
    # Use relaxed settings to ensure similar embeddings cluster together:
    # - distance_threshold=0.2: Lower than default (0.4) to force grouping of close vectors
    # - constraint_penalty=10.0: Higher than default to strongly enforce constraints
    # - max_scope_size=10: Small scope for test performance
    settings = HACSettings(
        linkage_method="single",
        distance_threshold=0.2,
        constraint_penalty=10.0,
        max_scope_size=10,
    )
    constraint_repo = AsyncMock()
    constraint_repo.get_all.return_value = []
    hac = ConstrainedHAC(constraint_repo, settings)

    id1 = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=1)
    id2 = _make_identity(np.array([0.98, 0.05, 0.0], dtype=np.float32), media_id=2)

    result = await run_hac_refinement(
        still_unclustered=[id1, id2],
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=hac,
        hac_settings=settings,
        assignment_writer=assignment_writer,
    )

    assert result == 1
    assignment_writer.persist_new_cluster.assert_called_once()
    call_kwargs = assignment_writer.persist_new_cluster.call_args.kwargs
    assert len(call_kwargs["identities"]) == 2


# ---------------------------------------------------------------------------
# Phase 1: Planner overlap and HAC exclusion regression scaffolds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hac_refinement_excludes_already_assigned_identities(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """HAC must not persist clusters for identities already assigned by graph fallback.

    This is the regression scaffold for the planner overlap bug: when
    _process_chunks() passes a filtered hac_eligible list (excluding identities
    placed in graph-fallback clusters), run_hac_refinement must only process
    those filtered identities.
    """
    id_assigned = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=1)
    id_unassigned = _make_identity(np.array([0.99, 0.05, 0.0], dtype=np.float32), media_id=2)

    # Simulate the caller already filtering out id_assigned — only pass id_unassigned.
    # HAC with a single identity has fewer than 2 members, so nothing should be created.
    fake_hac = FakeConstrainedHAC(cluster_assignments={uuid.UUID(id_unassigned.id): uuid.uuid4()})

    result = await run_hac_refinement(
        still_unclustered=[id_unassigned],  # id_assigned has already been excluded upstream
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    # Single identity cannot form a cluster
    assert result == 0
    assignment_writer.persist_new_cluster.assert_not_called()
    # HAC must not have been called with the excluded identity
    if fake_hac.refine_clusters_calls:
        _t, embeddings, _thresh = fake_hac.refine_clusters_calls[0]
        assert uuid.UUID(id_assigned.id) not in embeddings


@pytest.mark.asyncio
async def test_hac_refinement_two_eligible_identities_create_cluster(
    hac_settings: HACSettings,
    assignment_writer: MagicMock,
) -> None:
    """Two identities left after planner exclusion can still form an HAC cluster.

    Verifies that filtering for planner overlap does not break normal HAC paths.
    """
    id_a = _make_identity(np.array([1.0, 0.0, 0.0], dtype=np.float32), media_id=10)
    id_b = _make_identity(np.array([0.99, 0.1, 0.0], dtype=np.float32), media_id=11)

    shared_group = uuid.uuid4()
    fake_hac = FakeConstrainedHAC(
        cluster_assignments={
            uuid.UUID(id_a.id): shared_group,
            uuid.UUID(id_b.id): shared_group,
        }
    )

    result = await run_hac_refinement(
        still_unclustered=[id_a, id_b],
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        constrained_hac=fake_hac,
        hac_settings=hac_settings,
        assignment_writer=assignment_writer,
    )

    assert result == 1
    assignment_writer.persist_new_cluster.assert_called_once()
