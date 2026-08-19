"""
Label inference service for proactive suggestions.
"""

from __future__ import annotations

import logging
import uuid

import numpy as np
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, MediaIdentity
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.embedding_space import representative_embedding_model
from recognition.config.settings import resolve_effective_clustering_settings
from recognition.domain.repositories import ClusterRepository
from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource

logger = logging.getLogger(__name__)

# Bind-parameter ceiling for the FIR23-01 provenance lookup (CVUP1-R3-09).
# asyncpg rejects statements above 32,767 arguments; stay well clear so the
# tenant_id / embedding_model binds and driver overhead always fit.
_MODEL_LOOKUP_CHUNK_SIZE = 10_000


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
    embedding = getattr(rep_identity, "embedding", None) if rep_identity is not None else None
    if embedding is not None:
        target_embedding = np.asarray(embedding, dtype=np.float32)
    else:
        if cluster_repository is None:
            return None
        # Prefer shared-contract with_model loaders so the model belonging to the
        # vectors we average is recovered when representative_identity is missing
        # (R3-G1-1 / production shape covered by the representative-table integration test).
        reps, chosen_model = await cluster_repository.get_representative_embeddings_with_model(cluster_id)
        if not reps:
            reps, chosen_model = await cluster_repository.get_member_fallback_embeddings_with_model(cluster_id, limit=4)
        if reps:
            rep_stack = np.asarray(reps, dtype=np.float32)
            target_embedding = rep_stack.mean(axis=0)
            # Only fill model from the loader when representative_identity did not
            # already supply one — keep the present-identity path unchanged.
            if target_model is None:
                target_model = chosen_model
        else:
            return None

    # FIR23-01 fail-closed: never run unguarded NN when the query face's space is
    # unknown. Same dimensionality does not mean same space; a foreign labeled
    # rep must never win SIMILAR_CLUSTER via cross-space cosine.
    if target_model is None:
        logger.warning(
            "[label_inference] FIR23-01: refusing nearest-label inference without "
            "resolvable embedding_model (would allow cross-space cosine); "
            "cluster_id=%s",
            cluster_id,
        )
        return None

    # Prefer in-process similarity search using representative sets when available to avoid
    # vector index constraints and to honor representative table embeddings.
    # FIR23-01: restrict candidates to the query face's embedding_model. Domain
    # representatives drop embedding_model, so resolve same-space identity ids via
    # session when target_model is known. Fall through to the SQL path when
    # in-process finds nothing under a model predicate (do not shadow FIR23-01).
    #
    # CVUP1-GR-20: never materialise the tenant's full face corpus. Collect only
    # identity_ids of the labeled representatives we actually score, then query
    # MediaIdentity.id.in_(those_ids). Cross-space reps remain excluded.
    if cluster_repository is not None:
        labeled_clusters = await cluster_repository.get_labeled_with_representatives(str(tenant_uuid))

        same_model_identity_ids: set[str] | None = None
        if target_model is not None:
            unresolved_ids: list[uuid.UUID] = []
            seen_unresolved: set[str] = set()
            for _cluster, cluster_reps in labeled_clusters:
                for rep in cluster_reps:
                    rep_model = representative_embedding_model(rep)
                    if rep_model is not None:
                        continue
                    identity_id = getattr(rep, "identity_id", None)
                    if identity_id is None:
                        continue
                    id_str = str(identity_id)
                    if id_str in seen_unresolved:
                        continue
                    try:
                        unresolved_ids.append(uuid.UUID(id_str))
                    except ValueError:
                        continue
                    seen_unresolved.add(id_str)

            # Empty set still means the filter is active (no same-space unresolved ids).
            # None would mean "no model predicate" and would re-open cross-space NN.
            same_model_identity_ids = set()
            # CVUP1-R3-09: ``in_()`` expands to one bind per element at execution.
            # asyncpg caps a statement at 32,767 arguments, so an unbounded id list
            # turns the suggestion endpoint into a hard 500 on large tenants.
            # Chunk instead; the union of chunk results equals the single-query result.
            for offset in range(0, len(unresolved_ids), _MODEL_LOOKUP_CHUNK_SIZE):
                chunk = unresolved_ids[offset : offset + _MODEL_LOOKUP_CHUNK_SIZE]
                model_ids_result = await session.execute(
                    select(MediaIdentity.id).where(
                        MediaIdentity.tenant_id == tenant_uuid,
                        MediaIdentity.id.in_(chunk),
                        MediaIdentity.embedding_model == target_model,
                    )
                )
                same_model_identity_ids.update(str(row) for row in model_ids_result.scalars().all())

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
                    rep_model = representative_embedding_model(rep)
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
