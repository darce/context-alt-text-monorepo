"""
Cluster management routes.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from db.session import async_session_factory
from recognition.application.suggestions.service import SuggestionRefreshReason
from recognition.config.security import get_security_settings
from recognition.domain.job import JobType, SplitJobPayload
from recognition.infrastructure.repositories import SqlAlchemyIdentityClusterBlockRepository
from recognition.interface_adapters.http.dependencies import (
    build_cluster_service,
    get_cluster_repository,
    get_cluster_service_builder,
    get_job_service,
    get_session,
    get_suggestion_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.job_utils import (
    job_to_clustering_response as _job_to_clustering_response,
)
from recognition.interface_adapters.http.schemas.requests import (
    AssignOutlierRequest,
    ClusteringJobRequest,
    CreateClusterForIdentityRequest,
    MergeClusterRequest,
    PatchClusterRequest,
    PinRepresentativeRequest,
    ReassignIdentityRequest,
    SplitClusterRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    AsyncSplitClusterResponse,
    ClusteringJobStatusResponse,
    ClusterResponse,
    CreateClusterForIdentityResponse,
    JobProgressResponse,
    ReassignIdentityResponse,
    SplitClusterResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_label, validate_paging
from recognition.shared.ids import generate_id

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth)])


async def run_background_retry(tenant_id: str, cluster_id: str) -> None:
    """Execute post-merge matching retry in a background task with fresh session."""
    try:
        async with async_session_factory() as session:
            # We don't pass settings here, defaulting to env vars which is fine for background tasks
            cluster_service = await build_cluster_service(session=session, tenant_id=tenant_id)
            await cluster_service.retry_matching(target_cluster_id=cluster_id, tenant_id=tenant_id)
    except Exception as exc:
        _logger.exception("Background merge retry failed for cluster %s: %s", cluster_id, exc)


@router.post("/clustering/jobs", response_model=ClusteringJobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_clustering_job(
    request: ClusteringJobRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ClusteringJobStatusResponse:
    """Trigger clustering for unclustered identities."""
    _logger.info("Clustering request: tenant_id=%s, mode=%s", request.tenant_id, request.mode)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    job_service = await get_job_service(
        session=session,
        tenant_id=request.tenant_id,
        cluster_service_builder=lambda tid: cluster_service,
        scan_service_builder=None,
    )

    if request.mode == "sync":
        try:
            result = await cluster_service.cluster_unclustered_identities(request.tenant_id)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
        finished_at = getattr(result, "finished_at", None)
        completed = getattr(result, "completed", 0)
        total = getattr(result, "total", 0)
        clusters_created = getattr(result, "clusters_created", 0)
        job_id = getattr(result, "job_id", str(generate_id()))
        return ClusteringJobStatusResponse(
            id=str(job_id),
            type=JobType.CLUSTERING.value,
            status="completed",
            progress=JobProgressResponse(completed=completed, total=total),
            started_at=result.started_at if hasattr(result, "started_at") else datetime.now(tz=UTC),
            finished_at=finished_at,
            clusters_created=clusters_created,
            total_identities_clustered=completed,
        )

    job = await job_service.create_job(JobType.CLUSTERING, tenant_id=request.tenant_id)
    job = await job_service.start_job(job.id)
    return _job_to_clustering_response(job)


@router.get("/clusters", response_model=list[ClusterResponse])
async def list_clusters(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(50),
    offset: int = Query(0),
    include_outliers: bool = Query(False),
    labeled_only: bool = Query(False),
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> list[ClusterResponse]:
    """List clusters with paging."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    cluster_service = await cluster_service_builder(tenant_id)
    return await cluster_service.list_clusters(
        tenant_id,
        limit=limit,
        offset=offset,
        include_outliers=include_outliers,
        labeled_only=labeled_only,
    )


@router.get("/clusters/top-unlabeled", response_model=list[ClusterResponse])
async def get_top_unlabeled_clusters(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(10),
    repo=Depends(get_cluster_repository),
) -> list[ClusterResponse]:
    """Fetch top unlabeled clusters by member count for bootstrapping suggestions."""
    clusters = await repo.get_top_unlabeled(tenant_id, limit=limit)
    return [
        ClusterResponse(
            id=str(c.id),
            tenant_id=tenant_id,
            label=c.label,
            is_labeled=c.is_labeled,
            is_auto_label=c.is_auto_label,
            identity_count=c.identity_count,
            user_confirmed=c.user_confirmed,
        )
        for c in clusters
    ]


@router.patch("/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: PatchClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ClusterResponse:
    """Update cluster label."""
    label = validate_label(request.label)
    validate_entity_id(cluster_id, field_name="cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    cluster = await cluster_service.update_cluster(cluster_id, request.tenant_id, label=label)
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    return cluster


@router.post("/clusters/create-for-identity", response_model=CreateClusterForIdentityResponse)
async def create_cluster_for_identity(
    request: CreateClusterForIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> CreateClusterForIdentityResponse:
    """Create a new labeled cluster for a single identity."""
    validate_entity_id(request.identity_id, field_name="identity_id")
    label = validate_label(request.label)
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    try:
        cluster = await cluster_service.create_cluster_for_identity(
            identity_id=request.identity_id,
            label=label,
            tenant_id=request.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not cluster or not cluster.id:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Cluster creation failed")

    return CreateClusterForIdentityResponse(
        cluster_id=cluster.id,
        label=cluster.label or label,
        identity_id=request.identity_id,
        message="Cluster created",
    )


@router.post("/clusters/{cluster_id}/merge", response_model=ClusterResponse)
async def merge_cluster(
    cluster_id: str,
    request: MergeClusterRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ClusterResponse:
    """Merge cluster into target (by label)."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    cluster = await cluster_service.merge_cluster(
        source_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        target_cluster_id=request.target_cluster_id,
        target_label=request.target_label,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")

    # Schedule best-effort retry matching in background
    background_tasks.add_task(run_background_retry, request.tenant_id, request.target_cluster_id)

    # Refresh suggestions for the target cluster
    suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
    await suggestion_service.refresh_for_cluster(request.target_cluster_id)

    return cluster


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse | AsyncSplitClusterResponse)
async def split_cluster(
    cluster_id: str,
    request: SplitClusterRequest,
    response: Response,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> SplitClusterResponse | AsyncSplitClusterResponse:
    """
    Split a cluster using hierarchical clustering.

    If n_clusters=0 (default), automatically determines the optimal split
    based on face similarity. If n_clusters>=2, forces exactly that many groups.
    The largest group stays in the original cluster; others become new clusters.

    If mode="async", the split is queued and returns 202 Accepted with a job ID.
    """
    validate_entity_id(cluster_id, field_name="cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    if request.mode == "async":
        job_service = await get_job_service(session=session, tenant_id=request.tenant_id)
        payload = SplitJobPayload(
            cluster_id=cluster_id,
            n_clusters=request.n_clusters,
            anchor_identity_id=request.anchor_identity_id,
            split_mode=request.split_mode,
        )
        job = await job_service.queue_split(tenant_id=request.tenant_id, payload=payload)
        response.status_code = status.HTTP_202_ACCEPTED
        return AsyncSplitClusterResponse(
            job_id=job.id,
            status=job.status.value,
            message=f"Split operation queued for cluster {cluster_id[:8]}",
        )

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    new_ids, counts = await cluster_service.split_cluster(
        cluster_id,
        n_clusters=request.n_clusters,
        anchor_identity_id=request.anchor_identity_id,
        split_mode=request.split_mode,
        recompute=False,
    )
    if new_ids:
        job_service = await get_job_service(
            session=session,
            tenant_id=request.tenant_id,
            cluster_service_builder=lambda _tid: cluster_service,
            scan_service_builder=None,
        )
        await job_service.queue_curation_followup(
            tenant_id=request.tenant_id,
            cluster_ids=[cluster_id, *new_ids],
        )

    # Build response with both new list format and legacy single-cluster fields
    response_obj = SplitClusterResponse(
        new_cluster_ids=new_ids,
        moved_counts=counts,
        # Legacy fields: use first new cluster if any
        new_cluster_id=new_ids[0] if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )

    # Refresh suggestions for affected clusters
    suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
    for cid in [cluster_id, *new_ids]:
        await suggestion_service.refresh_for_cluster(cid)

    return response_obj


@router.post("/clusters/reassign", response_model=ReassignIdentityResponse)
async def reassign_identity(
    request: ReassignIdentityRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ReassignIdentityResponse:
    """Reassign an identity to a different cluster.

    This endpoint is used for:
    - Accepting inline suggestions (moving singleton to labeled cluster)
    - Correcting misassigned identities
    - Removing from cluster (set target_cluster_id to null)

    When reassigning to a cluster, any pending suggestion for that identity+cluster
    is automatically marked as accepted.
    """
    from recognition.interface_adapters.http.dependencies import get_suggestion_service

    validate_entity_id(request.identity_id, field_name="identity_id")
    if request.target_cluster_id:
        validate_entity_id(request.target_cluster_id, field_name="target_cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)

    # Get identity's current cluster (if any)
    source_cluster_id = await cluster_service.get_identity_cluster_id(request.identity_id)

    if request.target_cluster_id:
        block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
        await block_repo.remove_block(
            tenant_id=request.tenant_id,
            identity_id=request.identity_id,
            blocked_cluster_id=request.target_cluster_id,
        )
        # Assign to target cluster
        result = await cluster_service.assign_outlier_to_cluster(
            identity_id=request.identity_id,
            target_cluster_id=request.target_cluster_id,
            tenant_id=request.tenant_id,
            similarity=0.0,  # Not known at this point
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Identity or target cluster not found",
            )

        # Resolve any pending suggestion for this identity+cluster as accepted
        suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
        resolve_exclusive = getattr(suggestion_service, "resolve_for_identity_exclusive", None)
        if callable(resolve_exclusive):
            await resolve_exclusive(
                identity_id=request.identity_id,
                accepted_cluster_id=request.target_cluster_id,
                reason="manual_assign",
            )
        else:
            await suggestion_service.resolve_for_identity(
                identity_id=request.identity_id,
                cluster_id=request.target_cluster_id,
                resolution="accepted",
            )
        refresh_for_identity = getattr(suggestion_service, "refresh_for_identity", None)
        if callable(refresh_for_identity):
            await refresh_for_identity(
                identity_id=request.identity_id,
                reason=SuggestionRefreshReason.MANUAL_ASSIGN,
            )
    else:
        # Remove from current cluster (make orphan)
        await cluster_service.remove_identity_from_cluster(request.identity_id, recompute=False)
        if source_cluster_id:
            if request.block_from_cluster:
                block_repo = SqlAlchemyIdentityClusterBlockRepository(session, tenant_id=request.tenant_id)
                await block_repo.add_block(
                    tenant_id=request.tenant_id,
                    identity_id=request.identity_id,
                    blocked_cluster_id=source_cluster_id,
                    reason="manual_removal",
                )

                # Create CANNOT_LINK constraint to permanently prevent linking
                try:
                    from recognition.domain.constraints import ConstraintSource, ConstraintType
                    from recognition.infrastructure.repositories import SqlAlchemyConstraintRepository

                    # We need the cluster's representative to anchor the constraint
                    cluster_repo = cluster_service.assignment_writer._clusters
                    source_cluster = await cluster_repo.get_by_id(source_cluster_id)

                    if source_cluster and source_cluster.representative_identity_id:
                        constraint_repo = SqlAlchemyConstraintRepository(session)
                        with contextlib.suppress(Exception):
                            await constraint_repo.create(
                                tenant_id=request.tenant_id,
                                identity_a=request.identity_id,
                                identity_b=str(source_cluster.representative_identity_id),
                                constraint_type=ConstraintType.CANNOT_LINK.value,
                                source=ConstraintSource.WRONG_PERSON.value,
                                created_by_user_id=None,  # User ID not currently available in request
                            )
                except Exception as exc:
                    # Don't fail the request if constraint creation fails
                    _logger.warning(
                        "Failed to create CANNOT_LINK constraint for identity %s: %s", request.identity_id, exc
                    )

            job_service = await get_job_service(
                session=session,
                tenant_id=request.tenant_id,
                cluster_service_builder=lambda _tid: cluster_service,
                scan_service_builder=None,
            )
            await job_service.queue_curation_followup(
                tenant_id=request.tenant_id,
                cluster_ids=[source_cluster_id],
                identity_ids=[request.identity_id],
            )
        suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
        if source_cluster_id:
            await suggestion_service.resolve_for_identity(
                identity_id=request.identity_id,
                cluster_id=source_cluster_id,
                resolution="rejected",
            )
        refresh_for_identity = getattr(suggestion_service, "refresh_for_identity", None)
        if callable(refresh_for_identity):
            await refresh_for_identity(
                identity_id=request.identity_id,
                reason=SuggestionRefreshReason.WRONG_PERSON,
            )

        # Refresh suggestions for the affected clusters
        if source_cluster_id:
            await suggestion_service.refresh_for_cluster(source_cluster_id)
        if request.target_cluster_id:
            await suggestion_service.refresh_for_cluster(request.target_cluster_id)

    return ReassignIdentityResponse(
        identity_id=request.identity_id,
        source_cluster_id=source_cluster_id,
        target_cluster_id=request.target_cluster_id,
        success=True,
    )


@router.post("/clusters/{cluster_id}/assign", response_model=ClusterResponse)
async def assign_outlier(
    cluster_id: str,
    request: AssignOutlierRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ClusterResponse:
    """Assign an unclustered identity (outlier) to an existing cluster."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(request.identity_id, field_name="identity_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    cluster = await cluster_service.assign_outlier_to_cluster(
        identity_id=request.identity_id,
        target_cluster_id=cluster_id,
        tenant_id=request.tenant_id,
        similarity=request.similarity,
    )
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster or identity not found")

    # Refresh suggestions for the target cluster
    suggestion_service = await get_suggestion_service(session=session, tenant_id=request.tenant_id)
    await suggestion_service.refresh_for_cluster(cluster_id)

    return cluster


@router.patch("/clusters/{cluster_id}/representatives/{representative_id}/pin", status_code=status.HTTP_204_NO_CONTENT)
async def pin_representative(
    cluster_id: str,
    representative_id: str,
    request: PinRepresentativeRequest,
    auth=Depends(require_write_access),
    repo=Depends(get_cluster_repository),
) -> None:
    """Pin or unpin a cluster representative."""
    validate_entity_id(cluster_id, field_name="cluster_id")
    validate_entity_id(representative_id, field_name="representative_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    await repo.mark_representative_user_selected(
        representative_id=representative_id,
        is_selected=request.is_pinned,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# _job_to_response and _job_to_clustering_response are imported from job_utils
