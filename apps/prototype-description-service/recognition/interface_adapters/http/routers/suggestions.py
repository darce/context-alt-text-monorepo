"""
Suggestion management routes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.config.security import get_security_settings
from recognition.domain.cluster import IdentityCluster
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    MergeSuggestion,
    NameSuggestion,
    SuggestionStatus,
)
from recognition.infrastructure.repositories import SqlAlchemyMergeSuggestionRepository
from recognition.interface_adapters.http.dependencies import (
    get_cluster_repository,
    get_cluster_service_builder,
    get_session,
    get_suggestion_extension_service,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.schemas.requests import BulkAcceptSuggestionsRequest, SuggestionActionRequest
from recognition.interface_adapters.http.schemas.responses import (
    BulkAcceptResponse,
    ClusterSuggestionMatch,
    FaceBoxResponse,
    IdentitySuggestionsResponse,
    MergeSuggestionResponse,
    NameSuggestionResponse,
    SuggestionResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_paging
from recognition.interface_adapters.schemas.suggestion_details import MergeSuggestionDetails, SuggestionDetails

router = APIRouter(tags=["suggestions"], dependencies=[Depends(require_auth)])

T_Suggestion = TypeVar("T_Suggestion")


@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_pending_suggestions(
    _tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    suggestion_service=Depends(get_suggestion_service),
) -> list[SuggestionResponse]:
    """List pending suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    if min_confidence is not None:
        suggestions = await _collect_min_confidence_page(
            suggestion_service.list_pending,
            limit=limit,
            offset=offset,
            min_confidence=min_confidence,
            batch_size=settings.max_page_size,
        )
    else:
        suggestions = await suggestion_service.list_pending(limit=limit, offset=offset)
    return [_to_response_with_details(s) for s in suggestions]


@router.get("/suggestions/merge", response_model=list[MergeSuggestionResponse])
async def list_pending_merge_suggestions(
    _tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    session=Depends(get_session),
) -> list[MergeSuggestionResponse]:
    """List pending cluster merge suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    repo = SqlAlchemyMergeSuggestionRepository(session)
    if min_confidence is not None:
        suggestions = await _collect_min_confidence_page(
            lambda batch_limit, batch_offset: repo.list_pending_with_details(
                _tenant_id, limit=batch_limit, offset=batch_offset
            ),
            limit=limit,
            offset=offset,
            min_confidence=min_confidence,
            batch_size=settings.max_page_size,
        )
    else:
        suggestions = await repo.list_pending_with_details(_tenant_id, limit=limit, offset=offset)
    return [_to_merge_response(s) for s in suggestions]


@router.get("/identities/{identity_id}/suggestions", response_model=IdentitySuggestionsResponse)
async def list_suggestions(
    identity_id: str,
    _tenant_id: str = Depends(get_tenant_id),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
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
    if min_confidence is not None:
        suggestions = [suggestion for suggestion in suggestions if _meets_min_confidence(suggestion, min_confidence)]

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


@router.get("/suggestions/name", response_model=list[NameSuggestionResponse])
async def list_name_suggestions(
    _tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    suggestion_extension_service=Depends(get_suggestion_extension_service),
) -> list[NameSuggestionResponse]:
    """List pending name suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    suggestions = await suggestion_extension_service.list_name_suggestions(
        _tenant_id,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    return [_to_name_response(s) for s in suggestions]


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionResponse)
async def accept_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
    suggestion_service=Depends(get_suggestion_service),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> SuggestionResponse:
    """Accept a suggestion, persisting the assignment."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    suggestion = await suggestion_service.accept(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    cluster_service = await cluster_service_builder(request.tenant_id)
    assigned = await cluster_service.assign_outlier_to_cluster(
        identity_id=suggestion.identity_id,
        target_cluster_id=suggestion.cluster_id,
        tenant_id=request.tenant_id,
        similarity=suggestion.representative_similarity,
    )
    if assigned is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Suggestion assignment failed")

    await suggestion_service.resolve_for_identity_exclusive(
        identity_id=suggestion.identity_id,
        accepted_cluster_id=suggestion.cluster_id,
        reason="manual_accept",
    )

    # Do not trigger cluster-wide refresh on a single manual accept.
    # Requirement: one click should resolve only the selected card.

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_response(suggestion)


@router.post("/suggestions/name/{suggestion_id}/accept", response_model=NameSuggestionResponse)
async def accept_name_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    suggestion_extension_service=Depends(get_suggestion_extension_service),
) -> NameSuggestionResponse:
    """Accept a name suggestion and apply the label to the target cluster."""
    validate_entity_id(suggestion_id, field_name="suggestion_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    try:
        suggestion = await suggestion_extension_service.accept_name_suggestion(request.tenant_id, suggestion_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Name suggestion not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None

    await session.commit()
    return _to_name_response(suggestion)


@router.post("/suggestions/name/{suggestion_id}/reject", response_model=NameSuggestionResponse)
async def reject_name_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    suggestion_extension_service=Depends(get_suggestion_extension_service),
) -> NameSuggestionResponse:
    """Reject a name suggestion."""
    validate_entity_id(suggestion_id, field_name="suggestion_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    try:
        suggestion = await suggestion_extension_service.reject_name_suggestion(request.tenant_id, suggestion_id)
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Name suggestion not found") from None

    await session.commit()
    return _to_name_response(suggestion)


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionResponse)
async def reject_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    tenant_id: str = Depends(get_tenant_id),
    session=Depends(get_session),
    suggestion_service=Depends(get_suggestion_service),
) -> SuggestionResponse:
    """Reject a suggestion."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    suggestion = await suggestion_service.reject(suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")

    # Commit before response so client refetches see committed state
    # (see clusters.py PATCH handler comment for full race condition explanation).
    await session.commit()

    return _to_response(suggestion)


@router.post("/suggestions/bulk-accept", response_model=BulkAcceptResponse)
async def bulk_accept_suggestions(
    request: BulkAcceptSuggestionsRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    suggestion_extension_service=Depends(get_suggestion_extension_service),
) -> BulkAcceptResponse:
    """Bulk-accept suggestions by type and confidence threshold."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    result = await suggestion_extension_service.bulk_accept(
        request.tenant_id,
        suggestion_type=request.suggestion_type,
        min_confidence=request.min_confidence,
    )
    await session.commit()
    return BulkAcceptResponse(accepted_count=result.accepted_count, skipped_count=result.skipped_count)


@router.post("/suggestions/merge/{suggestion_id}/accept", response_model=MergeSuggestionResponse)
async def accept_merge_suggestion(
    suggestion_id: str,
    request: SuggestionActionRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
    cluster_service_builder=Depends(get_cluster_service_builder),
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

    cluster_service = await cluster_service_builder(request.tenant_id)
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
        moved_by_merge_id=str(suggestion.id),
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
        identity_bbox=identity_bbox,
        representative_media_id=suggestion.representative_media_id,
        representative_media_url=suggestion.representative_media_url,
        representative_bbox=representative_bbox,
        suggested_label=suggestion.suggested_label,
        suggested_label_source=suggestion.suggested_label_source.value if suggestion.suggested_label_source else None,
        suggested_label_confidence=suggestion.suggested_label_confidence,
        confidence_score=suggestion.confidence_score,
        expires_at=suggestion.expires_at,
        source_job_id=suggestion.source_job_id,
    )


def _to_name_response(suggestion: NameSuggestion) -> NameSuggestionResponse:
    """Convert a name suggestion to the API response model."""
    return NameSuggestionResponse(
        id=suggestion.id,
        cluster_id=suggestion.cluster_id,
        suggested_name=suggestion.suggested_name,
        source=suggestion.source.value,
        status=suggestion.status.value,
        confidence_score=suggestion.confidence_score,
        source_job_id=suggestion.source_job_id,
        created_at=suggestion.created_at,
        expires_at=suggestion.expires_at,
        resolved_at=suggestion.resolved_at,
    )


def _is_meaningful_label(label: str | None) -> bool:
    if not label:
        return False
    return not str(label).startswith("cluster-")


def _suggestion_confidence(suggestion: object) -> float | None:
    confidence = getattr(suggestion, "confidence_score", None)
    if confidence is None:
        confidence = getattr(suggestion, "suggested_label_confidence", None)
    try:
        return None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        return None


def _meets_min_confidence(suggestion: object, min_confidence: float) -> bool:
    confidence = _suggestion_confidence(suggestion)
    return confidence is not None and confidence >= min_confidence


async def _collect_min_confidence_page[T_Suggestion](
    fetch_page: Callable[[int, int], Awaitable[Sequence[T_Suggestion]]],
    *,
    limit: int,
    offset: int,
    min_confidence: float,
    batch_size: int,
) -> list[T_Suggestion]:
    """Filter pending results before applying paging semantics.

    The underlying suggestion endpoints only expose offset/limit paging, so we
    walk the unfiltered result set in batches, filter each batch, and then apply
    the requested paging window to the filtered sequence.
    """
    filtered: list[T_Suggestion] = []
    page_offset = 0
    target_count = offset + limit
    max_batches = 10
    batch_count = 0

    while len(filtered) < target_count:
        if batch_count >= max_batches:
            break
        batch_count += 1
        page = list(await fetch_page(batch_size, page_offset))
        if not page:
            break

        filtered.extend(item for item in page if _meets_min_confidence(item, min_confidence))
        if len(page) < batch_size:
            break
        page_offset += batch_size

    return filtered[offset:target_count]


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
        cluster_b_representative_bbox=FaceBoxResponse(
            x=cluster_b_bbox.x,
            y=cluster_b_bbox.y,
            width=cluster_b_bbox.width,
            height=cluster_b_bbox.height,
        )
        if cluster_b_bbox
        else None,
        confidence_score=getattr(suggestion, "confidence_score", None),
        expires_at=getattr(suggestion, "expires_at", None),
        source_job_id=getattr(suggestion, "source_job_id", None),
    )
