"""
Label inference service for proactive suggestions.
"""

from __future__ import annotations

import uuid

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, MediaIdentity
from recognition.application.settings import ClusteringSettings
from recognition.config import get_settings as get_recognition_settings
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
    inference_settings = settings or get_recognition_settings().clustering
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
    if not target_cluster.representative_identity:
        return None

    target_embedding = target_cluster.representative_identity.embedding
    if not target_embedding:
        return None

    # Find nearest labeled cluster using embedding distance
    stmt = (
        select(IdentityCluster)
        .join(MediaIdentity, IdentityCluster.representative_identity_id == MediaIdentity.id)
        .where(IdentityCluster.tenant_id == tenant_uuid)
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .where(IdentityCluster.id != cluster_uuid)
        .order_by(MediaIdentity.embedding.cosine_distance(target_embedding))
        .limit(1)
        .options(joinedload(IdentityCluster.representative_identity))
    )

    result = await session.execute(stmt)
    nearest_cluster = result.scalar_one_or_none()

    if (
        nearest_cluster
        and nearest_cluster.representative_identity
        and nearest_cluster.representative_identity.embedding
    ):
        import numpy as np

        vec_a = np.array(target_embedding)
        vec_b = np.array(nearest_cluster.representative_identity.embedding)

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
