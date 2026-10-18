"""Unit tests for cluster merge-candidate ranking (GPUFLOW-2 B6)."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from recognition.application.clustering.centroid_utils import compute_centroid, compute_similarity
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions import merge_candidates as merge_candidates_module
from recognition.application.suggestions.merge_candidates import list_merge_candidates
from recognition.application.suggestions.roster_candidates import SimilarityBand
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MergeSuggestionCreateData, MergeSuggestionRepository
from recognition.domain.suggestion import MergeSuggestion, SuggestionStatus
from recognition.domain.suggestion_details import MergeSuggestionDetails
from recognition.interface_adapters.http.routers import cluster_merge_candidates as merge_candidates_router
from recognition.shared.ids import generate_id


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _cluster(
    *,
    tenant_id: str,
    label: str | None,
    embedding: np.ndarray | None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    cluster_id: str | None = None,
    embedding_model: str | None = None,
    representative_identity_id: str | None = None,
    centroid_refreshed_at: datetime | None = None,
) -> IdentityCluster:
    centroid = compute_centroid([embedding]) if embedding is not None else None
    return IdentityCluster(
        id=cluster_id or str(generate_id()),
        tenant_id=tenant_id,
        label=label,
        is_labeled=bool(label),
        identity_count=1 if embedding is not None else 0,
        created_at=created_at or datetime.now(tz=UTC),
        updated_at=updated_at,
        representative_identity_id=representative_identity_id,
        centroid=centroid,
        embedding_model=embedding_model,
        centroid_refreshed_at=centroid_refreshed_at,
    )


def _pending(
    *,
    cluster_a_id: str,
    cluster_b_id: str,
    similarity: float,
    created_at: datetime,
    cluster_a_identity_count: int | None = None,
    cluster_b_identity_count: int | None = None,
    cluster_a_representative_identity_id: str | None = None,
    cluster_b_representative_identity_id: str | None = None,
    status: str = SuggestionStatus.PENDING.value,
    expires_at: datetime | None = None,
    refreshed_at: datetime | None = None,
) -> MergeSuggestionDetails:
    if cluster_a_id <= cluster_b_id:
        left, right = cluster_a_id, cluster_b_id
        left_count, right_count = cluster_a_identity_count, cluster_b_identity_count
        left_representative, right_representative = (
            cluster_a_representative_identity_id,
            cluster_b_representative_identity_id,
        )
    else:
        left, right = cluster_b_id, cluster_a_id
        left_count, right_count = cluster_b_identity_count, cluster_a_identity_count
        left_representative, right_representative = (
            cluster_b_representative_identity_id,
            cluster_a_representative_identity_id,
        )
    return MergeSuggestionDetails(
        id=str(generate_id()),
        cluster_a_id=left,
        cluster_b_id=right,
        similarity=similarity,
        status=status,
        created_at=created_at,
        refreshed_at=refreshed_at,
        expires_at=expires_at,
        cluster_a_identity_count=left_count,
        cluster_b_identity_count=right_count,
        cluster_a_representative_identity_id=left_representative,
        cluster_b_representative_identity_id=right_representative,
    )


class _FakeClusterRepo:
    def __init__(self, clusters: list[IdentityCluster]) -> None:
        self._clusters = list(clusters)

    async def get_by_id(self, cluster_id: str) -> IdentityCluster | None:
        for cluster in self._clusters:
            if str(cluster.id) == str(cluster_id):
                return cluster
        return None

    async def get_by_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        labeled_only: bool = False,
        search: str | None = None,
    ) -> list[IdentityCluster]:
        rows = [cluster for cluster in self._clusters if str(cluster.tenant_id) == str(tenant_id)]
        if labeled_only:
            rows = [cluster for cluster in rows if cluster.label]
        return rows[offset : offset + limit]


class _FakeMergeRepo(MergeSuggestionRepository):
    def __init__(self, pending: list[MergeSuggestionDetails] | None = None) -> None:
        self._pending = list(pending or [])

    async def upsert_pending(self, tenant_id: str, payload: MergeSuggestionCreateData) -> MergeSuggestion:
        raise NotImplementedError

    async def list_pending_with_details(self, tenant_id: str, limit: int, offset: int) -> list[MergeSuggestionDetails]:
        return self._pending[offset : offset + limit]

    async def update_status(self, tenant_id: str, suggestion_id: str, status: SuggestionStatus) -> MergeSuggestion:
        raise NotImplementedError

    async def get_by_id(self, tenant_id: str, suggestion_id: str) -> MergeSuggestion | None:
        return None

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        return 0


def test_merge_candidates_has_no_static_band_cut_shim() -> None:
    assert not hasattr(merge_candidates_module, "SUGGESTION_BAND_CUTS")
    assert not hasattr(merge_candidates_module, "clustering_settings")


@pytest.mark.asyncio
async def test_bands_follow_each_injected_setting_boundary() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0, 0.0])))
    candidate = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([0.6, 0.8, 0.0])))

    async def get_candidate(settings: ClusteringSettings):
        result = await list_merge_candidates(
            tenant_id,
            str(probe.id),
            cluster_repository=_FakeClusterRepo([probe, candidate]),
            merge_suggestion_repository=_FakeMergeRepo(),
            settings=settings,
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].cluster_id == str(candidate.id)
        assert result.candidates[0].similarity == pytest.approx(0.6)
        return result.candidates[0].band

    assert (
        await get_candidate(ClusteringSettings(suggestion_floor=0.40, suggestion_ceiling=0.80))
        is SimilarityBand.POSSIBLE
    )
    assert (
        await get_candidate(ClusteringSettings(suggestion_floor=0.70, suggestion_ceiling=0.80)) is SimilarityBand.NONE
    )
    assert (
        await get_candidate(ClusteringSettings(suggestion_floor=0.40, suggestion_ceiling=0.55))
        is SimilarityBand.STRONG
    )


@pytest.mark.asyncio
async def test_ranks_similarity_desc_then_name_asc() -> None:
    tenant_id = str(uuid4())
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=probe_vec)
    zed = _cluster(tenant_id=tenant_id, label="Zed", embedding=_normalize(np.array([0.9, 0.435, 0.0])))
    ada = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([0.9, 0.435, 0.0])))
    best = _cluster(tenant_id=tenant_id, label="Best", embedding=probe_vec)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([zed, probe, ada, best]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=ClusteringSettings(suggestion_floor=0.10, suggestion_ceiling=0.95),
    )

    assert [row.name for row in result.candidates] == ["Best", "Ada", "Zed"]
    assert [row.cluster_id for row in result.candidates] == [str(best.id), str(ada.id), str(zed.id)]
    assert result.cluster_id == str(probe.id)


@pytest.mark.asyncio
async def test_ranks_fresh_pending_score_above_higher_raw_cosine() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    probe = _cluster(
        tenant_id=tenant_id,
        label=None,
        embedding=_normalize(np.array([1.0, 0.0, 0.0])),
        created_at=now,
    )
    pending_candidate = _cluster(
        tenant_id=tenant_id,
        label="Pending",
        embedding=_normalize(np.array([0.1, np.sqrt(0.99), 0.0])),
        created_at=now,
    )
    raw_candidate = _cluster(
        tenant_id=tenant_id,
        label="Raw",
        embedding=_normalize(np.array([0.8, 0.6, 0.0])),
        created_at=now,
    )

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, raw_candidate, pending_candidate]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(pending_candidate.id),
                    similarity=0.91,
                    created_at=now + timedelta(seconds=1),
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert [row.cluster_id for row in result.candidates] == [
        str(pending_candidate.id),
        str(raw_candidate.id),
    ]
    assert [row.similarity for row in result.candidates] == pytest.approx([0.91, 0.8])


@pytest.mark.asyncio
async def test_similarity_uses_fresh_pending_with_matching_membership() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    other_vec = _normalize(np.array([0.0, 1.0, 0.0]))
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=probe_vec, created_at=now)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=other_vec, created_at=now)
    centroid_sim = compute_similarity(probe_vec, other_vec)
    assert centroid_sim < 0.2

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(other.id),
                    cluster_b_id=str(probe.id),
                    similarity=0.91,
                    created_at=now + timedelta(seconds=1),
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].similarity == pytest.approx(0.91)
    assert result.candidates[0].band is SimilarityBand.STRONG
    assert result.candidates[0].similarity != pytest.approx(centroid_sim)


@pytest.mark.asyncio
async def test_pending_observed_before_cluster_updated_at_is_ignored() -> None:
    tenant_id = str(uuid4())
    created = datetime(2026, 1, 1, tzinfo=UTC)
    updated = datetime(2026, 6, 1, tzinfo=UTC)
    observed = datetime(2026, 3, 1, tzinfo=UTC)
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    other_vec = _normalize(np.array([0.0, 1.0, 0.0]))
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=probe_vec, created_at=created, updated_at=updated)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=other_vec, created_at=created, updated_at=updated)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.99,
                    created_at=observed,
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].similarity == pytest.approx(compute_similarity(probe_vec, other_vec))
    assert result.candidates[0].band is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_pending_observed_before_centroid_refresh_is_ignored() -> None:
    tenant_id = str(uuid4())
    created = datetime(2026, 1, 1, tzinfo=UTC)
    centroid_refreshed = datetime(2026, 6, 1, tzinfo=UTC)
    observed = datetime(2026, 3, 1, tzinfo=UTC)
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    other_vec = _normalize(np.array([0.0, 1.0, 0.0]))
    probe = _cluster(
        tenant_id=tenant_id,
        label=None,
        embedding=probe_vec,
        created_at=created,
        centroid_refreshed_at=centroid_refreshed,
    )
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=other_vec, created_at=created)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.99,
                    created_at=observed,
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert result.candidates[0].similarity == pytest.approx(compute_similarity(probe_vec, other_vec))
    assert result.candidates[0].band is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_fresh_timestamp_with_stale_membership_uses_live_centroid_only() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    other_vec = _normalize(np.array([0.0, 1.0, 0.0]))
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=probe_vec, created_at=now)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=other_vec, created_at=now)
    centroid_sim = compute_similarity(probe_vec, other_vec)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.99,
                    created_at=now + timedelta(seconds=1),
                    cluster_a_identity_count=2,
                    cluster_b_identity_count=1,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert [row.cluster_id for row in result.candidates] == [str(other.id)]
    assert result.candidates[0].similarity == pytest.approx(centroid_sim)
    assert result.candidates[0].similarity == pytest.approx(0.0)
    assert result.candidates[0].band is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_same_count_representative_swap_rejects_pending_score() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    probe_rep = str(uuid4())
    original_other_rep = str(uuid4())
    replacement_other_rep = str(uuid4())
    probe = _cluster(
        tenant_id=tenant_id,
        label=None,
        embedding=_normalize(np.array([1.0, 0.0, 0.0])),
        created_at=now,
        representative_identity_id=probe_rep,
    )
    other = _cluster(
        tenant_id=tenant_id,
        label="Ada",
        embedding=_normalize(np.array([0.0, 1.0, 0.0])),
        created_at=now,
        representative_identity_id=replacement_other_rep,
    )

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.99,
                    created_at=now + timedelta(seconds=1),
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                    cluster_a_representative_identity_id=probe_rep,
                    cluster_b_representative_identity_id=original_other_rep,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert result.candidates[0].similarity == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_refreshed_pending_after_representative_mutation_is_accepted() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    mutation = now + timedelta(seconds=2)
    probe_rep = str(uuid4())
    other_rep = str(uuid4())
    probe = _cluster(
        tenant_id=tenant_id,
        label=None,
        embedding=_normalize(np.array([1.0, 0.0, 0.0])),
        created_at=now,
        representative_identity_id=probe_rep,
    )
    other = _cluster(
        tenant_id=tenant_id,
        label="Ada",
        embedding=_normalize(np.array([0.0, 1.0, 0.0])),
        created_at=now,
        updated_at=mutation,
        representative_identity_id=other_rep,
    )

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.91,
                    created_at=now - timedelta(seconds=1),
                    refreshed_at=mutation + timedelta(seconds=1),
                    cluster_a_identity_count=1,
                    cluster_b_identity_count=1,
                    cluster_a_representative_identity_id=probe_rep,
                    cluster_b_representative_identity_id=other_rep,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert result.candidates[0].similarity == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_negative_cosines_preserve_values_and_none_band() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0, 0.0])))
    more_negative = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([-1.0, 0.0, 0.0])))
    less_negative = _cluster(
        tenant_id=tenant_id,
        label="Zed",
        embedding=_normalize(np.array([-0.2, np.sqrt(0.96), 0.0])),
    )

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, more_negative, less_negative]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert [row.cluster_id for row in result.candidates] == [str(less_negative.id), str(more_negative.id)]
    assert [row.similarity for row in result.candidates] == pytest.approx([-0.2, -1.0])
    assert [row.band for row in result.candidates] == [SimilarityBand.NONE, SimilarityBand.NONE]


@pytest.mark.asyncio
async def test_missing_centroid_omits_candidate() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0])))
    missing = _cluster(tenant_id=tenant_id, label="Ghost", embedding=None)
    kept = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([1.0, 0.0])))

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, missing, kept]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(missing.id),
                    similarity=0.99,
                    created_at=datetime.now(tz=UTC),
                )
            ]
        ),
        settings=ClusteringSettings(),
    )

    ids = {row.cluster_id for row in result.candidates}
    assert str(kept.id) in ids
    assert str(missing.id) not in ids
    assert str(probe.id) not in ids


@pytest.mark.asyncio
async def test_unlabeled_cluster_emits_empty_name() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label="Probe", embedding=_normalize(np.array([1.0, 0.0])))
    unlabeled = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0])))

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, unlabeled]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=ClusteringSettings(),
    )

    assert result.candidates[0].name == ""
    assert result.candidates[0].cluster_id == str(unlabeled.id)


@pytest.mark.asyncio
async def test_cross_space_candidate_is_omitted() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(
        tenant_id=tenant_id,
        label=None,
        embedding=_normalize(np.array([1.0, 0.0])),
        embedding_model="opencv-sface+cv5@128d/l2/cosine",
    )
    foreign = _cluster(
        tenant_id=tenant_id,
        label="Foreign",
        embedding=_normalize(np.array([1.0, 0.0])),
        embedding_model="buffalo_l@512d/l2/cosine",
    )

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, foreign]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=ClusteringSettings(),
    )

    assert result.candidates == []


@pytest.mark.asyncio
async def test_missing_probe_raises_lookup_error() -> None:
    tenant_id = str(uuid4())
    with pytest.raises(LookupError):
        await list_merge_candidates(
            tenant_id,
            str(uuid4()),
            cluster_repository=_FakeClusterRepo([]),
            merge_suggestion_repository=_FakeMergeRepo(),
            settings=ClusteringSettings(),
        )


@pytest.mark.asyncio
async def test_expired_and_non_pending_suggestions_are_ignored() -> None:
    tenant_id = str(uuid4())
    now = datetime.now(tz=UTC)
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0])), created_at=now)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([0.0, 1.0])), created_at=now)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(
            [
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.99,
                    created_at=now,
                    status=SuggestionStatus.REJECTED.value,
                ),
                _pending(
                    cluster_a_id=str(probe.id),
                    cluster_b_id=str(other.id),
                    similarity=0.98,
                    created_at=now,
                    expires_at=now - timedelta(hours=1),
                ),
            ]
        ),
        settings=ClusteringSettings(),
    )

    assert result.candidates[0].similarity == pytest.approx(
        compute_similarity(_normalize(np.array([1.0, 0.0])), _normalize(np.array([0.0, 1.0])))
    )


@pytest.mark.asyncio
async def test_probe_without_centroid_returns_empty_not_error() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=None)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([1.0, 0.0])))

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, other]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=ClusteringSettings(),
    )

    assert result.cluster_id == str(probe.id)
    assert result.candidates == []


@pytest.mark.asyncio
async def test_route_maps_ranked_payload_without_extra_fields() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0, 0.0])))
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([1.0, 0.0, 0.0])))

    payload = await merge_candidates_router.get_cluster_merge_candidates(
        cluster_id=str(probe.id),
        _tenant_id=tenant_id,
        cluster_repo=_FakeClusterRepo([probe, other]),
        merge_repo=_FakeMergeRepo(),
    )

    dumped = payload.model_dump()
    assert set(dumped) == {"cluster_id", "candidates"}
    assert dumped["cluster_id"] == str(probe.id)
    assert set(dumped["candidates"][0]) == {"cluster_id", "name", "similarity", "band"}
    assert dumped["candidates"][0]["name"] == "Ada"
    assert dumped["candidates"][0]["band"] == "strong"


def test_router_declares_get_merge_candidates_and_has_no_literal_cuts() -> None:
    routes = [(route.path, getattr(route, "methods", set())) for route in merge_candidates_router.router.routes]
    assert any(
        path.endswith("/clusters/{cluster_id}/merge-candidates") and "GET" in methods for path, methods in routes
    )
    source = Path(inspect.getsourcefile(merge_candidates_router)).read_text(encoding="utf-8")
    assert "0.35" not in source
    assert "0.55" not in source
    assert "0.30" not in source
    assert "list_merge_candidates" in source
    assert "band_for" not in source
