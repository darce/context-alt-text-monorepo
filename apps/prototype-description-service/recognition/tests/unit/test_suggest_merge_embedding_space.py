"""CVUP1-R3-16: merge suggestions must not cosine across embedding spaces."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from recognition.application.clustering.centroid_utils import compute_centroid
from recognition.application.settings import ClusteringSettings
from recognition.application.settings.clustering import HACSettings
from recognition.application.suggestions.merge_suggestions import (
    MergeSuggestionService,
    generate_cluster_merge_suggestions,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MergeSuggestionCreateData, MergeSuggestionRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.shared.ids import generate_id
from recognition.shared.similarity import normalize_face_embedding


class MergeSuggestionRepoStub(MergeSuggestionRepository):
    def __init__(self) -> None:
        self.calls: list[MergeSuggestionCreateData] = []

    async def upsert_pending(self, tenant_id: str, payload: MergeSuggestionCreateData) -> MergeSuggestion:
        self.calls.append(payload)
        return MergeSuggestion(
            id=str(generate_id()),
            cluster_a_id=payload.cluster_a_id,
            cluster_b_id=payload.cluster_b_id,
            similarity=payload.similarity,
            status=SuggestionStatus.PENDING,
            created_at=datetime.now(tz=UTC),
            refreshed_at=payload.refreshed_at,
            source=payload.source,
        )

    async def list_pending_with_details(self, tenant_id: str, limit: int, offset: int):
        return []

    async def update_status(self, tenant_id: str, suggestion_id: str, status: SuggestionStatus) -> MergeSuggestion:
        raise NotImplementedError

    async def get_by_id(self, tenant_id: str, suggestion_id: str) -> MergeSuggestion | None:
        return None

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        return 0


def _cluster(*, tenant_id: str, embedding: np.ndarray, model: str | None) -> IdentityCluster:
    cluster_id = str(generate_id())
    rep = ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=str(generate_id()),
        embedding=embedding,
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )
    return IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=1,
        created_at=datetime.now(tz=UTC),
        user_confirmed=False,
        representatives=[rep],
        centroid=compute_centroid([embedding]),
        embedding_model=model,
    )


@pytest.mark.asyncio
async def test_generate_cluster_merge_suggestions_skips_cross_space_centroids() -> None:
    tenant_id = str(generate_id())
    vec_a = np.array([1.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.8, 0.6], dtype=np.float32)
    vec_foreign = np.array([0.95, 0.312], dtype=np.float32)
    same_a = _cluster(tenant_id=tenant_id, embedding=vec_a, model="space-a")
    same_b = _cluster(tenant_id=tenant_id, embedding=vec_b, model="space-a")
    foreign = _cluster(tenant_id=tenant_id, embedding=vec_foreign, model="space-b")
    repo = MergeSuggestionRepoStub()
    settings = ClusteringSettings(similarity_threshold=0.99, suggestion_floor=0.5)

    created = await generate_cluster_merge_suggestions(
        tenant_id=tenant_id,
        clusters=[same_a, same_b, foreign],
        repository=repo,
        settings=settings,
    )

    pair_ids = {(call.cluster_a_id, call.cluster_b_id) for call in repo.calls}
    assert created == 1
    assert (same_a.id, same_b.id) in pair_ids or (same_b.id, same_a.id) in pair_ids
    assert all(foreign.id not in pair for pair in pair_ids)


def _centroid_only_cluster(*, tenant_id: str, embedding: np.ndarray, model: str | None) -> IdentityCluster:
    """Cluster with a centroid but no loaded representatives (pre-recompute state)."""
    return IdentityCluster(
        id=str(generate_id()),
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=3,
        created_at=datetime.now(tz=UTC),
        user_confirmed=False,
        representatives=[],
        centroid=compute_centroid([embedding]),
        embedding_model=model,
    )


@pytest.mark.asyncio
async def test_generate_cluster_merge_suggestions_skips_unresolved_when_tenant_has_stamp() -> None:
    """Unstamped-model clusters must not pair on centroid cosine once any stamp exists."""
    tenant_id = str(generate_id())
    vec_a = np.array([1.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.8, 0.6], dtype=np.float32)
    unresolved_a = _centroid_only_cluster(tenant_id=tenant_id, embedding=vec_a, model=None)
    unresolved_b = _centroid_only_cluster(tenant_id=tenant_id, embedding=vec_b, model=None)
    stamped = _cluster(tenant_id=tenant_id, embedding=vec_a, model="space-a")
    repo = MergeSuggestionRepoStub()
    settings = ClusteringSettings(similarity_threshold=0.99, suggestion_floor=0.5)

    created = await generate_cluster_merge_suggestions(
        tenant_id=tenant_id,
        clusters=[unresolved_a, unresolved_b, stamped],
        repository=repo,
        settings=settings,
    )

    involved = {cid for call in repo.calls for cid in (call.cluster_a_id, call.cluster_b_id)}
    assert unresolved_a.id not in involved
    assert unresolved_b.id not in involved
    assert created == 0


@pytest.mark.asyncio
async def test_generate_cluster_merge_suggestions_pairs_legacy_all_unstamped() -> None:
    tenant_id = str(generate_id())
    vec_a = np.array([1.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.8, 0.6], dtype=np.float32)
    unresolved_a = _centroid_only_cluster(tenant_id=tenant_id, embedding=vec_a, model=None)
    unresolved_b = _centroid_only_cluster(tenant_id=tenant_id, embedding=vec_b, model=None)
    repo = MergeSuggestionRepoStub()
    settings = ClusteringSettings(similarity_threshold=0.99, suggestion_floor=0.5)

    created = await generate_cluster_merge_suggestions(
        tenant_id=tenant_id,
        clusters=[unresolved_a, unresolved_b],
        repository=repo,
        settings=settings,
    )

    assert created == 1
    pair_ids = {(call.cluster_a_id, call.cluster_b_id) for call in repo.calls}
    assert (unresolved_a.id, unresolved_b.id) in pair_ids or (unresolved_b.id, unresolved_a.id) in pair_ids


class ClusterRepoStub:
    def __init__(self, clusters: list[IdentityCluster]) -> None:
        self._clusters = clusters

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ):  # noqa: ARG002, E501
        return self._clusters


class RecordingHAC:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def refine_clusters(self, *, tenant_id, embeddings):  # noqa: ANN001, ARG002
        dims = {tuple(emb.shape) for emb in embeddings.values()}
        models_nbytes = {emb.shape[0] for emb in embeddings.values()}
        assert len(dims) == 1, f"HAC invoked on mixed-dimension matrix: {dims}"
        assert len(models_nbytes) == 1
        self.calls.append(dict(embeddings))
        group_id = generate_id()
        return dict.fromkeys(embeddings.keys(), group_id)


def _singleton(*, tenant_id: str, embedding: np.ndarray, model: str | None) -> IdentityCluster:
    cluster_id = str(generate_id())
    identity_id = str(generate_id())
    rep = ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=identity_id,
        embedding=embedding,
        created_at=datetime.now(tz=UTC),
        embedding_model=model,
    )
    return IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        is_labeled=False,
        identity_count=1,
        representative_identity_id=identity_id,
        created_at=datetime.now(tz=UTC),
        user_confirmed=False,
        representatives=[rep],
        centroid=normalize_face_embedding(embedding),
        embedding_model=model,
    )


def _pad(dim: int, *head: float) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    for i, value in enumerate(head):
        vec[i] = value
    return vec


@pytest.mark.asyncio
async def test_generate_singleton_merge_partitions_hac_by_embedding_space() -> None:
    """HAC must not see mixed spaces: same-space pairs upsert, foreign is excluded."""
    tenant_id = str(generate_id())
    settings = ClusteringSettings(similarity_threshold=0.8, suggestion_floor=0.65, suggestion_ceiling=0.8)
    vec_a = _pad(512, 1.0)
    vec_b = _pad(512, 0.75, 0.6614)
    vec_foreign = _pad(512, 0.95, 0.312)
    same_a = _singleton(tenant_id=tenant_id, embedding=vec_a, model="space-a")
    same_b = _singleton(tenant_id=tenant_id, embedding=vec_b, model="space-a")
    foreign = _singleton(tenant_id=tenant_id, embedding=vec_foreign, model="space-b")
    hac = RecordingHAC()
    repo = MergeSuggestionRepoStub()
    service = MergeSuggestionService(
        repo, cluster_repository=ClusterRepoStub([same_a, same_b, foreign]), settings=settings
    )

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=hac,
        hac_settings=HACSettings(max_scope_size=10),
    )

    assert created == 1
    assert len(hac.calls) == 1
    assert len(hac.calls[0]) == 2
    pair_ids = {(call.cluster_a_id, call.cluster_b_id) for call in repo.calls}
    assert (same_a.id, same_b.id) in pair_ids or (same_b.id, same_a.id) in pair_ids
    assert all(foreign.id not in pair for pair in pair_ids)


@pytest.mark.asyncio
async def test_generate_singleton_merge_runs_hac_per_dimension_space() -> None:
    """128d and 512d singletons must not share an HAC matrix."""
    tenant_id = str(generate_id())
    settings = ClusteringSettings(similarity_threshold=0.8, suggestion_floor=0.65, suggestion_ceiling=0.8)
    a128 = _singleton(tenant_id=tenant_id, embedding=_pad(128, 1.0), model="space-128")
    b128 = _singleton(tenant_id=tenant_id, embedding=_pad(128, 0.75, 0.6614), model="space-128")
    a512 = _singleton(tenant_id=tenant_id, embedding=_pad(512, 1.0), model="space-512")
    b512 = _singleton(tenant_id=tenant_id, embedding=_pad(512, 0.75, 0.6614), model="space-512")
    hac = RecordingHAC()
    repo = MergeSuggestionRepoStub()
    service = MergeSuggestionService(
        repo,
        cluster_repository=ClusterRepoStub([a128, b128, a512, b512]),
        settings=settings,
    )

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=hac,
        hac_settings=HACSettings(max_scope_size=10),
    )

    assert created == 2
    assert len(hac.calls) == 2
    call_dims = sorted({next(iter(call.values())).shape[0] for call in hac.calls})
    assert call_dims == [128, 512]
    assert all(len(call) == 2 for call in hac.calls)
    involved = {cid for call in repo.calls for cid in (call.cluster_a_id, call.cluster_b_id)}
    assert involved == {a128.id, b128.id, a512.id, b512.id}
