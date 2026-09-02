"""Pair-level merge suggestions: labeled cluster may pair with unlabeled twin.

WBUX-6 C2: a user-confirmed labeled cluster was excluded from the candidate
pool, so a new unlabeled twin in the suggestion band was never proposed.
Eligibility is pair-level: at most one side labeled; labeled side is survivor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

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
from recognition.infrastructure.repositories.merge_suggestion_repository import (
    SqlAlchemyMergeSuggestionRepository,
)
from recognition.interface_adapters.http.routers.suggestions import _to_merge_response
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
    cluster_id: str | None = None,
) -> IdentityCluster:
    cluster_id = cluster_id or str(generate_id())
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
    assert call.survivor_cluster_id == labeled.id
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
    assert call.survivor_cluster_id is None
    assert _settings().suggestion_floor <= call.similarity < _settings().similarity_threshold


@pytest.mark.parametrize("reserved_label", ["cluster_7", "CLUSTER-9"])
@pytest.mark.asyncio
async def test_reserved_label_shape_is_not_labeled_survivor(reserved_label: str) -> None:
    """S3-F2: reserved cluster_/CLUSTER- shapes are unlabeled even when user_confirmed."""
    tenant_id = str(generate_id())
    unlabeled = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, embedding=_IN_BAND_A)
    reserved = _cluster(
        tenant_id=tenant_id,
        label=reserved_label,
        user_confirmed=True,
        embedding=_IN_BAND_B,
    )

    repo = await _generate([unlabeled, reserved], tenant_id)

    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert {call.cluster_a_id, call.cluster_b_id} == {unlabeled.id, reserved.id}
    assert call.cluster_a_id == unlabeled.id
    assert call.cluster_b_id == reserved.id
    assert call.survivor_cluster_id is None


@pytest.mark.asyncio
async def test_unconfirmed_real_label_is_not_labeled_survivor() -> None:
    """S3-F3: real label without user_confirmed is not labeled (mutant: drop user_confirmed)."""
    tenant_id = str(generate_id())
    unlabeled = _cluster(tenant_id=tenant_id, label=None, user_confirmed=False, embedding=_IN_BAND_A)
    named_unconfirmed = _cluster(
        tenant_id=tenant_id,
        label="Ada Lovelace",
        user_confirmed=False,
        embedding=_IN_BAND_B,
    )

    repo = await _generate([unlabeled, named_unconfirmed], tenant_id)

    assert len(repo.calls) == 1
    call = repo.calls[0]
    assert call.cluster_a_id == unlabeled.id
    assert call.cluster_b_id == named_unconfirmed.id
    assert call.survivor_cluster_id is None


@pytest.mark.asyncio
async def test_labeled_labeled_skips_similarity_computation(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3-F4: ineligible labeled+labeled pairs must not reach compute_similarity."""
    tenant_id = str(generate_id())
    labeled_a = _cluster(tenant_id=tenant_id, label="Ada", user_confirmed=True, embedding=_IN_BAND_A)
    labeled_b = _cluster(tenant_id=tenant_id, label="Ada Twin", user_confirmed=True, embedding=_IN_BAND_B)
    similarity_calls: list[tuple[object, object]] = []

    def _spy_similarity(left: object, right: object) -> float:
        similarity_calls.append((left, right))
        return 0.75

    monkeypatch.setattr(
        "recognition.application.suggestions.merge_suggestions.compute_similarity",
        _spy_similarity,
    )

    repo = await _generate([labeled_a, labeled_b], tenant_id)

    assert repo.calls == []
    assert similarity_calls == []


@pytest.mark.asyncio
async def test_upsert_pending_persists_survivor_when_labeled_id_sorts_after() -> None:
    """S3-F1: labeled survivor survives UUID canonical reorder (mutant: assign after sort)."""
    unlabeled_id = UUID("00000000-0000-0000-0000-000000000001")
    labeled_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    assert unlabeled_id.int < labeled_id.int
    captured: dict[str, object] = {}

    class _Session:
        async def execute(self, _stmt: object) -> object:
            result = AsyncMock()
            result.scalar_one_or_none = lambda: None
            return result

        def add(self, model: object) -> None:
            if getattr(model, "id", None) is None:
                model.id = uuid4()
            captured["model"] = model

        async def flush(self) -> None:
            return None

        async def refresh(self, _model: object) -> None:
            return None

    repo = SqlAlchemyMergeSuggestionRepository(_Session())  # type: ignore[arg-type]
    suggestion = await repo.upsert_pending(
        str(uuid4()),
        MergeSuggestionCreateData(
            cluster_a_id=str(labeled_id),
            cluster_b_id=str(unlabeled_id),
            similarity=0.72,
            survivor_cluster_id=str(labeled_id),
        ),
    )

    model = captured["model"]
    assert getattr(model, "cluster_a_id") == unlabeled_id
    assert getattr(model, "cluster_b_id") == labeled_id
    assert getattr(model, "survivor_cluster_id") == labeled_id
    assert suggestion.survivor_cluster_id == str(labeled_id)
    assert suggestion.cluster_a_id == str(unlabeled_id)
    assert suggestion.cluster_b_id == str(labeled_id)


def test_list_merge_response_carries_survivor_cluster_id_and_label() -> None:
    """S3-F1: pending list payload exposes durable survivor id + label."""
    unlabeled_id = "00000000-0000-0000-0000-000000000001"
    labeled_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    suggestion = SimpleNamespace(
        id=str(uuid4()),
        cluster_a_id=unlabeled_id,
        cluster_b_id=labeled_id,
        similarity=0.72,
        status=SuggestionStatus.PENDING,
        confidence_score=0.72,
        expires_at=None,
        source_job_id=None,
        cluster_a_label=None,
        cluster_b_label="Ada Lovelace",
        survivor_cluster_id=labeled_id,
    )

    response = _to_merge_response(suggestion)
    dumped = response.model_dump()

    assert response.survivor_cluster_id == labeled_id
    assert response.survivor_label == "Ada Lovelace"
    assert "survivor_cluster_id" in dumped
    assert "survivor_label" in dumped
