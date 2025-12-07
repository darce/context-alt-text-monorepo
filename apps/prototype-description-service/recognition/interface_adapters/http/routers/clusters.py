"""
Cluster management routes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.config.security import get_security_settings
from recognition.domain.job import Job, JobType
from recognition.interface_adapters.http.dependencies import (
    build_cluster_service,
    get_cluster_service_builder,
    get_job_service,
    get_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.schemas.requests import (
    AssignOutlierRequest,
    ClusteringJobRequest,
    MergeClusterRequest,
    PatchClusterRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    ClusteringJobStatusResponse,
    ClusterResponse,
    JobProgressResponse,
    JobStatusResponse,
)
from recognition.interface_adapters.http.validation import validate_entity_id, validate_label, validate_paging
from recognition.shared.ids import generate_id

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth)])


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
    cluster_service_builder=Depends(get_cluster_service_builder),
) -> list[ClusterResponse]:
    """List clusters with paging."""
    settings = get_security_settings()
    validate_paging(limit, offset, settings.max_page_size)
    cluster_service = await cluster_service_builder(tenant_id)
    return await cluster_service.list_clusters(tenant_id, limit=limit, offset=offset, include_outliers=include_outliers)


@router.patch("/clusters/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    request: PatchClusterRequest,
    auth=Depends(require_write_access),
    session=Depends(get_session),
) -> ClusterResponse:
    """Update cluster label."""
    _ = validate_label(request.label)
    validate_entity_id(cluster_id, field_name="cluster_id")
    if auth and auth.tenant_claim and auth.tenant_claim != request.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
    cluster_service = await build_cluster_service(session=session, tenant_id=request.tenant_id)
    cluster = await cluster_service.update_cluster(cluster_id, request.tenant_id, label=request.label)
    if not cluster:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster not found")
    return cluster


@router.post("/clusters/{cluster_id}/merge", response_model=ClusterResponse)
async def merge_cluster(
    cluster_id: str,
    request: MergeClusterRequest,
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
    return cluster


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
    return cluster


def _job_to_response(job: Job) -> JobStatusResponse:
    """Convert Job domain object to API response."""
    progress = JobProgressResponse(completed=job.progress_completed, total=job.progress_total)
    started_at = job.started_at or datetime.now(tz=UTC)
    return JobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
    )


def _job_to_clustering_response(job: Job) -> ClusteringJobStatusResponse:
    """Convert Job domain object to clustering API response."""
    progress = JobProgressResponse(completed=job.progress_completed, total=job.progress_total)
    started_at = job.started_at or datetime.now(tz=UTC)
    return ClusteringJobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
        clusters_created=0,  # Not known until job completes
        total_identities_clustered=job.progress_completed,
    )
