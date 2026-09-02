"""Unit tests for cluster merge suggestion generation."""

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
from recognition.domain.suggestion_details import MergeSuggestionDetails
from recognition.shared.ids import generate_id
from recognition.shared.similarity import normalize_face_embedding


class MergeSuggestionRepoStub(MergeSuggestionRepository):
    def __init__(self) -> None:
        self.calls: list[MergeSuggestionCreateData] = []
        self.delete_calls: list[tuple[str, str]] = []

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

    async def list_pending_with_details(self, tenant_id: str, limit: int, offset: int) -> list[MergeSuggestionDetails]:
        return []

    async def update_status(
        self,
        tenant_id: str,
        suggestion_id: str,
        status: SuggestionStatus,
    ) -> MergeSuggestion:
        raise NotImplementedError

    async def get_by_id(self, tenant_id: str, suggestion_id: str) -> MergeSuggestion | None:
        return None

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        self.delete_calls.append((tenant_id, cluster_id))
        return 0


def _rep(cluster_id: str, embedding: np.ndarray) -> ClusterRepresentative:
    return ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=str(generate_id()),
        embedding=embedding,
        created_at=datetime.now(tz=UTC),
        quality_score=1.0,
    )


def _cluster(
    *,
    tenant_id: str,
    label: str | None,
    user_confirmed: bool,
    reps: list[np.ndarray],
) -> IdentityCluster:
    cluster_id = str(generate_id())
    centroid = compute_centroid(reps) if reps else None
    return IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        label=label,
        is_labeled=bool(label),
        identity_count=len(reps),
        created_at=datetime.now(tz=UTC),
        user_confirmed=user_confirmed,
        representatives=[_rep(cluster_id, rep) for rep in reps],
        centroid=centroid,
    )


def _singleton_cluster(
    *,
    tenant_id: str,
    embedding: np.ndarray,
    label: str | None = None,
    user_confirmed: bool = False,
) -> IdentityCluster:
    cluster_id = str(generate_id())
    identity_id = str(generate_id())
    rep = ClusterRepresentative(
        id=str(generate_id()),
        cluster_id=cluster_id,
        identity_id=identity_id,
        embedding=embedding,
        created_at=datetime.now(tz=UTC),
        quality_score=1.0,
    )
    return IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        label=label,
        is_labeled=bool(label),
        identity_count=1,
        representative_identity_id=identity_id,
        created_at=datetime.now(tz=UTC),
        user_confirmed=user_confirmed,
        representatives=[rep],
        centroid=normalize_face_embedding(embedding),
    )


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
    ):
        return self._clusters

    async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None):
        return []


@pytest.mark.asyncio
async def test_generate_cluster_merge_suggestions_filters_and_creates() -> None:
    tenant_id = str(generate_id())
    # Override defaults to match P1 target thresholds (see false-positive-analysis.md §4.1)
    # similarity_threshold=0.80 and suggestion_ceiling=0.80 per the lowered thresholds fix
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )

    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.75, 0.6614, 0.0], dtype=np.float32)
    # Orthogonal to both in-band vectors so the labeled cluster stays below the floor.
    vec_c = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    unlabeled_a = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, reps=[vec_a])
    unlabeled_b = _cluster(tenant_id=tenant_id, label="cluster-xyz", user_confirmed=False, reps=[vec_b])
    labeled = _cluster(tenant_id=tenant_id, label="Daniel", user_confirmed=True, reps=[vec_c])

    repo = MergeSuggestionRepoStub()

    created = await generate_cluster_merge_suggestions(
        tenant_id=tenant_id,
        clusters=[unlabeled_a, unlabeled_b, labeled],
        repository=repo,
        settings=settings,
    )

    assert created == 1
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert {call.cluster_a_id, call.cluster_b_id} == {unlabeled_a.id, unlabeled_b.id}
    assert settings.suggestion_floor <= call.similarity < settings.similarity_threshold


@pytest.mark.asyncio
async def test_generate_singleton_merge_suggestions_groups_singletons() -> None:
    tenant_id = str(generate_id())
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )
    hac_settings = HACSettings(max_scope_size=10)

    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.75, 0.6614, 0.0], dtype=np.float32)

    cluster_a = _singleton_cluster(tenant_id=tenant_id, embedding=vec_a)
    cluster_b = _singleton_cluster(tenant_id=tenant_id, embedding=vec_b)

    class ConstrainedHACStub:
        async def refine_clusters(self, *, tenant_id, embeddings):  # noqa: ANN001
            group_id = generate_id()
            return dict.fromkeys(embeddings.keys(), group_id)

    repo = MergeSuggestionRepoStub()
    cluster_repo = ClusterRepoStub([cluster_a, cluster_b])
    service = MergeSuggestionService(repo, cluster_repository=cluster_repo, settings=settings)

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=ConstrainedHACStub(),
        hac_settings=hac_settings,
    )

    assert created == 1
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert {call.cluster_a_id, call.cluster_b_id} == {cluster_a.id, cluster_b.id}
    assert call.survivor_cluster_id is None


class ConstrainedHACGroupStub:
    async def refine_clusters(self, *, tenant_id, embeddings):  # noqa: ANN001
        group_id = generate_id()
        return dict.fromkeys(embeddings.keys(), group_id)


@pytest.mark.asyncio
async def test_generate_singleton_two_labeled_does_not_upsert() -> None:
    """S3-F3: two labeled singletons in one HAC group never become a merge suggestion."""
    tenant_id = str(generate_id())
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )
    hac_settings = HACSettings(max_scope_size=10)
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.75, 0.6614, 0.0], dtype=np.float32)
    labeled_a = _singleton_cluster(tenant_id=tenant_id, embedding=vec_a, label="Ada", user_confirmed=True)
    labeled_b = _singleton_cluster(tenant_id=tenant_id, embedding=vec_b, label="Bea", user_confirmed=True)

    repo = MergeSuggestionRepoStub()
    service = MergeSuggestionService(
        repo,
        cluster_repository=ClusterRepoStub([labeled_a, labeled_b]),
        settings=settings,
    )

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=ConstrainedHACGroupStub(),
        hac_settings=hac_settings,
    )

    assert created == 0
    assert repo.calls == []


@pytest.mark.asyncio
async def test_generate_singleton_labeled_unlabeled_upserts_labeled_survivor() -> None:
    """S3-F3: labeled singleton + unlabeled singleton upsert with labeled survivor."""
    tenant_id = str(generate_id())
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )
    hac_settings = HACSettings(max_scope_size=10)
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.75, 0.6614, 0.0], dtype=np.float32)
    unlabeled = _singleton_cluster(tenant_id=tenant_id, embedding=vec_a)
    labeled = _singleton_cluster(tenant_id=tenant_id, embedding=vec_b, label="Ada", user_confirmed=True)

    repo = MergeSuggestionRepoStub()
    service = MergeSuggestionService(
        repo,
        cluster_repository=ClusterRepoStub([unlabeled, labeled]),
        settings=settings,
    )

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=ConstrainedHACGroupStub(),
        hac_settings=hac_settings,
    )

    assert created == 1
    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call.cluster_a_id == labeled.id
    assert call.cluster_b_id == unlabeled.id
    assert call.survivor_cluster_id == labeled.id


@pytest.mark.asyncio
async def test_generate_singleton_labeled_labeled_skips_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3-F4: singleton labeled+labeled pairs skip compute_similarity."""
    tenant_id = str(generate_id())
    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )
    hac_settings = HACSettings(max_scope_size=10)
    vec_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    vec_b = np.array([0.75, 0.6614, 0.0], dtype=np.float32)
    labeled_a = _singleton_cluster(tenant_id=tenant_id, embedding=vec_a, label="Ada", user_confirmed=True)
    labeled_b = _singleton_cluster(tenant_id=tenant_id, embedding=vec_b, label="Bea", user_confirmed=True)
    similarity_calls: list[tuple[object, object]] = []

    def _spy_similarity(left: object, right: object) -> float:
        similarity_calls.append((left, right))
        return 0.75

    monkeypatch.setattr(
        "recognition.application.suggestions.merge_suggestions.compute_similarity",
        _spy_similarity,
    )

    repo = MergeSuggestionRepoStub()
    service = MergeSuggestionService(
        repo,
        cluster_repository=ClusterRepoStub([labeled_a, labeled_b]),
        settings=settings,
    )

    created = await service.generate_singleton_merge_suggestions(
        tenant_id,
        constrained_hac=ConstrainedHACGroupStub(),
        hac_settings=hac_settings,
    )

    assert created == 0
    assert repo.calls == []
    assert similarity_calls == []


@pytest.mark.asyncio
async def test_merge_suggestion_service_deletes_by_cluster() -> None:
    tenant_id = str(generate_id())
    cluster_id = str(generate_id())
    repo = MergeSuggestionRepoStub()
    cluster_repo = ClusterRepoStub([])
    service = MergeSuggestionService(repo, cluster_repository=cluster_repo, settings=ClusteringSettings())

    deleted = await service.delete_by_cluster(tenant_id, cluster_id)

    assert deleted == 0
    assert repo.delete_calls == [(tenant_id, cluster_id)]
