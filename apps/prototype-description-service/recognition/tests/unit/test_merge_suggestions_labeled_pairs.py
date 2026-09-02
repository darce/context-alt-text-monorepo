"""Pair-level merge suggestions: labeled cluster may pair with unlabeled twin.

WBUX-6 C2: a user-confirmed labeled cluster was excluded from the candidate
pool, so a new unlabeled twin in the suggestion band was never proposed.
Eligibility is pair-level: at most one side labeled; labeled side is survivor.
"""

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
from recognition.domain.suggestion_details import MergeSuggestionDetails
from recognition.shared.ids import generate_id

# Cosine ~0.75 — inside [suggestion_floor=0.65, similarity_threshold=0.8).
_IN_BAND_A = np.array([1.0, 0.0, 0.0], dtype=np.float32)
_IN_BAND_B = np.array([0.75, 0.6614, 0.0], dtype=np.float32)
# Orthogonal to both in-band vectors (xy-plane) — similarity 0, below the floor.
_BELOW_FLOOR = np.array([0.0, 0.0, 1.0], dtype=np.float32)


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
        return 0


def _settings() -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.65,
        suggestion_ceiling=0.8,
    )


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
    embedding: np.ndarray,
) -> IdentityCluster:
    cluster_id = str(generate_id())
    return IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        label=label,
        is_labeled=bool(label),
        identity_count=1,
        created_at=datetime.now(tz=UTC),
        user_confirmed=user_confirmed,
        representatives=[_rep(cluster_id, embedding)],
        centroid=compute_centroid([embedding]),
    )


async def _generate(clusters: list[IdentityCluster], tenant_id: str) -> MergeSuggestionRepoStub:
    repo = MergeSuggestionRepoStub()
    await generate_cluster_merge_suggestions(
        tenant_id=tenant_id,
        clusters=clusters,
        repository=repo,
        settings=_settings(),
    )
    return repo


@pytest.mark.asyncio
async def test_labeled_unlabeled_in_band_suggests_labeled_as_survivor() -> None:
    tenant_id = str(generate_id())
    unlabeled = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, embedding=_IN_BAND_A)
    labeled = _cluster(tenant_id=tenant_id, label="Ada Lovelace", user_confirmed=True, embedding=_IN_BAND_B)

    repo = await _generate([unlabeled, labeled], tenant_id)

    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call.cluster_a_id == labeled.id
    assert call.cluster_b_id == unlabeled.id
    assert _settings().suggestion_floor <= call.similarity < _settings().similarity_threshold


@pytest.mark.asyncio
async def test_labeled_labeled_in_band_never_suggested() -> None:
    tenant_id = str(generate_id())
    labeled_a = _cluster(tenant_id=tenant_id, label="Ada", user_confirmed=True, embedding=_IN_BAND_A)
    labeled_b = _cluster(tenant_id=tenant_id, label="Ada Twin", user_confirmed=True, embedding=_IN_BAND_B)

    repo = await _generate([labeled_a, labeled_b], tenant_id)

    assert repo.calls == []


@pytest.mark.asyncio
async def test_labeled_unlabeled_below_floor_not_suggested() -> None:
    tenant_id = str(generate_id())
    unlabeled = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, embedding=_IN_BAND_A)
    labeled = _cluster(tenant_id=tenant_id, label="Ada Lovelace", user_confirmed=True, embedding=_BELOW_FLOOR)

    repo = await _generate([unlabeled, labeled], tenant_id)

    assert repo.calls == []


@pytest.mark.asyncio
async def test_unlabeled_pair_in_band_still_suggested() -> None:
    tenant_id = str(generate_id())
    unlabeled_a = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, embedding=_IN_BAND_A)
    unlabeled_b = _cluster(tenant_id=tenant_id, label="cluster-xyz", user_confirmed=False, embedding=_IN_BAND_B)
    labeled = _cluster(tenant_id=tenant_id, label="Daniel", user_confirmed=True, embedding=_BELOW_FLOOR)

    repo = await _generate([unlabeled_a, unlabeled_b, labeled], tenant_id)

    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert {call.cluster_a_id, call.cluster_b_id} == {unlabeled_a.id, unlabeled_b.id}
    assert call.cluster_a_id == unlabeled_a.id
    assert call.cluster_b_id == unlabeled_b.id
    assert _settings().suggestion_floor <= call.similarity < _settings().similarity_threshold
