"""HTTP endpoints for similarity suggestions."""

from __future__ import annotations

from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityCluster
from db.session import get_session
from db.tenant_context import set_tenant_context
from recognition.application.centroid_utils import compute_similarity

router = APIRouter(tags=["recognition"])


class ClusterMatch(BaseModel):
    cluster_id: str = Field(..., description="Cluster UUID")
    label: str = Field(..., description="Cluster label")
    similarity: float = Field(..., description="Cosine similarity score (0-1)")
    identity_count: int = Field(..., description="Number of identities in the cluster")


class SuggestionResponse(BaseModel):
    matches: list[ClusterMatch]


@router.get("/clusters/suggest", response_model=SuggestionResponse)
async def suggest_similar_clusters(
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    embedding: list[float] = Query(..., description="Embedding vector for the query identity"),
    top_k: int = Query(5, ge=1, le=20, description="Maximum number of matches to return"),
    threshold: float = Query(0.6, ge=0.0, le=1.0, description="Minimum similarity to include a match"),
    session: AsyncSession = Depends(get_session),
) -> SuggestionResponse:
    """
    Find existing clusters whose centroids are similar to the provided embedding.
    """

    await set_tenant_context(session, tenant_id)

    stmt = (
        select(IdentityCluster, ClusterCentroid.centroid, ClusterCentroid.member_count)
        .join(ClusterCentroid, IdentityCluster.id == ClusterCentroid.cluster_id)
        .where(IdentityCluster.tenant_id == tenant_id)
    )
    result = await session.execute(stmt)

    query_vector = np.array(embedding, dtype=np.float32)
    matches: list[tuple[IdentityCluster, float]] = []

    for cluster, centroid, member_count in result.all():
        if centroid is None or not member_count:
            continue
        centroid_vector = np.array(centroid, dtype=np.float32)
        similarity = compute_similarity(query_vector, centroid_vector)
        if similarity >= threshold:
            matches.append((cluster, similarity))

    matches.sort(key=lambda pair: pair[1], reverse=True)
    matches = matches[:top_k]

    return SuggestionResponse(
        matches=[
            ClusterMatch(
                cluster_id=str(cluster.id),
                label=cluster.label or "",
                similarity=similarity,
                identity_count=cluster.identity_count,
            )
            for cluster, similarity in matches
        ]
    )
