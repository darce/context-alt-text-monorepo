"""Rank labelled roster clusters against an unlabeled probe cluster (UXW2-5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import numpy as np

from recognition.application.settings import ClusteringSettings
from recognition.application.similarity.search import SimilaritySearch
from recognition.application.suggestions.embedding_space import (
    models_are_same_space,
    representative_embedding_model,
    representative_vector,
)
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.cluster import is_reserved_label_shape
from recognition.domain.repositories import ClusterRepository

DEFAULT_ROSTER_CANDIDATES_TOP_K = 10
MAX_ROSTER_CANDIDATES_TOP_K = 50
# Cosine can be negative; contract band none = below floor, so do not drop < 0.
_MIN_RANK_SIMILARITY = -1.0


class SimilarityBand(StrEnum):
    """Server-side categorical match band. Never a calibrated probability."""

    STRONG = "strong"
    POSSIBLE = "possible"
    NONE = "none"


class QualityFlag(StrEnum):
    """Probe-face quality gate.

    ``occluded`` is reserved (EMB-11; never fabricated). Unknown values must be
    treated as ``low_quality``.
    """

    OK = "ok"
    LOW_QUALITY = "low_quality"
    OCCLUDED = "occluded"


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


@dataclass(frozen=True)
class RosterCandidatesResult:
    model_id: str
    embedding_model: str
    computed_at: datetime
    probe_face_count: int
    reference_face_count: int
    quality_flag: QualityFlag
    thresholds: RosterCandidateThresholds
    candidates: list[RosterCandidate]


def band_for(similarity: float, settings: ClusteringSettings) -> SimilarityBand:
    """Map cosine to a live-settings band. strong ≥ ceiling, possible ∈ [floor, ceiling)."""
    if similarity >= settings.suggestion_ceiling:
        return SimilarityBand.STRONG
    if similarity >= settings.suggestion_floor:
        return SimilarityBand.POSSIBLE
    return SimilarityBand.NONE


def _capped_band(
    similarity: float, settings: ClusteringSettings, quality_flag: QualityFlag
) -> SimilarityBand:
    """Low-quality probes must not surface Strong (FE must not show Strong for a bad probe)."""
    band = band_for(similarity, settings)
    if quality_flag is not QualityFlag.OK and band is SimilarityBand.STRONG:
        return SimilarityBand.POSSIBLE
    return band


def _quality_flag_from_samples(
    samples: list[tuple[float | None, float | None, float | None]],
    settings: ClusteringSettings,
) -> QualityFlag:
    """Fail closed: missing metrics → low_quality. Any below-floor metric → low_quality."""
    if not samples:
        return QualityFlag.LOW_QUALITY
    quality_floor = settings.fatal_quality_floor
    det_floor = settings.fatal_confidence_floor
    saw_metric = False
    for quality, landmark, det_score in samples:
        if quality is not None:
            saw_metric = True
            if float(quality) < quality_floor:
                return QualityFlag.LOW_QUALITY
        if landmark is not None:
            saw_metric = True
            if float(landmark) < quality_floor:
                return QualityFlag.LOW_QUALITY
        if det_score is not None:
            saw_metric = True
            if float(det_score) < det_floor:
                return QualityFlag.LOW_QUALITY
    if not saw_metric:
        return QualityFlag.LOW_QUALITY
    return QualityFlag.OK


async def _load_probe_faces(
    cluster_repository: ClusterRepository, cluster_id: str
) -> tuple[list[np.ndarray], str | None, list[tuple[float | None, float | None, float | None]]]:
    """Load ranking rows + quality from the ClusterRepository protocol loaders."""
    embeddings, model, qualities = await cluster_repository.get_representative_embeddings_with_quality(cluster_id)
    if embeddings:
        return embeddings, model, qualities
    return await cluster_repository.get_member_fallback_embeddings_with_quality(cluster_id, limit=4)


def _vector_dim(vec: np.ndarray) -> int:
    arr = np.asarray(vec)
    if arr.ndim == 0:
        return 0
    return int(arr.shape[-1])


async def list_roster_candidates(
    tenant_id: str,
    cluster_id: str,
    *,
    cluster_repository: ClusterRepository,
    settings: ClusteringSettings | None = None,
    top_k: int = DEFAULT_ROSTER_CANDIDATES_TOP_K,
) -> RosterCandidatesResult:
    """Max-cosine of probe reps vs each labelled cluster's same-space reps.

    Python has no person table: candidates are keyed by labelled ``cluster_id``
    + ``name`` (the cluster label). PHP maps ``cluster_id`` → ``roster_entry_id``
    and collapses to one row per person.
    """
    inference_settings = settings or resolve_effective_clustering_settings()
    cluster = await cluster_repository.get_by_id(cluster_id)
    if cluster is None or str(getattr(cluster, "tenant_id", "")) != str(tenant_id):
        raise LookupError("cluster not found")

    probe_embeddings, probe_model, probe_qualities = await _load_probe_faces(
        cluster_repository, cluster_id
    )

    thresholds = RosterCandidateThresholds(
        suggestion_floor=float(inference_settings.suggestion_floor),
        suggestion_ceiling=float(inference_settings.suggestion_ceiling),
        similarity_threshold=float(inference_settings.similarity_threshold),
    )
    computed_at = datetime.now(tz=UTC)
    model_id = probe_model or ""

    usable_probes: list[np.ndarray] = []
    usable_qualities: list[tuple[float | None, float | None, float | None]] = []
    if probe_embeddings:
        probe_dim = _vector_dim(probe_embeddings[0])
        aligned = list(probe_qualities) + [(None, None, None)] * max(
            0, len(probe_embeddings) - len(probe_qualities)
        )
        for vec, sample in zip(probe_embeddings, aligned, strict=False):
            if probe_dim > 0 and _vector_dim(vec) == probe_dim:
                usable_probes.append(vec)
                usable_qualities.append(sample)
    quality_flag = _quality_flag_from_samples(usable_qualities, inference_settings)

    if not usable_probes:
        return RosterCandidatesResult(
            model_id=model_id,
            embedding_model=model_id,
            computed_at=computed_at,
            probe_face_count=len(usable_probes),
            reference_face_count=0,
            quality_flag=quality_flag,
            thresholds=thresholds,
            candidates=[],
        )

    probe_dim = _vector_dim(usable_probes[0])
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
            if not models_are_same_space(probe_model, representative_embedding_model(rep)):
                continue
            vec = representative_vector(rep)
            if vec is None or _vector_dim(vec) != probe_dim:
                continue
            same_space.append(vec)
        if not same_space:
            continue
        reps_by_cluster[labeled_id] = same_space
        labels_by_cluster[labeled_id] = str(label_value)

    reference_face_count = sum(len(vecs) for vecs in reps_by_cluster.values())
    search = SimilaritySearch(inference_settings)
    best_by_cluster: dict[str, float] = {}
    for probe_vec in usable_probes:
        for match in search.find_all_matches(
            probe_vec, reps_by_cluster, min_similarity=_MIN_RANK_SIMILARITY
        ):
            previous = best_by_cluster.get(match.cluster_id)
            if previous is None or match.similarity > previous:
                best_by_cluster[match.cluster_id] = match.similarity

    ranked = sorted(
        (
            (cluster_id, best_by_cluster[cluster_id])
            for cluster_id in reps_by_cluster
            if cluster_id in best_by_cluster
        ),
        key=lambda item: (-item[1], item[0]),
    )
    candidates = [
        RosterCandidate(
            cluster_id=labeled_id,
            name=labels_by_cluster[labeled_id],
            similarity=similarity,
            band=_capped_band(similarity, inference_settings, quality_flag),
        )
        for labeled_id, similarity in ranked[:top_k]
    ]
    return RosterCandidatesResult(
        model_id=str(probe_model),
        embedding_model=str(probe_model),
        computed_at=computed_at,
        probe_face_count=len(usable_probes),
        reference_face_count=reference_face_count,
        quality_flag=quality_flag,
        thresholds=thresholds,
        candidates=candidates,
    )
