"""Rank other clusters as merge candidates for a probe cluster (GPUFLOW-2 B6)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from recognition.application.clustering.centroid_utils import compute_similarity
from recognition.application.settings import ClusteringSettings
from recognition.application.settings import clustering as clustering_settings
from recognition.application.suggestions.embedding_space import (
    cluster_embedding_model,
    models_are_same_space,
)
from recognition.application.suggestions.roster_candidates import SimilarityBand, band_for
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import ClusterRepository, MergeSuggestionRepository
from recognition.domain.suggestion import SuggestionStatus
from recognition.domain.suggestion_details import MergeSuggestionDetails

# GPUFLOW-2-C1-provisional-20260916 suggestion_band_cuts. svc-recovery-merge
# owns settings/clustering.py; read that constant when present.
SUGGESTION_BAND_CUTS: dict[str, float] = getattr(
    clustering_settings,
    "SUGGESTION_BAND_CUTS",
    {
        "low_confidence_floor": 0.30,
        "suggestion_floor": 0.35,
        "suggestion_ceiling": 0.55,
    },
)

_PAGE_SIZE = 1000


@dataclass(frozen=True)
class MergeCandidate:
    cluster_id: str
    name: str
    similarity: float
    band: SimilarityBand


@dataclass(frozen=True)
class MergeCandidatesResult:
    cluster_id: str
    candidates: list[MergeCandidate]


async def list_merge_candidates(
    tenant_id: str,
    cluster_id: str,
    *,
    cluster_repository: ClusterRepository,
    merge_suggestion_repository: MergeSuggestionRepository,
    settings: ClusteringSettings | None = None,
) -> MergeCandidatesResult:
    """Rank other clusters by max(centroid cosine, fresh pending suggestion).

    Band cuts come from injected ClusteringSettings (policy names
    suggestion_floor / suggestion_ceiling), not from literals in the HTTP route.
    Missing embeddings omit the candidate (rg-015).
    """
    inference_settings = settings or resolve_effective_clustering_settings()
    probe = await cluster_repository.get_by_id(cluster_id)
    if probe is None or probe.id is None or str(probe.tenant_id) != str(tenant_id):
        raise LookupError("cluster not found")
    clusters = await _list_tenant_clusters(cluster_repository, tenant_id)
    scored_probe = _cluster_by_id(clusters, str(probe.id)) or probe
    pending = await _list_pending_suggestions(merge_suggestion_repository, tenant_id)
    pending_by_peer = _fresh_pending_by_peer(pending, scored_probe, clusters)
    return MergeCandidatesResult(
        cluster_id=str(scored_probe.id),
        candidates=_rank_candidates(scored_probe, clusters, pending_by_peer, inference_settings),
    )


async def _list_tenant_clusters(cluster_repository: ClusterRepository, tenant_id: str) -> list[IdentityCluster]:
    collected: list[IdentityCluster] = []
    offset = 0
    while True:
        page = await cluster_repository.get_by_tenant(tenant_id, limit=_PAGE_SIZE, offset=offset)
        collected.extend(page)
        if len(page) < _PAGE_SIZE:
            return collected
        offset += _PAGE_SIZE


async def _list_pending_suggestions(
    repository: MergeSuggestionRepository, tenant_id: str
) -> list[MergeSuggestionDetails]:
    collected: list[MergeSuggestionDetails] = []
    offset = 0
    while True:
        page = await repository.list_pending_with_details(tenant_id, limit=_PAGE_SIZE, offset=offset)
        collected.extend(page)
        if len(page) < _PAGE_SIZE:
            return collected
        offset += _PAGE_SIZE


def _rank_candidates(
    probe: IdentityCluster,
    clusters: list[IdentityCluster],
    pending_by_peer: dict[str, float],
    settings: ClusteringSettings,
) -> list[MergeCandidate]:
    probe_id = str(probe.id)
    probe_centroid = _centroid_vector(probe)
    if probe_centroid is None:
        return []
    probe_model = cluster_embedding_model(probe)
    ranked: list[MergeCandidate] = []
    for cluster in clusters:
        candidate = _score_candidate(probe_id, probe_centroid, probe_model, cluster, pending_by_peer, settings)
        if candidate is not None:
            ranked.append(candidate)
    ranked.sort(key=lambda row: (-row.similarity, row.name.casefold(), row.cluster_id))
    return ranked


def _score_candidate(
    probe_id: str,
    probe_centroid: np.ndarray,
    probe_model: str | None,
    cluster: IdentityCluster,
    pending_by_peer: dict[str, float],
    settings: ClusteringSettings,
) -> MergeCandidate | None:
    other_id = str(cluster.id or "")
    if not other_id or other_id == probe_id:
        return None
    if not models_are_same_space(probe_model, cluster_embedding_model(cluster)):
        return None
    centroid = _centroid_vector(cluster)
    if centroid is None:
        return None
    similarity = float(compute_similarity(probe_centroid, centroid))
    pending_similarity = pending_by_peer.get(other_id)
    if pending_similarity is not None:
        similarity = max(similarity, pending_similarity)
    return MergeCandidate(
        cluster_id=other_id,
        name=_cluster_name(cluster),
        similarity=similarity,
        band=band_for(similarity, settings),
    )


def _fresh_pending_by_peer(
    pending: list[MergeSuggestionDetails],
    probe: IdentityCluster,
    clusters: list[IdentityCluster],
) -> dict[str, float]:
    probe_id = str(probe.id)
    by_id = {str(cluster.id): cluster for cluster in clusters if cluster.id}
    now = datetime.now(tz=UTC)
    best: dict[str, tuple[datetime, float]] = {}
    for row in pending:
        peer_id = _peer_id(row, probe_id)
        other = by_id.get(peer_id) if peer_id is not None else None
        observed = _suggestion_observed_at(row)
        if peer_id is None or other is None or observed is None:
            continue
        if not _is_usable_pending(row, now) or not _is_fresh(observed, probe, other):
            continue
        previous = best.get(peer_id)
        if (
            previous is None
            or observed > previous[0]
            or (observed == previous[0] and float(row.similarity) > previous[1])
        ):
            best[peer_id] = (observed, float(row.similarity))
    return {peer_id: similarity for peer_id, (_when, similarity) in best.items()}


def _is_usable_pending(row: MergeSuggestionDetails, now: datetime) -> bool:
    status = row.status
    status_value = status.value if isinstance(status, SuggestionStatus) else str(status)
    if status_value != SuggestionStatus.PENDING.value:
        return False
    expires_at = row.expires_at
    return expires_at is None or _as_utc(expires_at) >= now


def _is_fresh(observed: datetime, probe: IdentityCluster, other: IdentityCluster) -> bool:
    mutation = _latest_mutation(probe, other)
    return mutation is None or _as_utc(observed) >= mutation


def _latest_mutation(probe: IdentityCluster, other: IdentityCluster) -> datetime | None:
    stamps = [_as_utc(stamp) for stamp in (probe.created_at, other.created_at) if stamp is not None]
    return max(stamps) if stamps else None


def _suggestion_observed_at(row: MergeSuggestionDetails) -> datetime | None:
    refreshed = getattr(row, "refreshed_at", None)
    stamps = [stamp for stamp in (refreshed, row.created_at) if isinstance(stamp, datetime)]
    return max(_as_utc(stamp) for stamp in stamps) if stamps else None


def _peer_id(row: MergeSuggestionDetails, probe_id: str) -> str | None:
    probe = probe_id.lower()
    left = str(row.cluster_a_id)
    right = str(row.cluster_b_id)
    if left.lower() == probe:
        return right
    if right.lower() == probe:
        return left
    return None


def _cluster_by_id(clusters: list[IdentityCluster], cluster_id: str) -> IdentityCluster | None:
    for cluster in clusters:
        if str(cluster.id) == cluster_id:
            return cluster
    return None


def _cluster_name(cluster: IdentityCluster) -> str:
    label = cluster.label
    if label is None:
        return ""
    return str(label).strip()


def _centroid_vector(cluster: IdentityCluster) -> np.ndarray | None:
    centroid = cluster.centroid
    if centroid is None:
        return None
    vector = np.asarray(centroid, dtype=np.float32)
    if vector.size == 0:
        return None
    return vector


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
