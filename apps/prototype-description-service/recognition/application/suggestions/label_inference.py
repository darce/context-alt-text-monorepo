"""
Label inference service for proactive suggestions.
"""

from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, MediaIdentity
from recognition.application.settings import ClusteringSettings
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.repositories import ClusterRepository
from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource


async def infer_suggested_label(
    tenant_id: str,
    cluster_id: str,
    *,
    session: AsyncSession,
    cluster_repository: ClusterRepository | None = None,
    settings: ClusteringSettings | None = None,
) -> SuggestedLabel | None:
    """Infer a label for a cluster based on available signals.

    Source priority:
    1. Identity match (if suggestion links to known identity) - (Not implemented: requires user feedback loop awareness)
    2. Roster entry (via Identity) - (Skipped: RosterEntry does not exist in MVP)
    3. Similar cluster (nearest labeled cluster) - Implemented here.

    Args:
        tenant_id: Tenant ID
        cluster_id: Cluster ID (The unlabeled cluster we are trying to label)
        session: Database session

    Returns:
        SuggestedLabel or None if no reliable inference found.
    """
    inference_settings = settings or resolve_effective_clustering_settings()
    threshold = inference_settings.suggestion_floor

    try:
        tenant_uuid = uuid.UUID(tenant_id)
        cluster_uuid = uuid.UUID(cluster_id)
    except ValueError:
        return None

    # Fetch target cluster state first. We can infer from member suggestion signals
    # even when representative linkage is missing.
    stmt_target = (
        select(IdentityCluster)
        .options(joinedload(IdentityCluster.representative_identity))
        .where(IdentityCluster.id == cluster_uuid)
        .where(IdentityCluster.tenant_id == tenant_uuid)
    )
    result_target = await session.execute(stmt_target)
    target_cluster = result_target.scalar_one_or_none()

    if not target_cluster:
        return None

    # 1. Identity Match (via IdentitySuggestion), including accepted suggestions.
    # If a member already has an accepted suggestion to a labeled cluster, surface it
    # immediately as the strongest signal for top-unlabeled CTA enrichment.
    from db.models.constraints import IdentitySuggestion
    from db.models.identity import IdentityMember

    accepted_first = case((IdentitySuggestion.resolution == "accepted", 0), else_=1)
    stmt_identity = (
        select(IdentitySuggestion, IdentityCluster)
        .join(IdentityCluster, IdentitySuggestion.suggested_cluster_id == IdentityCluster.id)
        .join(IdentityMember, IdentitySuggestion.identity_id == IdentityMember.identity_id)
        .where(IdentitySuggestion.tenant_id == tenant_uuid)
        .where(IdentitySuggestion.resolution.in_(("accepted", "pending")))
        .where(IdentityMember.cluster_id == cluster_uuid)
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .where(~IdentityCluster.label.startswith("cluster-"))
        .where(IdentityCluster.id != cluster_uuid)
        .order_by(accepted_first, IdentitySuggestion.confidence_score.desc())
        .limit(1)
    )

    result_identity = await session.execute(stmt_identity)
    identity_match = result_identity.first()

    if identity_match:
        suggestion, other_cluster = identity_match
        # Accepted suggestions are explicit outcomes, so we honor them regardless of
        # confidence threshold. Pending suggestions still require threshold gating.
        if suggestion.resolution == "accepted" or suggestion.confidence_score >= threshold:
            return SuggestedLabel(
                label=other_cluster.label,
                source=SuggestedLabelSource.IDENTITY,
                confidence=suggestion.confidence_score,
                target_cluster_id=str(other_cluster.id),
            )

    # 1b. Roster Entry Match
    if target_cluster.roster_id:
        if cluster_repository is None:
            return None

        roster_name = await cluster_repository.get_roster_entry_name(str(target_cluster.roster_id))
        if roster_name:
            return SuggestedLabel(label=roster_name, source=SuggestedLabelSource.ROSTER, confidence=1.0)
        return None

    # 2. Merge Suggestions (Preferred Provenance for Similar Cluster)
    # Check if there is a pending merge suggestion with a labeled cluster
    from db.models.constraints import ClusterMergeSuggestion

    stmt_merge = (
        select(ClusterMergeSuggestion, IdentityCluster)
        .join(
            IdentityCluster,
            (
                (ClusterMergeSuggestion.cluster_a_id == IdentityCluster.id)
                & (ClusterMergeSuggestion.cluster_b_id == cluster_uuid)
            )
            | (
                (ClusterMergeSuggestion.cluster_b_id == IdentityCluster.id)
                & (ClusterMergeSuggestion.cluster_a_id == cluster_uuid)
            ),
        )
        .where(ClusterMergeSuggestion.tenant_id == tenant_uuid)
        .where(ClusterMergeSuggestion.resolution == "pending")
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .order_by(ClusterMergeSuggestion.similarity.desc())
        .limit(1)
    )

    result_merge = await session.execute(stmt_merge)
    merge_match = result_merge.first()

    if merge_match:
        suggestion, other_cluster = merge_match
        if suggestion.similarity >= threshold:
            return SuggestedLabel(
                label=other_cluster.label,
                source=SuggestedLabelSource.SIMILAR_CLUSTER,
                confidence=suggestion.similarity,
                target_cluster_id=str(other_cluster.id),
            )

    # 3. Nearest Neighbor Search (Fallback)
    # FIR23-01: resolve the query face's embedding_model before any NN path so
    # both in-process and SQL candidates stay in one space.
    rep_identity = target_cluster.representative_identity
    target_model = getattr(rep_identity, "embedding_model", None) if rep_identity is not None else None

    target_embedding: np.ndarray | None = None
    embedding = (
        getattr(target_cluster.representative_identity, "embedding", None)
        if target_cluster.representative_identity is not None
        else None
    )
    if embedding is not None:
        target_embedding = np.asarray(embedding, dtype=np.float32)
    else:
        if cluster_repository is None:
            return None
        reps = await cluster_repository.get_representative_embeddings(cluster_id)
        if not reps:
            reps = await cluster_repository.get_member_fallback_embeddings(cluster_id, limit=4)
        if reps:
            rep_stack = np.asarray(reps, dtype=np.float32)
            target_embedding = rep_stack.mean(axis=0)
        else:
            return None

    # Prefer in-process similarity search using representative sets when available to avoid
    # vector index constraints and to honor representative table embeddings.
    # FIR23-01: restrict candidates to the query face's embedding_model. Domain
    # representatives drop embedding_model, so resolve same-space identity ids via
    # session when target_model is known. Fall through to the SQL path when
    # in-process finds nothing under a model predicate (do not shadow FIR23-01).
    if cluster_repository is not None:
        same_model_identity_ids: set[str] | None = None
        if target_model is not None:
            model_ids_result = await session.execute(
                select(MediaIdentity.id).where(
                    MediaIdentity.tenant_id == tenant_uuid,
                    MediaIdentity.embedding_model == target_model,
                )
            )
            same_model_identity_ids = {str(row) for row in model_ids_result.scalars().all()}

        labeled_clusters = await cluster_repository.get_labeled_with_representatives(str(tenant_uuid))
        best_similarity = -1.0
        best_cluster_id: str | None = None
        for labeled_cluster, cluster_reps in labeled_clusters:
            if not labeled_cluster.id or labeled_cluster.id == str(cluster_uuid):
                continue
            label_value = labeled_cluster.label
            if not label_value or label_value.startswith("cluster-"):
                continue
            for rep in cluster_reps:
                if same_model_identity_ids is not None:
                    rep_model = getattr(rep, "embedding_model", None)
                    if rep_model is None:
                        identity = getattr(rep, "identity", None)
                        if identity is not None:
                            rep_model = getattr(identity, "embedding_model", None)
                    if rep_model is not None:
                        if str(rep_model) != str(target_model):
                            continue
                    else:
                        identity_id = getattr(rep, "identity_id", None)
                        if identity_id is None or str(identity_id) not in same_model_identity_ids:
                            continue
                rep_vec = np.asarray(getattr(rep, "embedding", rep), dtype=np.float32)
                norm_a = np.linalg.norm(target_embedding)
                norm_b = np.linalg.norm(rep_vec)
                if norm_a == 0 or norm_b == 0:
                    continue
                similarity = float(np.dot(target_embedding, rep_vec) / (norm_a * norm_b))
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_cluster_id = labeled_cluster.id

        if best_cluster_id is not None and best_similarity >= threshold:
            label_value = next(
                (c.label for c, _ in labeled_clusters if c.id == best_cluster_id and c.label),
                None,
            )
            if not label_value:
                return None
            return SuggestedLabel(
                label=label_value,
                source=SuggestedLabelSource.SIMILAR_CLUSTER,
                confidence=best_similarity,
                target_cluster_id=best_cluster_id,
            )

        # In-process miss. When no embedding_model predicate applies, keep prior
        # exclusive in-process behaviour. When a model is known, continue to SQL.
        if target_model is None:
            return None

    # Find nearest labeled cluster using embedding distance (DB fallback).
    # FIR23-01: restrict to the same embedding_model as the query face so
    # mixed-model rows cannot win nearest-neighbor. Single-model tenants are a
    # no-op (predicate matches every candidate).
    # pgvector cosine_distance is unavailable on SQLite unit/integration DBs.
    from recognition.shared.db.dialect import is_sqlite

    if is_sqlite(session):
        return None

    stmt = (
        select(IdentityCluster)
        .join(MediaIdentity, IdentityCluster.representative_identity_id == MediaIdentity.id)
        .where(IdentityCluster.tenant_id == tenant_uuid)
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .where(IdentityCluster.id != cluster_uuid)
        .where(MediaIdentity.embedding.isnot(None))
    )
    if target_model is not None:
        stmt = stmt.where(MediaIdentity.embedding_model == target_model)
    stmt = (
        stmt.order_by(MediaIdentity.embedding.cosine_distance(target_embedding))
        .limit(1)
        .options(joinedload(IdentityCluster.representative_identity))
    )

    result = await session.execute(stmt)
    nearest_cluster = result.scalar_one_or_none()

    nearest_embedding = (
        getattr(nearest_cluster.representative_identity, "embedding", None)
        if nearest_cluster and nearest_cluster.representative_identity
        else None
    )
    if nearest_cluster and nearest_embedding is not None:
        vec_a = np.array(target_embedding)
        vec_b = np.array(nearest_embedding)

        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)

        if norm_a > 0 and norm_b > 0:
            similarity = float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

            if similarity >= threshold and nearest_cluster.label:
                return SuggestedLabel(
                    label=nearest_cluster.label,
                    source=SuggestedLabelSource.SIMILAR_CLUSTER,
                    confidence=similarity,
                    target_cluster_id=str(nearest_cluster.id),
                )

    return None
