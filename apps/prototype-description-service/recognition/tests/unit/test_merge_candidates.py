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
from recognition.application.suggestions.merge_candidates import (
    SUGGESTION_BAND_CUTS,
    list_merge_candidates,
)
from recognition.application.suggestions.roster_candidates import SimilarityBand, band_for
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
    cluster_id: str | None = None,
    embedding_model: str | None = None,
) -> IdentityCluster:
    centroid = compute_centroid([embedding]) if embedding is not None else None
    return IdentityCluster(
        id=cluster_id or str(generate_id()),
        tenant_id=tenant_id,
        label=label,
        is_labeled=bool(label),
        identity_count=1 if embedding is not None else 0,
        created_at=created_at or datetime.now(tz=UTC),
        centroid=centroid,
        embedding_model=embedding_model,
    )


def _pending(
    *,
    cluster_a_id: str,
    cluster_b_id: str,
    similarity: float,
    created_at: datetime,
    status: str = SuggestionStatus.PENDING.value,
    expires_at: datetime | None = None,
) -> MergeSuggestionDetails:
    left, right = sorted((cluster_a_id, cluster_b_id))
    return MergeSuggestionDetails(
        id=str(generate_id()),
        cluster_a_id=left,
        cluster_b_id=right,
        similarity=similarity,
        status=status,
        created_at=created_at,
        expires_at=expires_at,
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


def test_suggestion_band_cuts_use_calibration_policy_names() -> None:
    assert set(SUGGESTION_BAND_CUTS) == {
        "low_confidence_floor",
        "suggestion_floor",
        "suggestion_ceiling",
    }
    settings = ClusteringSettings(
        suggestion_floor=SUGGESTION_BAND_CUTS["suggestion_floor"],
        suggestion_ceiling=SUGGESTION_BAND_CUTS["suggestion_ceiling"],
    )
    assert band_for(SUGGESTION_BAND_CUTS["suggestion_ceiling"], settings) is SimilarityBand.STRONG
    assert band_for(SUGGESTION_BAND_CUTS["suggestion_floor"], settings) is SimilarityBand.POSSIBLE
    assert band_for(SUGGESTION_BAND_CUTS["suggestion_floor"] - 0.01, settings) is SimilarityBand.NONE


@pytest.mark.asyncio
async def test_bands_come_from_injected_settings_not_hardcoded() -> None:
    tenant_id = str(uuid4())
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=_normalize(np.array([1.0, 0.0, 0.0])))
    strong = _cluster(tenant_id=tenant_id, label="Ada", embedding=_normalize(np.array([1.0, 0.0, 0.0])))
    possible = _cluster(tenant_id=tenant_id, label="Bea", embedding=_normalize(np.array([0.55, 0.835, 0.0])))
    none = _cluster(tenant_id=tenant_id, label="Cyd", embedding=_normalize(np.array([0.0, 1.0, 0.0])))
    settings = ClusteringSettings(suggestion_floor=0.40, suggestion_ceiling=0.80)

    result = await list_merge_candidates(
        tenant_id,
        str(probe.id),
        cluster_repository=_FakeClusterRepo([probe, strong, possible, none]),
        merge_suggestion_repository=_FakeMergeRepo(),
        settings=settings,
    )

    bands = {row.cluster_id: row.band for row in result.candidates}
    assert bands[str(strong.id)] is SimilarityBand.STRONG
    assert bands[str(possible.id)] is SimilarityBand.POSSIBLE
    assert bands[str(none.id)] is SimilarityBand.NONE


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

    assert [row.cluster_id for row in result.candidates] == [str(best.id), str(ada.id), str(zed.id)]
    assert result.cluster_id == str(probe.id)


@pytest.mark.asyncio
async def test_similarity_is_max_of_centroid_and_fresh_pending() -> None:
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
async def test_stale_pending_suggestion_is_ignored() -> None:
    tenant_id = str(uuid4())
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 6, 1, tzinfo=UTC)
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    other_vec = _normalize(np.array([0.0, 1.0, 0.0]))
    probe = _cluster(tenant_id=tenant_id, label=None, embedding=probe_vec, created_at=newer)
    other = _cluster(tenant_id=tenant_id, label="Ada", embedding=other_vec, created_at=newer)

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
                    created_at=older,
                )
            ]
        ),
        settings=ClusteringSettings(suggestion_floor=0.35, suggestion_ceiling=0.55),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].similarity == pytest.approx(compute_similarity(probe_vec, other_vec))
    assert result.candidates[0].band is SimilarityBand.NONE


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
