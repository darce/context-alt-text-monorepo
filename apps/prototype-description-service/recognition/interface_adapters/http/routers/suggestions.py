"""
Suggestion management routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.config.security import get_security_settings
from recognition.domain.suggestion import AssignmentSuggestion
from recognition.interface_adapters.http.dependencies import (
    get_cluster_repository,
    get_session,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.schemas.requests import SuggestionActionRequest
from recognition.interface_adapters.http.schemas.responses import (
    ClusterSuggestionMatch,
    IdentitySuggestionsResponse,
    SuggestionResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_paging

router = APIRouter(tags=["suggestions"], dependencies=[Depends(require_auth)])


@router.get("/suggestions", response_model=list[SuggestionResponse])
async def list_pending_suggestions(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    suggestion_service=Depends(get_suggestion_service),
) -> list[SuggestionResponse]:
    """List pending suggestions for a tenant."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    suggestions = await suggestion_service.list_pending(limit=limit, offset=offset)
    return [_to_response(s) for s in suggestions]


@router.get("/identities/{identity_id}/suggestions", response_model=IdentitySuggestionsResponse)
async def list_suggestions(
    identity_id: str,
    tenant_id: str = Depends(get_tenant_id),
    suggestion_service=Depends(get_suggestion_service),
    cluster_repo=Depends(get_cluster_repository),
) -> IdentitySuggestionsResponse:
    """List pending suggestions for an identity with enriched cluster data.

    Returns suggestions in frontend-compatible format with cluster labels
    and member counts.
    """
    validate_entity_id(identity_id, field_name="identity_id")
    suggestions = await suggestion_service.list_for_identity(identity_id)

    # Enrich suggestions with cluster details
    matches: list[ClusterSuggestionMatch] = []
    for suggestion in suggestions:
        # Fetch cluster to get label and member count
        cluster = await cluster_repo.get_by_id(suggestion.cluster_id)
        if cluster:
            matches.append(
                ClusterSuggestionMatch(
                    cluster_id=suggestion.cluster_id,
                    label=cluster.label or f"cluster-{suggestion.cluster_id[:8]}",
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
    return _to_response(suggestion)


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
