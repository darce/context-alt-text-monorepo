"""
Label inference service for proactive suggestions.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from db.models import IdentityCluster, MediaIdentity
from recognition.config.settings import ClusteringSettings  # Assuming this location or will verify
from recognition.domain.suggestion import SuggestedLabel, SuggestedLabelSource


async def infer_suggested_label(
    tenant_id: str,
    cluster_id: str,
    *,
    session: AsyncSession,
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
    settings = ClusteringSettings()

    threshold = settings.suggestion_floor  # Dynamic threshold

    try:
        tenant_uuid = uuid.UUID(tenant_id)
        cluster_uuid = uuid.UUID(cluster_id)
    except ValueError:
        return None

    # Fetch the target cluster's representative embedding
    # Correct model attribute: 'representative_identity' which has 'embedding'
    stmt_target = (
        select(IdentityCluster)
        .options(joinedload(IdentityCluster.representative_identity))
        .where(IdentityCluster.id == cluster_uuid)
        .where(IdentityCluster.tenant_id == tenant_uuid)
    )
    result_target = await session.execute(stmt_target)
    target_cluster = result_target.scalar_one_or_none()

    if not target_cluster or not target_cluster.representative_identity:
        return None

    # 1. Identity Match (via IdentitySuggestion)
    # Check if any member of this cluster has a pending suggestion to link to a LABELED cluster
    # This implies the member is likely that person, so the whole cluster (assignment target) might be that person.
    from db.models.constraints import IdentitySuggestion
    from db.models.identity import IdentityMember

    stmt_identity = (
        select(IdentitySuggestion, IdentityCluster)
        .join(IdentityCluster, IdentitySuggestion.suggested_cluster_id == IdentityCluster.id)
        .join(IdentityMember, IdentitySuggestion.identity_id == IdentityMember.identity_id)
        .where(IdentitySuggestion.tenant_id == tenant_uuid)
        .where(IdentitySuggestion.resolution == "pending")
        .where(IdentityMember.cluster_id == cluster_uuid)
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .order_by(IdentitySuggestion.confidence_score.desc())
        .limit(1)
    )

    result_identity = await session.execute(stmt_identity)
    identity_match = result_identity.first()

    if identity_match:
        suggestion, other_cluster = identity_match
        # If we have a strong suggestion linking a member to a labeled cluster, use it.
        # Threshold: use suggestion confidence.
        if suggestion.confidence_score >= threshold:
            return SuggestedLabel(
                label=other_cluster.label, source=SuggestedLabelSource.IDENTITY, confidence=suggestion.confidence_score
            )

    # 1b. Roster Entry Match
    if target_cluster.roster_id:
        # Check if we can resolve the name from a legacy table (best effort)
        # Even if table is missing, the presence of roster_id is a strong signal.
        try:
            from sqlalchemy import text

            # Use text() to avoid dependency on missing model
            roster_stmt = text("SELECT name FROM roster_entries WHERE id = :rid")
            roster_res = await session.execute(roster_stmt, {"rid": str(target_cluster.roster_id)})
            roster_name = roster_res.scalar()
            if roster_name:
                return SuggestedLabel(label=roster_name, source=SuggestedLabelSource.ROSTER, confidence=1.0)
        except Exception:
            # Table missing or query failure - cannot verify label
            pass

        # If we couldn't resolve the name (missing table or ID), return None.
        # Requirements imply we need the specific name, not a generic signal.
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
                label=other_cluster.label, source=SuggestedLabelSource.SIMILAR_CLUSTER, confidence=suggestion.similarity
            )

    # 3. Nearest Neighbor Search (Fallback)
    if not target_cluster.representative_identity:
        return None

    # Check if representative_identity is loaded; if not, might need to fetch it?
    # joinedload was used above, so it should be there.
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
                    label=nearest_cluster.label, source=SuggestedLabelSource.SIMILAR_CLUSTER, confidence=similarity
                )

    return None
