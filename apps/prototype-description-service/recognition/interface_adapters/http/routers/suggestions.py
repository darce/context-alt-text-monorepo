"""
Suggestion management routes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.application.orchestration import ClusterService
from recognition.application.suggestions.roster_candidates import (
    DEFAULT_ROSTER_CANDIDATES_TOP_K,
    MAX_ROSTER_CANDIDATES_TOP_K,
    list_roster_candidates,
)
from recognition.application.suggestions.service import SuggestionService
from recognition.config.security import get_security_settings
from recognition.domain.cluster import IdentityCluster, ReservedClusterLabelError, is_reserved_label_shape
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    BulkAcceptResult,
    MergeSuggestion,
    NameSuggestion,
    SuggestionStatus,
)
from recognition.domain.suggestion_details import MergeSuggestionDetails, SuggestionDetails
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMergeSuggestionRepository
from recognition.infrastructure.services import SuggestionExtensionService
from recognition.interface_adapters.http.deps import (
    get_cluster_repository,
    get_cluster_service_builder,
    get_merge_suggestion_repository,
    get_session,
    get_suggestion_extension_service,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.face_box import representative_response_from_domain
from recognition.interface_adapters.http.schemas.requests import BulkAcceptSuggestionsRequest, SuggestionActionRequest
from recognition.interface_adapters.http.schemas.responses import (
    BulkAcceptResponse,
    ClusterSuggestionMatch,
    FaceBoxResponse,
    IdentityBatchSuggestionsResponse,
    IdentitySuggestionsResponse,
    MergeSuggestionResponse,
    NameSuggestionResponse,
    RepresentativeResponse,
    RosterCandidateResponse,
    RosterCandidateThresholdsResponse,
    RosterCandidatesResponse,
    SuggestionResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_paging, validate_top_k

router = APIRouter(tags=["suggestions"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])

T_Suggestion = TypeVar("T_Suggestion")

# URL-budget bound for the batch identity-suggestions route (UXP-2 3a): a
# comma-joined list of 100 UUIDs is ~3.7 KB, safely inside proxy query limits.
MAX_BATCH_IDENTITY_IDS = 100


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


@router.get("/clusters/{cluster_id}/roster-candidates", response_model=RosterCandidatesResponse)
async def get_roster_candidates(
    cluster_id: str,
    _tenant_id: str = Depends(get_tenant_id),
    top_k: int = Query(default=DEFAULT_ROSTER_CANDIDATES_TOP_K),
    cluster_repo=Depends(get_cluster_repository),
) -> RosterCandidatesResponse:
    """Rank labelled clusters against this probe. Band from live settings; no raw % contract."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_top_k(top_k, max_top_k=MAX_ROSTER_CANDIDATES_TOP_K)
    try:
        result = await list_roster_candidates(
            _tenant_id,
            cluster_id,
            cluster_repository=cluster_repo,
            top_k=top_k,
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found") from None
    return RosterCandidatesResponse(
        model_id=result.model_id,
        embedding_model=result.embedding_model,
        computed_at=result.computed_at,
        probe_face_count=result.probe_face_count,
        reference_face_count=result.reference_face_count,
        quality_flag=result.quality_flag.value,
        thresholds=RosterCandidateThresholdsResponse(
            suggestion_floor=result.thresholds.suggestion_floor,
            suggestion_ceiling=result.thresholds.suggestion_ceiling,
            similarity_threshold=result.thresholds.similarity_threshold,
        ),
        candidates=[
            RosterCandidateResponse(
                cluster_id=row.cluster_id,
                name=row.name,
                similarity=row.similarity,
                band=row.band.value,
            )
            for row in result.candidates
        ],
    )


@router.get("/identities/suggestions", response_model=IdentityBatchSuggestionsResponse)
async def list_identities_suggestions(
    identity_ids: str = Query(description="Comma-joined identity UUIDs (max 100)."),
    _tenant_id: str = Depends(get_tenant_id),
    top_k: int = Query(default=1),
    suggestion_service=Depends(get_suggestion_service),
) -> IdentityBatchSuggestionsResponse:
    """Top-k labeled-cluster suggestions for a batch of identities, keyed by identity id.

    One bounded call for "top suggestion for each of these identities": response
    row count is <= len(identity_ids) x top_k by construction. Filter parity with
    the per-card route is literal (pending + truthy cluster label only).
    Out-of-range ``top_k`` is rejected with 400, never clamped (``MAX_TOP_K``,
    ``validate_paging`` convention).
    """
    raw_ids = [item.strip() for item in identity_ids.split(",")]
    if len(raw_ids) > MAX_BATCH_IDENTITY_IDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"identity_ids exceeds maximum of {MAX_BATCH_IDENTITY_IDS}",
        )
    validated_ids = [validate_entity_id(item, field_name="identity_ids") for item in raw_ids]
    validate_top_k(top_k)

    grouped = await suggestion_service.list_for_identities(validated_ids, top_k=top_k)
    matches: dict[str, list[ClusterSuggestionMatch]] = {}
    for identity_id, rows in grouped.items():
        identity_matches: list[ClusterSuggestionMatch] = []
        for row in rows:
            if not row.cluster_label:
                # The windowed query filters to truthy labels; guard narrows the optional type.
                continue
            identity_matches.append(
                ClusterSuggestionMatch(
                    suggestion_id=row.id,
                    cluster_id=row.cluster_id,
                    label=row.cluster_label,
                    similarity=row.representative_similarity,
                    identity_count=row.cluster_identity_count or 0,
                )
            )
        if identity_matches:
            matches[identity_id] = identity_matches

    return IdentityBatchSuggestionsResponse(matches=matches)


@router.get("/identities/{identity_id}/suggestions", response_model=IdentitySuggestionsResponse)
async def list_suggestions(
    identity_id: str,
    _tenant_id: str = Depends(get_tenant_id),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    top_k: int | None = Query(default=None),
    suggestion_service=Depends(get_suggestion_service),
    cluster_repo=Depends(get_cluster_repository),
) -> IdentitySuggestionsResponse:
    """List pending suggestions for an identity with enriched cluster data.

    Returns suggestions in frontend-compatible format with cluster labels
    and member counts. Only returns suggestions for labeled clusters - unlabeled
    cluster suggestions are not actionable (asking "Is this Unnamed cluster?" is meaningless).

    ``top_k`` bounds the match count after ranking (UXP-2 3a: previously accepted
    but silently ignored); omitting it keeps the unbounded behavior. Out-of-range
    ``top_k`` is rejected with 400, never clamped (``MAX_TOP_K``,
    ``validate_paging`` convention).
    """
    validate_entity_id(identity_id, field_name="identity_id")
    if top_k is not None:
        validate_top_k(top_k)
    suggestions = await suggestion_service.list_for_identity(identity_id)
    if min_confidence is not None:
        suggestions = [suggestion for suggestion in suggestions if _meets_min_confidence(suggestion, min_confidence)]

    # Enrich suggestions with cluster details in one batched fetch - only include labeled clusters
    cluster_ids = list({suggestion.cluster_id for suggestion in suggestions})
    clusters = await cluster_repo.get_by_ids(cluster_ids) if cluster_ids else []
    clusters_by_id = {cluster.id: cluster for cluster in clusters}

    matches: list[ClusterSuggestionMatch] = []
    for suggestion in suggestions:
        cluster = clusters_by_id.get(suggestion.cluster_id)
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

    # Sort by similarity descending; the stable sort keeps the repository's
    # created_at DESC ordering as the tie-break, matching the batch route's window.
    matches.sort(key=lambda m: m.similarity, reverse=True)
    if top_k is not None:
        matches = matches[:top_k]

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
    except ReservedClusterLabelError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None

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
    suggestion_service=Depends(get_suggestion_service),
    cluster_service_builder=Depends(get_cluster_service_builder),
    cluster_repo: SqlAlchemyClusterRepository = Depends(get_cluster_repository),
    merge_repo: SqlAlchemyMergeSuggestionRepository = Depends(get_merge_suggestion_repository),
) -> BulkAcceptResponse:
    """Bulk-accept suggestions by type and confidence threshold."""
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    if request.suggestion_type == "name":
        result = await suggestion_extension_service.bulk_accept(
            request.tenant_id,
            suggestion_type="name",
            min_confidence=request.min_confidence,
        )
    elif request.suggestion_type == "assignment":
        result = await _bulk_accept_assignments(
            request.tenant_id,
            min_confidence=request.min_confidence,
            suggestion_extension_service=suggestion_extension_service,
            suggestion_service=suggestion_service,
            cluster_service_builder=cluster_service_builder,
        )
    elif request.suggestion_type == "merge":
        result = await _bulk_accept_merges(
            request.tenant_id,
            min_confidence=request.min_confidence,
            suggestion_extension_service=suggestion_extension_service,
            cluster_service_builder=cluster_service_builder,
            cluster_repo=cluster_repo,
            merge_repo=merge_repo,
        )
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unsupported suggestion_type")

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

    cluster_service = await cluster_service_builder(request.tenant_id)
    cluster_repo = cluster_service.assignment_writer.cluster_repository

    # E215-BR-02: non-PENDING ACCEPTED replay still stamps authoritative ids
    # (resolve survivor via cluster existence, or re-rank if both still present).
    if suggestion.status != SuggestionStatus.PENDING:
        if suggestion.status == SuggestionStatus.ACCEPTED:
            source_id, target_id = await _resolve_accepted_merge_ids(suggestion, cluster_repo)
            return _to_merge_response(
                suggestion,
                source_cluster_id=source_id,
                target_cluster_id=target_id,
            )
        return _to_merge_response(suggestion)

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

    # Authoritative survivor/retired ids from _select_merge_target (source=retired,
    # target=survivor). Clients must not re-rank cluster_a/b presentation fields.
    return _to_merge_response(
        suggestion,
        source_cluster_id=source_cluster_id,
        target_cluster_id=target_cluster_id,
    )


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
    representatives: list[RepresentativeResponse] = [
        representative_response_from_domain(rep) for rep in (getattr(suggestion, "representatives", None) or [])
    ]
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
        representatives=representatives,
    )


def _is_meaningful_label(label: str | None) -> bool:
    """Return whether a label is operator-meaningful (non-empty, non-reserved)."""
    if label is None or not str(label).strip():
        return False
    return not is_reserved_label_shape(label)


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


async def _bulk_accept_assignments(
    tenant_id: str,
    *,
    min_confidence: float,
    suggestion_extension_service: SuggestionExtensionService,
    suggestion_service: SuggestionService,
    cluster_service_builder: Callable[[str], Awaitable[ClusterService]],
) -> BulkAcceptResult:
    """Bulk-accept assignment suggestions with full cluster-assignment side effects."""
    candidates = await suggestion_extension_service.list_pending_assignment_candidates(
        tenant_id, min_confidence=min_confidence
    )
    cluster_service = await cluster_service_builder(tenant_id)
    accepted = 0
    skipped = 0
    for candidate in candidates:
        suggestion = await suggestion_service.accept(candidate.id)
        if suggestion is None:
            skipped += 1
            continue
        assigned = await cluster_service.assign_outlier_to_cluster(
            identity_id=candidate.identity_id,
            target_cluster_id=candidate.cluster_id,
            tenant_id=tenant_id,
            similarity=candidate.representative_similarity,
        )
        if assigned is None:
            skipped += 1
            continue
        await suggestion_service.resolve_for_identity_exclusive(
            identity_id=candidate.identity_id,
            accepted_cluster_id=candidate.cluster_id,
            reason="bulk_accept",
        )
        accepted += 1
    return BulkAcceptResult(accepted_count=accepted, skipped_count=skipped)


async def _bulk_accept_merges(
    tenant_id: str,
    *,
    min_confidence: float,
    suggestion_extension_service: SuggestionExtensionService,
    cluster_service_builder: Callable[[str], Awaitable[ClusterService]],
    cluster_repo: SqlAlchemyClusterRepository,
    merge_repo: SqlAlchemyMergeSuggestionRepository,
) -> BulkAcceptResult:
    """Bulk-accept merge suggestions with full cluster-merge side effects."""
    candidates = await suggestion_extension_service.list_pending_merge_candidates(
        tenant_id, min_confidence=min_confidence
    )
    cluster_service = await cluster_service_builder(tenant_id)
    accepted = 0
    skipped = 0
    for candidate in candidates:
        cluster_a = await cluster_repo.get_by_id(candidate.cluster_a_id)
        cluster_b = await cluster_repo.get_by_id(candidate.cluster_b_id)
        if not cluster_a or not cluster_b:
            skipped += 1
            continue
        try:
            source_cluster_id, target_cluster_id, target_label = _select_merge_target(cluster_a, cluster_b)
        except HTTPException:
            skipped += 1
            continue
        merged = await cluster_service.merge_cluster(
            source_cluster_id,
            tenant_id,
            target_cluster_id,
            target_label=target_label,
            moved_by_merge_id=str(candidate.id),
        )
        if merged is None:
            skipped += 1
            continue
        await merge_repo.delete_by_cluster(tenant_id, source_cluster_id)
        await merge_repo.delete_by_cluster(tenant_id, target_cluster_id)
        accepted += 1
    return BulkAcceptResult(accepted_count=accepted, skipped_count=skipped)


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
    # Placeholder cluster-* labels must not enter merge's reserved-label guard;
    # None falls back to preserving target.label in the use case.
    selected_label = target.label if _is_meaningful_label(target.label) else None
    return source.id, target.id, selected_label


async def _resolve_accepted_merge_ids(
    suggestion: MergeSuggestion | MergeSuggestionDetails,
    cluster_repo: object,
) -> tuple[str | None, str | None]:
    """Stamp source/target on ACCEPTED replay (E215-BR-02).

    Prefer existence: the missing side is retired (source), the remaining side is
    survivor (target). When both still exist, re-run ``_select_merge_target``.
    """
    get_by_id = getattr(cluster_repo, "get_by_id", None)
    if get_by_id is None:
        return None, None
    cluster_a = await get_by_id(suggestion.cluster_a_id)
    cluster_b = await get_by_id(suggestion.cluster_b_id)
    if cluster_a and not cluster_b:
        return suggestion.cluster_b_id, suggestion.cluster_a_id
    if cluster_b and not cluster_a:
        return suggestion.cluster_a_id, suggestion.cluster_b_id
    if cluster_a and cluster_b:
        try:
            source_id, target_id, _ = _select_merge_target(cluster_a, cluster_b)
        except HTTPException:
            return None, None
        return source_id, target_id
    return None, None


def _to_merge_response(
    suggestion: MergeSuggestion | MergeSuggestionDetails,
    *,
    source_cluster_id: str | None = None,
    target_cluster_id: str | None = None,
) -> MergeSuggestionResponse:
    """Convert merge suggestion to API response model.

    Pass ``source_cluster_id`` / ``target_cluster_id`` after accept so the
    response carries the authoritative survivor/retired pair from
    ``_select_merge_target`` (source=retired, target=survivor).
    """
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
        source_cluster_id=source_cluster_id,
        target_cluster_id=target_cluster_id,
    )
