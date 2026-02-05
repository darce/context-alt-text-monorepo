"""
Suggestion management routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.config.security import get_security_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    MergeSuggestion,
    MergeSuggestionDetails,
    SuggestionDetails,
    SuggestionStatus,
)
from recognition.infrastructure.repositories import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.dependencies import (
    build_cluster_service,
    get_cluster_repository,
    get_session,
    get_suggestion_refresh_service,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.schemas.requests import SuggestionActionRequest
from recognition.interface_adapters.http.schemas.responses import (
    ClusterSuggestionMatch,
    FaceBoxResponse,
    IdentitySuggestionsResponse,
    MergeSuggestionResponse,
    SuggestionResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_paging

router = APIRouter(tags=["suggestions"], dependencies=[Depends(require_auth)])


@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_pending_suggestions(
    _tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    suggestion_service=Depends(get_suggestion_service),
) -> list[SuggestionResponse]:
    """List pending suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    suggestions = await suggestion_service.list_pending(limit=limit, offset=offset)
    return [_to_response_with_details(s) for s in suggestions]


@router.get("/suggestions/merge", response_model=list[MergeSuggestionResponse])
async def list_pending_merge_suggestions(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    session=Depends(get_session),
) -> list[MergeSuggestionResponse]:
    """List pending cluster merge suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    repo = SqlAlchemyMergeSuggestionRepository(session)
    suggestions = await repo.list_pending_with_details(tenant_id, limit=limit, offset=offset)
    return [_to_merge_response(s) for s in suggestions]


@router.get("/identities/{identity_id}/suggestions", response_model=IdentitySuggestionsResponse)
async def list_suggestions(
    identity_id: str,
    tenant_id: str = Depends(get_tenant_id),
    suggestion_service=Depends(get_suggestion_service),
    cluster_repo=Depends(get_cluster_repository),
) -> IdentitySuggestionsResponse:
    """List pending suggestions for an identity with enriched cluster data.

    Returns suggestions in frontend-compatible format with cluster labels
    and member counts. Only returns suggestions for labeled clusters - unlabeled
    cluster suggestions are not actionable (asking "Is this Unnamed cluster?" is meaningless).
    """
    validate_entity_id(identity_id, field_name="identity_id")
    suggestions = await suggestion_service.list_for_identity(identity_id)

    # Enrich suggestions with cluster details - only include labeled clusters
    matches: list[ClusterSuggestionMatch] = []
    for suggestion in suggestions:
        # Fetch cluster to get label and member count
        cluster = await cluster_repo.get_by_id(suggestion.cluster_id)
        # Only include suggestions for clusters with actual labels
        if cluster and cluster.label:
            matches.append(
                ClusterSuggestionMatch(
                    suggestion_id=suggestion.id,
                    cluster_id=suggestion.cluster_id,
                    label=cluster.label,
                    similarity=suggestion.representative_similarity,
                    identity_count=cluster.identity_count or 0,
                )
            )

    # Sort by similarity descending
    matches.sort(key=lambda m: m.similarity, reverse=True)

    return IdentitySuggestionsResponse(matches=matches)


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionResponse)
async def accept_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
) -> SuggestionResponse:
    """Accept a suggestion, persisting the assignment."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
    suggestion = await suggestion_service.accept(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    assigned = await cluster_service.assign_outlier_to_cluster(
        identity_id=suggestion.identity_id,
        target_cluster_id=suggestion.cluster_id,
        tenant_id=request.tenant_id,
        similarity=suggestion.representative_similarity,
    )
    if assigned is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Suggestion assignment failed")

    resolve_exclusive = getattr(suggestion_service, "resolve_for_identity_exclusive", None)
    if callable(resolve_exclusive):
        await resolve_exclusive(
            identity_id=suggestion.identity_id,
            accepted_cluster_id=suggestion.cluster_id,
            reason="manual_accept",
        )

    # Refresh suggestions for the target cluster (centroid changed)
    suggestion_refresh_service = await get_suggestion_refresh_service(session=session, tenant_id=request.tenant_id)
    await suggestion_refresh_service.refresh_for_cluster(suggestion.cluster_id)

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_response(suggestion)


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
) -> SuggestionResponse:
    """Reject a suggestion."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
    suggestion = await suggestion_service.reject(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_response(suggestion)


@router.post("/suggestions/merge/{suggestion_id}/accept", response_model=MergeSuggestionResponse)
async def accept_merge_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> MergeSuggestionResponse:
    """Accept a merge suggestion, merging the cluster pair."""
    validate_entity_id(suggestion_id, field_name="suggestion_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    repo = SqlAlchemyMergeSuggestionRepository(session)
    suggestion = await repo.get_by_id(request.tenant_id, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merge suggestion not found")
    if suggestion.status != SuggestionStatus.PENDING:
        return _to_merge_response(suggestion)

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    cluster_a = await cluster_repo.get_by_id(suggestion.cluster_a_id)
    cluster_b = await cluster_repo.get_by_id(suggestion.cluster_b_id)
    if not cluster_a or not cluster_b:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    source_cluster_id, target_cluster_id, target_label = _select_merge_target(cluster_a, cluster_b)
    merged = await cluster_service.merge_cluster(
        source_cluster_id,
        request.tenant_id,
        target_cluster_id,
        target_label=target_label,
    )
    if merged is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Merge failed")

    await repo.delete_by_cluster(request.tenant_id, source_cluster_id)
    await repo.delete_by_cluster(request.tenant_id, target_cluster_id)
    suggestion.status = SuggestionStatus.ACCEPTED

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_merge_response(suggestion)


@router.post("/suggestions/merge/{suggestion_id}/reject", response_model=MergeSuggestionResponse)
async def reject_merge_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> MergeSuggestionResponse:
    """Reject a merge suggestion."""
    validate_entity_id(suggestion_id, field_name="suggestion_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    repo = SqlAlchemyMergeSuggestionRepository(session)
    try:
        suggestion = await repo.update_status(request.tenant_id, suggestion_id, SuggestionStatus.REJECTED)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Merge suggestion not found") from None

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_merge_response(suggestion)


def _to_response(suggestion: AssignmentSuggestion) -> SuggestionResponse:
    """Convert domain suggestion to API response model."""
    return SuggestionResponse(
        id=suggestion.id,
        identity_id=suggestion.identity_id,
        cluster_id=suggestion.cluster_id,
        rep_similarity=suggestion.representative_similarity,
        member_similarity=suggestion.member_similarity,
        status=suggestion.status.value,
    )


def _to_response_with_details(suggestion: SuggestionDetails) -> SuggestionResponse:
    """Convert suggestion detail to API response with identity + cluster details."""
    identity_bbox = (
        FaceBoxResponse(
            x=suggestion.identity_bbox.x,
            y=suggestion.identity_bbox.y,
            width=suggestion.identity_bbox.width,
            height=suggestion.identity_bbox.height,
        )
        if suggestion.identity_bbox
        else None
    )
    representative_bbox = (
        FaceBoxResponse(
            x=suggestion.representative_bbox.x,
            y=suggestion.representative_bbox.y,
            width=suggestion.representative_bbox.width,
            height=suggestion.representative_bbox.height,
        )
        if suggestion.representative_bbox
        else None
    )

    return SuggestionResponse(
        id=suggestion.id,
        identity_id=suggestion.identity_id,
        cluster_id=suggestion.cluster_id,
        rep_similarity=suggestion.representative_similarity,
        member_similarity=suggestion.member_similarity,
        status=suggestion.status,
        cluster_label=suggestion.cluster_label,
        cluster_identity_count=suggestion.cluster_identity_count,
        identity_media_id=suggestion.identity_media_id,
        identity_media_url=suggestion.identity_media_url,
        identity_thumbnail_url=suggestion.identity_thumbnail_url,
        identity_bbox=identity_bbox,
        representative_media_id=suggestion.representative_media_id,
        representative_media_url=suggestion.representative_media_url,
        representative_thumbnail_url=suggestion.representative_thumbnail_url,
        representative_bbox=representative_bbox,
        suggested_label=suggestion.suggested_label,
        suggested_label_source=suggestion.suggested_label_source.value if suggestion.suggested_label_source else None,
        suggested_label_confidence=suggestion.suggested_label_confidence,
        cluster_thumbnails=suggestion.cluster_thumbnails or [],
    )


def _is_meaningful_label(label: str | None) -> bool:
    if not label:
        return False
    return not str(label).startswith("cluster-")


def _select_merge_target(cluster_a: IdentityCluster, cluster_b: IdentityCluster) -> tuple[str, str, str | None]:
    """Pick a target cluster to preserve labels and counts."""

    def rank(cluster: IdentityCluster) -> tuple[int, int, int, str]:
        return (
            1 if cluster.user_confirmed else 0,
            1 if _is_meaningful_label(cluster.label) else 0,
            int(cluster.identity_count or 0),
            cluster.id or "",
        )

    target = cluster_a if rank(cluster_a) >= rank(cluster_b) else cluster_b
    source = cluster_b if target is cluster_a else cluster_a
    if not target.id or not source.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cluster identifiers missing")
    return source.id, target.id, target.label


def _to_merge_response(suggestion: MergeSuggestion | MergeSuggestionDetails) -> MergeSuggestionResponse:
    """Convert merge suggestion to API response model."""
    status_value = suggestion.status if isinstance(suggestion.status, str) else suggestion.status.value
    cluster_a_bbox = getattr(suggestion, "cluster_a_representative_bbox", None)
    cluster_b_bbox = getattr(suggestion, "cluster_b_representative_bbox", None)

    return MergeSuggestionResponse(
        id=suggestion.id,
        cluster_a_id=suggestion.cluster_a_id,
        cluster_b_id=suggestion.cluster_b_id,
        similarity=suggestion.similarity,
        status=status_value,
        cluster_a_label=getattr(suggestion, "cluster_a_label", None),
        cluster_b_label=getattr(suggestion, "cluster_b_label", None),
        cluster_a_identity_count=getattr(suggestion, "cluster_a_identity_count", None),
        cluster_b_identity_count=getattr(suggestion, "cluster_b_identity_count", None),
        cluster_a_representative_media_id=getattr(suggestion, "cluster_a_representative_media_id", None),
        cluster_a_representative_media_url=getattr(suggestion, "cluster_a_representative_media_url", None),
        cluster_a_representative_thumbnail_url=getattr(suggestion, "cluster_a_representative_thumbnail_url", None),
        cluster_a_representative_bbox=FaceBoxResponse(
            x=cluster_a_bbox.x,
            y=cluster_a_bbox.y,
            width=cluster_a_bbox.width,
            height=cluster_a_bbox.height,
        )
        if cluster_a_bbox
        else None,
        cluster_b_representative_media_id=getattr(suggestion, "cluster_b_representative_media_id", None),
        cluster_b_representative_media_url=getattr(suggestion, "cluster_b_representative_media_url", None),
        cluster_b_representative_thumbnail_url=getattr(suggestion, "cluster_b_representative_thumbnail_url", None),
        cluster_b_representative_bbox=FaceBoxResponse(
            x=cluster_b_bbox.x,
            y=cluster_b_bbox.y,
            width=cluster_b_bbox.width,
            height=cluster_b_bbox.height,
        )
        if cluster_b_bbox
        else None,
    )
