"""CVUP1-R3-16: merge suggestions must not cosine across embedding spaces."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from recognition.application.clustering.centroid_utils import compute_centroid
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.merge_suggestions import generate_cluster_merge_suggestions
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MergeSuggestionCreateData, MergeSuggestionRepository
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.shared.ids import generate_id


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
