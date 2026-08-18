"""Rank labelled roster clusters against an unlabeled probe cluster (UXW2-5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import numpy as np

from recognition.application.settings import ClusteringSettings
from recognition.application.similarity.search import SimilaritySearch
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.cluster import is_reserved_label_shape

DEFAULT_ROSTER_CANDIDATES_TOP_K = 10
MAX_ROSTER_CANDIDATES_TOP_K = 50


class SimilarityBand(StrEnum):
    """Server-side categorical match band. Never a calibrated probability."""

    STRONG = "strong"
    POSSIBLE = "possible"
    NONE = "none"


class QualityFlag(StrEnum):
    """Probe-face quality gate. Occlusion is reserved (never fabricated)."""

    OK = "ok"
    LOW_QUALITY = "low_quality"


@dataclass(frozen=True)
class RosterCandidateThresholds:
    suggestion_floor: float
    suggestion_ceiling: float
    similarity_threshold: float


@dataclass(frozen=True)
class RosterCandidate:
    cluster_id: str
    name: str
    similarity: float
    band: SimilarityBand
    quality_flag: QualityFlag


@dataclass(frozen=True)
class RosterCandidatesResult:
    model_id: str
    embedding_model: str
    computed_at: datetime
    reference_face_count: int
    thresholds: RosterCandidateThresholds
    candidates: list[RosterCandidate]


def band_for(similarity: float, settings: ClusteringSettings) -> SimilarityBand:
    """Map cosine to a live-settings band. strong ≥ ceiling, possible ∈ [floor, ceiling)."""
    if similarity >= settings.suggestion_ceiling:
        return SimilarityBand.STRONG
    if similarity >= settings.suggestion_floor:
        return SimilarityBand.POSSIBLE
    return SimilarityBand.NONE


def _rep_embedding_model(rep: Any) -> str | None:
    model = getattr(rep, "embedding_model", None)
    if model is None:
        identity = getattr(rep, "identity", None)
        if identity is not None:
            model = getattr(identity, "embedding_model", None)
    if model is None:
        return None
    return str(model)


def _rep_vector(rep: Any) -> np.ndarray | None:
    raw = getattr(rep, "embedding", None)
    if raw is None:
        return None
    vec = np.asarray(raw, dtype=np.float32)
    if vec.size == 0:
        return None
    return vec


def _probe_quality_flag(cluster: Any, settings: ClusteringSettings) -> QualityFlag:
    reps = getattr(cluster, "representatives", None) or []
    quality_floor = settings.fatal_quality_floor
    det_floor = settings.fatal_confidence_floor
    for rep in reps:
        quality = getattr(rep, "quality_score", None)
        metrics = getattr(rep, "debug_metrics", None) or {}
        landmark = metrics.get("landmark_quality") if isinstance(metrics, dict) else None
        det_score = metrics.get("det_score") if isinstance(metrics, dict) else None
        if quality is not None and float(quality) < quality_floor:
            return QualityFlag.LOW_QUALITY
        if landmark is not None and float(landmark) < quality_floor:
            return QualityFlag.LOW_QUALITY
        if det_score is not None and float(det_score) < det_floor:
            return QualityFlag.LOW_QUALITY
    return QualityFlag.OK


async def list_roster_candidates(
    tenant_id: str,
    cluster_id: str,
    *,
    cluster_repository: Any,
    settings: ClusteringSettings | None = None,
    top_k: int = DEFAULT_ROSTER_CANDIDATES_TOP_K,
) -> RosterCandidatesResult:
    """Max-cosine of probe reps vs each labelled cluster's same-space reps.

    Python has no person table: candidates are keyed by labelled ``cluster_id``
    + ``name`` (the cluster label). PHP maps ``cluster_id`` → ``roster_entry_id``.
    """
    inference_settings = settings or resolve_effective_clustering_settings()
    cluster = await cluster_repository.get_by_id(cluster_id)
    if cluster is None or str(getattr(cluster, "tenant_id", "")) != str(tenant_id):
        raise LookupError("cluster not found")

    probe_embeddings, probe_model = await cluster_repository.get_representative_embeddings_with_model(cluster_id)
    if not probe_embeddings:
        probe_embeddings, probe_model = await cluster_repository.get_member_fallback_embeddings_with_model(
            cluster_id, limit=4
        )

    thresholds = RosterCandidateThresholds(
        suggestion_floor=float(inference_settings.suggestion_floor),
        suggestion_ceiling=float(inference_settings.suggestion_ceiling),
        similarity_threshold=float(inference_settings.similarity_threshold),
    )
    computed_at = datetime.now(tz=UTC)
    model_id = probe_model or ""

    if not probe_embeddings or probe_model is None:
        return RosterCandidatesResult(
            model_id=model_id,
            embedding_model=model_id,
            computed_at=computed_at,
            reference_face_count=len(probe_embeddings),
            thresholds=thresholds,
            candidates=[],
        )

    labeled = await cluster_repository.get_labeled_with_representatives(str(tenant_id))
    reps_by_cluster: dict[str, list[np.ndarray]] = {}
    labels_by_cluster: dict[str, str] = {}
    for labeled_cluster, cluster_reps in labeled:
        labeled_id = str(getattr(labeled_cluster, "id", "") or "")
        if not labeled_id or labeled_id == str(cluster_id):
            continue
        label_value = getattr(labeled_cluster, "label", None)
        if not label_value or is_reserved_label_shape(label_value):
            continue
        same_space: list[np.ndarray] = []
        for rep in cluster_reps:
            if _rep_embedding_model(rep) != str(probe_model):
                continue
            vec = _rep_vector(rep)
            if vec is None:
                continue
            same_space.append(vec)
        if not same_space:
            continue
        reps_by_cluster[labeled_id] = same_space
        labels_by_cluster[labeled_id] = str(label_value)

    search = SimilaritySearch(inference_settings)
    best_by_cluster: dict[str, float] = {}
    for probe_vec in probe_embeddings:
        for match in search.find_all_matches(probe_vec, reps_by_cluster, min_similarity=0.0):
            previous = best_by_cluster.get(match.cluster_id)
            if previous is None or match.similarity > previous:
                best_by_cluster[match.cluster_id] = match.similarity

    quality_flag = _probe_quality_flag(cluster, inference_settings)
    ranked = sorted(best_by_cluster.items(), key=lambda item: item[1], reverse=True)
    candidates = [
        RosterCandidate(
            cluster_id=labeled_id,
            name=labels_by_cluster[labeled_id],
            similarity=similarity,
            band=band_for(similarity, inference_settings),
            quality_flag=quality_flag,
        )
        for labeled_id, similarity in ranked[:top_k]
    ]
    return RosterCandidatesResult(
        model_id=str(probe_model),
        embedding_model=str(probe_model),
        computed_at=computed_at,
        reference_face_count=len(probe_embeddings),
        thresholds=thresholds,
        candidates=candidates,
    )
