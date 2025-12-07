"""HTTP endpoints for similarity suggestions.

This module provides two types of suggestion endpoints:

1. **Real-time suggestions** (existing):
   - `GET /clusters/suggest` - Find similar clusters for an embedding
   - `GET /identities/{id}/suggestions` - Find similar clusters for an identity

2. **Persisted suggestions** (new):
   - `GET /suggestions` - List pending suggestions created during clustering
   - `GET /suggestions/{id}` - Get a specific suggestion
   - `POST /suggestions/{id}/accept` - Accept and assign identity to cluster
   - `POST /suggestions/{id}/reject` - Reject a suggestion
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ClusterCentroid, IdentityCluster, IdentitySuggestion, MediaIdentity
from db.session import get_session
from db.settings import get_database_settings
from db.tenant_context import set_tenant_context
from recognition.application.clustering.identity_clustering_service import (
    IdentityClusteringService,
)
from recognition.application.clustering.suggestion_service import SuggestionService

logger = logging.getLogger(__name__)

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
    """Query clusters whose centroids are similar to the provided embedding.

    Only returns clusters that have been explicitly labeled by the user
    (label does not start with "cluster-" and is not null/empty).
    """
    distance_threshold = 1.0 - threshold
    distance_expr = ClusterCentroid.centroid.cosine_distance(embedding)

    stmt = (
        select(IdentityCluster, distance_expr.label("distance"))
        .join(ClusterCentroid, IdentityCluster.id == ClusterCentroid.cluster_id)
        .where(IdentityCluster.tenant_id == tenant_id)
        .where(ClusterCentroid.member_count > 0)
        .where(distance_expr <= distance_threshold)
        # Only suggest clusters that have been explicitly labeled by user
        # (not auto-generated "cluster-XXXX" labels)
        .where(IdentityCluster.label.isnot(None))
        .where(IdentityCluster.label != "")
        .where(~IdentityCluster.label.startswith("cluster-"))
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

    On first query (or when view is stale), refreshes the materialized view
    if no matches are found but clusters exist.
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

    # If no matches found, try refreshing the materialized view and retry
    # This handles the case where clusters exist but view is stale
    if not matches:
        from sqlalchemy import func, text

        # Check if clusters exist (quick count)
        cluster_count_stmt = (
            select(func.count()).select_from(IdentityCluster).where(IdentityCluster.tenant_id == tenant_id)
        )
        cluster_count = (await session.execute(cluster_count_stmt)).scalar_one()

        if cluster_count > 0:
            logger.info(
                "No suggestions found but %d clusters exist; refreshing centroid view",
                cluster_count,
            )
            try:
                await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
                await session.execute(text("REFRESH MATERIALIZED VIEW mv_identity_cluster_centroids"))
                await session.execute(text("RESET app.bypass_rls"))
                # Retry the query
                matches = await _fetch_matches(session, tenant_id, embedding, top_k, threshold)
            except Exception as exc:
                logger.warning("Failed to refresh centroid view: %s", exc)

    return SuggestionResponse(matches=matches)


# ============================================================================
# Persisted Suggestion Endpoints (for borderline cluster matches)
# ============================================================================


class PersistedSuggestion(BaseModel):
    """A persisted suggestion for a borderline cluster match."""

    id: str = Field(..., description="Suggestion UUID")
    identity_id: str = Field(..., description="Identity UUID")
    suggested_cluster_id: str = Field(..., description="Suggested cluster UUID")
    representative_similarity: float = Field(..., description="Similarity to cluster representative")
    avg_member_similarity: float = Field(..., description="Average similarity to cluster members")
    confidence_score: float = Field(..., description="Combined confidence score (0-1)")
    resolution: str = Field(..., description="pending, accepted, rejected, or expired")
    created_at: datetime = Field(..., description="When the suggestion was created")
    resolved_at: datetime | None = Field(None, description="When the suggestion was resolved")

    # Optional enriched fields (populated when include_details=true)
    cluster_label: str | None = Field(None, description="Cluster label")
    cluster_member_count: int | None = Field(None, description="Number of identities in cluster")
    identity_media_id: int | None = Field(None, description="WordPress media ID")


class PersistedSuggestionListResponse(BaseModel):
    """Response for listing persisted suggestions."""

    suggestions: list[PersistedSuggestion]
    total: int = Field(..., description="Total number of pending suggestions")
    limit: int = Field(..., description="Number of suggestions per page")
    offset: int = Field(..., description="Number of suggestions skipped")


class SuggestionActionResponse(BaseModel):
    """Response for suggestion accept/reject actions."""

    id: str
    resolution: str
    resolved_at: datetime | None = None
    message: str


def _suggestion_to_response(
    suggestion: IdentitySuggestion,
    cluster_label: str | None = None,
    cluster_member_count: int | None = None,
    identity_media_id: int | None = None,
) -> PersistedSuggestion:
    """Convert an IdentitySuggestion model to an API response."""
    return PersistedSuggestion(
        id=str(suggestion.id),
        identity_id=str(suggestion.identity_id),
        suggested_cluster_id=str(suggestion.suggested_cluster_id),
        representative_similarity=suggestion.representative_similarity,
        avg_member_similarity=suggestion.avg_member_similarity,
        confidence_score=suggestion.confidence_score,
        resolution=suggestion.resolution or "pending",
        created_at=suggestion.created_at,
        resolved_at=suggestion.resolved_at,
        cluster_label=cluster_label,
        cluster_member_count=cluster_member_count,
        identity_media_id=identity_media_id,
    )


@router.get("/suggestions", response_model=PersistedSuggestionListResponse)
async def list_pending_suggestions(
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of suggestions to return"),
    offset: int = Query(0, ge=0, description="Number of suggestions to skip"),
    include_details: bool = Query(True, description="Include cluster label and member count"),
    session: AsyncSession = Depends(get_session),
) -> PersistedSuggestionListResponse:
    """
    List pending suggestions for review.

    Returns suggestions ordered by confidence score (highest first).
    Use this to populate a suggestion review queue in the UI.
    """
    await set_tenant_context(session, tenant_id)

    service = SuggestionService(session, tenant_id)
    suggestions = await service.get_pending_suggestions(limit=limit, offset=offset)
    total = await service.count_pending_suggestions()

    if not suggestions:
        return PersistedSuggestionListResponse(
            suggestions=[],
            total=total,
            limit=limit,
            offset=offset,
        )

    # Optionally fetch cluster and identity details for richer UI
    if include_details:
        cluster_ids = {s.suggested_cluster_id for s in suggestions}
        identity_ids = {s.identity_id for s in suggestions}

        # Fetch cluster labels and counts
        cluster_stmt = select(IdentityCluster).where(IdentityCluster.id.in_(cluster_ids))
        cluster_result = await session.execute(cluster_stmt)
        clusters = {c.id: c for c in cluster_result.scalars().all()}

        # Fetch identity media IDs
        identity_stmt = select(MediaIdentity).where(MediaIdentity.id.in_(identity_ids))
        identity_result = await session.execute(identity_stmt)
        identities = {i.id: i for i in identity_result.scalars().all()}

        response_items = []
        for s in suggestions:
            cluster = clusters.get(s.suggested_cluster_id)
            identity = identities.get(s.identity_id)
            response_items.append(
                _suggestion_to_response(
                    s,
                    cluster_label=cluster.label if cluster else None,
                    cluster_member_count=cluster.identity_count if cluster else None,
                    identity_media_id=identity.media_id if identity else None,
                )
            )
    else:
        response_items = [_suggestion_to_response(s) for s in suggestions]

    return PersistedSuggestionListResponse(
        suggestions=response_items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/suggestions/{suggestion_id}", response_model=PersistedSuggestion)
async def get_suggestion(
    suggestion_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    session: AsyncSession = Depends(get_session),
) -> PersistedSuggestion:
    """
    Get a specific suggestion by ID.
    """
    await set_tenant_context(session, tenant_id)

    service = SuggestionService(session, tenant_id)
    suggestion = await service.get_suggestion_by_id(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    # Fetch cluster details
    cluster = await session.get(IdentityCluster, suggestion.suggested_cluster_id)
    identity = await session.get(MediaIdentity, suggestion.identity_id)

    return _suggestion_to_response(
        suggestion,
        cluster_label=cluster.label if cluster else None,
        cluster_member_count=cluster.identity_count if cluster else None,
        identity_media_id=identity.media_id if identity else None,
    )


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionActionResponse)
async def accept_suggestion(
    suggestion_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    session: AsyncSession = Depends(get_session),
) -> SuggestionActionResponse:
    """
    Accept a suggestion and assign the identity to the suggested cluster.

    This will:
    1. Mark the suggestion as "accepted"
    2. Add the identity to the suggested cluster
    3. Expire any other pending suggestions for this identity
    """
    await set_tenant_context(session, tenant_id)

    service = SuggestionService(session, tenant_id)
    suggestion = await service.accept_suggestion(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.resolution != "accepted":
        # Already resolved
        return SuggestionActionResponse(
            id=str(suggestion.id),
            resolution=suggestion.resolution or "unknown",
            resolved_at=suggestion.resolved_at,
            message=f"Suggestion was already {suggestion.resolution}",
        )

    # Assign the identity to the cluster
    clustering_service = IdentityClusteringService(session, tenant_id)
    await clustering_service.assign_identity_to_cluster(suggestion.identity_id, suggestion.suggested_cluster_id)

    # Expire other pending suggestions for this identity
    await service.expire_suggestions_for_identity(suggestion.identity_id)

    await session.commit()

    logger.info(
        "Accepted suggestion %s: identity %s -> cluster %s",
        suggestion_id,
        suggestion.identity_id,
        suggestion.suggested_cluster_id,
    )

    return SuggestionActionResponse(
        id=str(suggestion.id),
        resolution="accepted",
        resolved_at=suggestion.resolved_at,
        message="Identity assigned to cluster",
    )


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionActionResponse)
async def reject_suggestion(
    suggestion_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant UUID"),
    session: AsyncSession = Depends(get_session),
) -> SuggestionActionResponse:
    """
    Reject a suggestion.

    The identity will remain unassigned (or in its current cluster).
    """
    await set_tenant_context(session, tenant_id)

    service = SuggestionService(session, tenant_id)
    suggestion = await service.reject_suggestion(suggestion_id)

    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.resolution != "rejected":
        # Already resolved
        return SuggestionActionResponse(
            id=str(suggestion.id),
            resolution=suggestion.resolution or "unknown",
            resolved_at=suggestion.resolved_at,
            message=f"Suggestion was already {suggestion.resolution}",
        )

    await session.commit()

    logger.info(
        "Rejected suggestion %s: identity %s (cluster %s)",
        suggestion_id,
        suggestion.identity_id,
        suggestion.suggested_cluster_id,
    )

    return SuggestionActionResponse(
        id=str(suggestion.id),
        resolution="rejected",
        resolved_at=suggestion.resolved_at,
        message="Suggestion rejected",
    )
