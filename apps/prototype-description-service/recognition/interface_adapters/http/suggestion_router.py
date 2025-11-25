"""HTTP endpoints for similarity suggestions."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityCluster, MediaIdentity
from db.session import get_session
from db.settings import get_database_settings
from db.tenant_context import set_tenant_context

router = APIRouter(tags=["recognition"])
_DB_SETTINGS = get_database_settings()


class ClusterMatch(BaseModel):
    cluster_id: str = Field(..., description="Cluster UUID")
    label: str = Field(..., description="Cluster label")
    similarity: float = Field(..., description="Cosine similarity score (0-1)")
    identity_count: int = Field(..., description="Number of identities in the cluster")


class SuggestionResponse(BaseModel):
    matches: list[ClusterMatch]


def _validate_embedding_length(embedding: Sequence[float]) -> None:
    """Ensure the embedding length matches the configured pgvector dimension."""
    expected = _DB_SETTINGS.pgvector_dimension
    if len(embedding) != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Embedding must contain {expected} dimensions; received {len(embedding)}.",
        )


async def _fetch_matches(
    session: AsyncSession,
    tenant_id: UUID,
    embedding: Sequence[float],
    top_k: int,
    threshold: float,
) -> list[ClusterMatch]:
    """Query clusters whose centroids are similar to the provided embedding."""
    distance_threshold = 1.0 - threshold
    distance_expr = ClusterCentroid.centroid.cosine_distance(embedding)

    stmt = (
        select(IdentityCluster, distance_expr.label("distance"))
        .join(ClusterCentroid, IdentityCluster.id == ClusterCentroid.cluster_id)
        .where(IdentityCluster.tenant_id == tenant_id)
        .where(ClusterCentroid.member_count > 0)
        .where(distance_expr <= distance_threshold)
        .order_by(distance_expr.asc())
        .limit(top_k)
    )

    result = await session.execute(stmt)
    matches: list[ClusterMatch] = []
    for cluster, distance in result.all():
        similarity = 1.0 - float(distance)
        matches.append(
            ClusterMatch(
                cluster_id=str(cluster.id),
                label=cluster.label or "",
                similarity=similarity,
                identity_count=cluster.identity_count,
            )
        )
    return matches


@router.get("/clusters/suggest", response_model=SuggestionResponse)
async def suggest_similar_clusters(
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    embedding: list[float] = Query(
        ...,
        min_items=_DB_SETTINGS.pgvector_dimension,
        max_items=_DB_SETTINGS.pgvector_dimension,
        description="Embedding vector for the query identity",
    ),
    top_k: int = Query(5, ge=1, le=20, description="Maximum number of matches to return"),
    threshold: float = Query(0.6, ge=0.0, le=1.0, description="Minimum similarity to include a match"),
    session: AsyncSession = Depends(get_session),
) -> SuggestionResponse:
    """
    Find existing clusters whose centroids are similar to the provided embedding.
    Uses pgvector for efficient in-database similarity search.
    """
    _validate_embedding_length(embedding)
    await set_tenant_context(session, tenant_id)
    matches = await _fetch_matches(session, tenant_id, embedding, top_k, threshold)
    return SuggestionResponse(matches=matches)


@router.get("/identities/{identity_id}/suggestions", response_model=SuggestionResponse)
async def suggest_for_identity(
    identity_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    top_k: int = Query(5, ge=1, le=20, description="Maximum number of matches to return"),
    threshold: float = Query(0.6, ge=0.0, le=1.0, description="Minimum similarity to include a match"),
    session: AsyncSession = Depends(get_session),
) -> SuggestionResponse:
    """
    Find existing clusters similar to a specific identity.
    """
    await set_tenant_context(session, tenant_id)

    stmt = select(MediaIdentity.embedding).where(
        MediaIdentity.id == identity_id,
        MediaIdentity.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    embedding = result.scalar_one_or_none()

    if embedding is None:
        raise HTTPException(status_code=404, detail="Identity not found for this tenant")

    _validate_embedding_length(embedding)
    matches = await _fetch_matches(session, tenant_id, embedding, top_k, threshold)
    return SuggestionResponse(matches=matches)
