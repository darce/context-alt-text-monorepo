"""Cluster-to-cluster merge suggestion generation."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from itertools import combinations

import numpy as np

from recognition.application.clustering.centroid_utils import compute_similarity
from recognition.application.settings import ClusteringSettings
from recognition.application.settings.clustering import HACSettings
from recognition.application.suggestions.embedding_space import (
    cluster_embedding_model,
    models_are_same_space,
    representative_embedding_model,
)
from recognition.domain.cluster import IdentityCluster, is_reserved_label_shape
from recognition.domain.repositories import (
    ClusterRepository,
    ConstrainedHACProtocol,
    MergeSuggestionCreateData,
    MergeSuggestionRepository,
)
from recognition.shared.similarity import normalize_face_embedding

logger = logging.getLogger(__name__)


class MergeSuggestionService:
    """Generate merge suggestions for similar cluster pairs."""

    def __init__(
        self,
        repository: MergeSuggestionRepository,
        *,
        cluster_repository: ClusterRepository,
        settings: ClusteringSettings,
    ) -> None:
        """Initialize the merge suggestion service.

        Args:
            repository: Persistence for merge suggestions.
            cluster_repository: Source of cluster data to evaluate.
            settings: Clustering thresholds to apply.
        """
        self._repository = repository
        self._cluster_repository = cluster_repository
        self._settings = settings

    async def generate_for_tenant(self, tenant_id: str, *, limit: int = 1000) -> int:
        """Generate merge suggestions for a tenant.

        Args:
            tenant_id: Tenant UUID string.
            limit: Maximum clusters to evaluate.

        Returns:
            Number of suggestions created or updated.
        """
        clusters = await self._cluster_repository.get_by_tenant(tenant_id, limit=limit)
        return await generate_cluster_merge_suggestions(
            tenant_id=tenant_id,
            clusters=clusters,
            repository=self._repository,
            settings=self._settings,
        )

    async def generate_singleton_merge_suggestions(
        self,
        tenant_id: str,
        *,
        constrained_hac: ConstrainedHACProtocol | None,
        hac_settings: HACSettings | None,
        limit: int = 1000,
    ) -> int:
        """Generate merge suggestions for singleton clusters using HAC grouping."""
        if constrained_hac is None or hac_settings is None:
            return 0

        limit = max(limit, hac_settings.max_scope_size)
        clusters = await self._cluster_repository.get_by_tenant(tenant_id, limit=limit)

        singleton_candidates: list[tuple[IdentityCluster, str, np.ndarray, str | None]] = []
        for cluster in clusters:
            if cluster.identity_count != 1 or not _is_eligible_for_merge_suggestion(cluster, tenant_id):
                continue
            cluster_id = cluster.id
            if cluster_id is None:
                continue
            identity_id, embedding = _extract_singleton_identity_embedding(cluster)
            if not identity_id or embedding is None:
                logger.debug(
                    "[merge_suggestions] singleton_skip cluster_id=%s missing_embedding=%s",
                    cluster_id,
                    embedding is None,
                )
                continue
            singleton_candidates.append(
                (cluster, identity_id, embedding, _singleton_embedding_model(cluster, identity_id))
            )

        if len(singleton_candidates) < 2:
            return 0

        if len(singleton_candidates) > hac_settings.max_scope_size:
            singleton_candidates.sort(
                key=lambda item: item[0].created_at.timestamp() if item[0].created_at else 0.0,
                reverse=True,
            )
            singleton_candidates = singleton_candidates[: hac_settings.max_scope_size]
            logger.info(
                "[merge_suggestions] singleton_scope_trimmed=%d max_scope=%d tenant_id=%s",
                len(singleton_candidates),
                hac_settings.max_scope_size,
                tenant_id,
            )

        embeddings: dict[uuid.UUID, np.ndarray] = {}
        identity_to_cluster: dict[uuid.UUID, IdentityCluster] = {}
        identity_models: dict[uuid.UUID, str | None] = {}
        for cluster, identity_id, embedding, embedding_model in singleton_candidates:
            try:
                identity_uuid = uuid.UUID(identity_id)
            except ValueError:
                logger.debug("[merge_suggestions] singleton_skip invalid_identity_id=%s", identity_id)
                continue
            embeddings[identity_uuid] = normalize_face_embedding(np.array(embedding, dtype=np.float32))
            identity_models[identity_uuid] = embedding_model
            if cluster.id is not None:
                identity_to_cluster[identity_uuid] = cluster

        if len(embeddings) < 2:
            return 0

        hac_clusters = await constrained_hac.refine_clusters(
            tenant_id=uuid.UUID(tenant_id),
            embeddings=embeddings,
        )

        groups: dict[uuid.UUID, list[uuid.UUID]] = {}
        for identity_uuid, group_uuid in hac_clusters.items():
            if identity_uuid in identity_to_cluster:
                groups.setdefault(group_uuid, []).append(identity_uuid)

        created = 0
        now = datetime.now(tz=UTC)
        for group in groups.values():
            if len(group) < 2:
                continue
            for identity_a, identity_b in combinations(group, 2):
                cluster_a = identity_to_cluster.get(identity_a)
                cluster_b = identity_to_cluster.get(identity_b)
                if cluster_a is None or cluster_b is None or cluster_a.id is None or cluster_b.id is None:
                    continue
                if not _is_merge_pair_eligible(cluster_a, cluster_b):
                    continue
                if not models_are_same_space(identity_models.get(identity_a), identity_models.get(identity_b)):
                    continue
                similarity = compute_similarity(embeddings[identity_a], embeddings[identity_b])
                if similarity < self._settings.suggestion_floor:
                    continue
                if similarity >= self._settings.similarity_threshold:
                    continue
                payload = _merge_suggestion_payload(
                    cluster_a,
                    cluster_b,
                    similarity=similarity,
                    source="singleton_hac",
                    refreshed_at=now,
                )
                await self._repository.upsert_pending(tenant_id, payload)
                created += 1

        if created:
            logger.info(
                "[merge_suggestions] Generated %d singleton HAC suggestions (tenant_id=%s)",
                created,
                tenant_id,
            )
        return created

    async def delete_by_cluster(self, tenant_id: str, cluster_id: str) -> int:
        """Delete pending merge suggestions involving the provided cluster."""
        return await self._repository.delete_by_cluster(tenant_id, cluster_id)


async def generate_cluster_merge_suggestions(
    *,
    tenant_id: str,
    clusters: Sequence[IdentityCluster],
    repository: MergeSuggestionRepository,
    settings: ClusteringSettings,
) -> int:
    """Generate cluster-to-cluster merge suggestions from centroid similarity.

    Args:
        tenant_id: Tenant UUID string.
        clusters: Clusters to evaluate for merge suggestions.
        repository: Persistence for merge suggestions.
        settings: Clustering thresholds to apply.

    Returns:
        Number of suggestions created or updated.
    """
    if not clusters:
        return 0

    candidates: list[tuple[IdentityCluster, np.ndarray]] = []
    for cluster in clusters:
        cluster_id = cluster.id
        if not cluster_id:
            continue
        if not _is_eligible_for_merge_suggestion(cluster, tenant_id):
            continue
        centroid = _extract_cluster_centroid(cluster)
        if centroid is None:
            continue
        candidates.append((cluster, centroid))

    if len(candidates) < 2:
        logger.debug("[merge_suggestions] No eligible cluster pairs for tenant_id=%s", tenant_id)
        return 0

    created = 0
    now = datetime.now(tz=UTC)
    for idx, (cluster_a, centroid_a) in enumerate(candidates):
        for cluster_b, centroid_b in candidates[idx + 1 :]:
            if not _is_merge_pair_eligible(cluster_a, cluster_b):
                continue
            if not models_are_same_space(cluster_embedding_model(cluster_a), cluster_embedding_model(cluster_b)):
                continue
            similarity = compute_similarity(centroid_a, centroid_b)
            if similarity < settings.suggestion_floor:
                continue
            if similarity >= settings.similarity_threshold:
                continue

            payload = _merge_suggestion_payload(
                cluster_a,
                cluster_b,
                similarity=similarity,
                source="cluster_merge",
                refreshed_at=now,
            )
            await repository.upsert_pending(tenant_id, payload)
            created += 1

    logger.info(
        "[merge_suggestions] Generated %d merge suggestions (clusters=%d tenant_id=%s)",
        created,
        len(candidates),
        tenant_id,
    )
    return created


def _is_eligible_for_merge_suggestion(cluster: IdentityCluster, tenant_id: str) -> bool:
    """Return whether a cluster may participate in merge-suggestion pairing.

    Tenant mismatch is excluded. Labeled vs unlabeled is decided at pair
    level: a pair is suggestible when similarity is in band and at most one
    side is user-confirmed with a non-reserved (non-``cluster-``/``cluster_``)
    label.
    """
    return not (cluster.tenant_id and cluster.tenant_id.lower() != tenant_id.lower())


def _is_labeled_for_merge_suggestion(cluster: IdentityCluster) -> bool:
    """Return True when the cluster is user-confirmed with a real (non-auto) label."""
    label = cluster.label
    return bool(cluster.user_confirmed and label and not is_reserved_label_shape(label))


def _is_merge_pair_eligible(cluster_a: IdentityCluster, cluster_b: IdentityCluster) -> bool:
    """A pair is suggestible unless both sides are labeled."""
    return not (_is_labeled_for_merge_suggestion(cluster_a) and _is_labeled_for_merge_suggestion(cluster_b))


def _merge_pair_cluster_ids(cluster_a: IdentityCluster, cluster_b: IdentityCluster) -> tuple[str, str]:
    """Return (survivor_id, other_id). Labeled side is the survivor when exactly one is labeled."""
    cluster_a_id = cluster_a.id
    cluster_b_id = cluster_b.id
    if cluster_a_id is None or cluster_b_id is None:
        raise ValueError("merge pair requires cluster ids")
    if _is_labeled_for_merge_suggestion(cluster_b) and not _is_labeled_for_merge_suggestion(cluster_a):
        return cluster_b_id, cluster_a_id
    return cluster_a_id, cluster_b_id


def _merge_suggestion_payload(
    cluster_a: IdentityCluster,
    cluster_b: IdentityCluster,
    *,
    similarity: float,
    source: str,
    refreshed_at: datetime,
) -> MergeSuggestionCreateData:
    survivor_id, other_id = _merge_pair_cluster_ids(cluster_a, cluster_b)
    exactly_one_labeled = _is_labeled_for_merge_suggestion(cluster_a) != _is_labeled_for_merge_suggestion(cluster_b)
    return MergeSuggestionCreateData(
        cluster_a_id=survivor_id,
        cluster_b_id=other_id,
        similarity=similarity,
        source=source,
        refreshed_at=refreshed_at,
        survivor_cluster_id=survivor_id if exactly_one_labeled else None,
    )


def _extract_cluster_centroid(cluster: IdentityCluster) -> np.ndarray | None:
    rep_count = len(cluster.representatives or [])
    logger.debug(
        "[merge_suggestions] centroid_lookup cluster_id=%s has_centroid=%s rep_count=%d",
        cluster.id,
        cluster.centroid is not None,
        rep_count,
    )
    if cluster.centroid is not None:
        return np.array(cluster.centroid, dtype=np.float32)
    return None


def _extract_singleton_identity_embedding(cluster: IdentityCluster) -> tuple[str | None, np.ndarray | None]:
    identity_id = cluster.representative_identity_id
    embedding: np.ndarray | None = None
    if cluster.centroid is not None:
        embedding = np.array(cluster.centroid, dtype=np.float32)

    reps = list(cluster.representatives or [])
    if identity_id:
        for rep in reps:
            if rep.identity_id == identity_id and rep.embedding is not None:
                if embedding is None:
                    embedding = np.array(rep.embedding, dtype=np.float32)
                return identity_id, embedding

    for rep in reps:
        if rep.embedding is not None:
            identity_id = rep.identity_id
            if embedding is None:
                embedding = np.array(rep.embedding, dtype=np.float32)
            return identity_id, embedding

    return identity_id, embedding


def _singleton_embedding_model(cluster: IdentityCluster, identity_id: str) -> str | None:
    """Resolve the singleton face's embedding space from loaded reps, else cluster."""
    for rep in list(cluster.representatives or []):
        if rep.identity_id == identity_id:
            model = representative_embedding_model(rep)
            if model is not None:
                return model
    return cluster_embedding_model(cluster)


__all__ = ["MergeSuggestionService", "generate_cluster_merge_suggestions"]
