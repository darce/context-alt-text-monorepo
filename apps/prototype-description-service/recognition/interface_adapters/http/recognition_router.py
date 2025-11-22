"""Recognition HTTP routes for analysis and clustering."""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import IdentityCluster, IdentityScanJob, MediaIdentity, Tenant
from db.session import get_session
from db.tenant_context import set_tenant_context
from recognition.application.identity_clustering_service import (
    ClusterLabelConflictError,
    ClusterNotFoundError,
    IdentityClusteringService,
)
from recognition.application.identity_scan_service import IdentityScanService
from recognition.config import get_settings
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["recognition"])


class MediaItem(BaseModel):
    media_id: int
    media_url: HttpUrl


class AnalyzeRequest(BaseModel):
    tenant_id: UUID
    site_url: HttpUrl | None = None
    media_items: list[MediaItem] = Field(..., min_length=1, max_length=100)
    user_id: int | None = None


class AnalyzeResponse(BaseModel):
    job_id: UUID
    status: str
    total_media: int


class ClusterRequest(BaseModel):
    tenant_id: UUID
    similarity_threshold: float | None = 0.6


class ClusterResponse(BaseModel):
    clusters_created: int
    total_identities_clustered: int
    merges_performed: int = Field(
        default=0,
        description="Number of auto-merge operations performed",
    )
    job_id: str | None = None


class ClusterSummaryResponse(BaseModel):
    id: str
    label: str
    identity_count: int
    member_ids: list[str]
    representative_identity: dict
    sample_identities: list[dict]


class MediaIdentityBBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class MediaIdentityDetail(BaseModel):
    id: str
    media_id: int
    cluster_id: str | None
    cluster_label: str | None
    is_auto_label: bool = False
    bbox: MediaIdentityBBox
    confidence: float
    similarity: float | None
    detected_at: str | None
    thumbnail_url: str | None = None


class MediaIdentitiesResponse(BaseModel):
    identities_by_media: dict[str, list[MediaIdentityDetail]]


def _resolve_thumbnail_url(raw_url: str | None, request: Request) -> str | None:
    if not raw_url:
        return raw_url

    try:
        parsed_url = urlparse(raw_url)
    except ValueError:
        return raw_url

    # If the stored URL already points to a different origin (e.g., S3), leave it alone.
    settings = get_settings()
    configured = settings.thumbnail.base_url or ""
    configured_host = urlparse(configured).netloc if configured else ""

    if parsed_url.scheme and parsed_url.netloc:
        request_base = str(request.base_url).rstrip("/")
        if configured_host and parsed_url.netloc == configured_host:
            return f"{request_base}{parsed_url.path}"
        return raw_url

    path = raw_url if raw_url.startswith("/") else f"/{raw_url}"
    return f"{str(request.base_url).rstrip('/')}{path}"


class UpdateClusterLabelRequest(BaseModel):
    tenant_id: UUID
    label: str = Field(..., min_length=1, max_length=255)


class UpdateClusterLabelResponse(BaseModel):
    id: str
    label: str
    identity_count: int
    updated_at: str


class MergeClusterRequest(BaseModel):
    tenant_id: UUID
    target_label: str = Field(..., min_length=1, max_length=255)


class MergeClusterResponse(BaseModel):
    source_id: str
    target_id: str
    identities_moved: int
    target_identity_count: int


class MergeSimilarRequest(BaseModel):
    tenant_id: UUID
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    max_iterations: int | None = Field(default=None, ge=1, le=10)


class MergeSimilarResponse(BaseModel):
    merges_performed: int


class ClusteringJobResponse(BaseModel):
    id: str
    status: str
    progress: float
    total_identities: int | None = None
    processed_identities: int | None = None
    error_message: str | None = None


class StartClusteringJobResponse(BaseModel):
    status: str
    job_id: str | None = None
    clusters_created: int | None = None
    assigned: int | None = None


def get_embedding_provider() -> FaceEmbeddingProvider:
    return FaceEmbeddingProvider()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(
    request: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
    provider: FaceEmbeddingProvider = Depends(get_embedding_provider),
) -> AnalyzeResponse:
    await set_tenant_context(session, request.tenant_id)
    await _ensure_tenant(session, request.tenant_id, request.site_url)
    job = IdentityScanJob(
        tenant_id=request.tenant_id,
        status="pending",
        media_ids=[item.media_id for item in request.media_items],
        total_media=len(request.media_items),
        created_by_user_id=request.user_id,
    )

    session.add(job)
    await session.flush()
    # job remains pending; IdentityScanService will update status and commit.
    service = IdentityScanService(session, provider, request.tenant_id)
    await service.scan_identities(job, [item.model_dump() for item in request.media_items], request.user_id)

    try:
        await set_tenant_context(session, request.tenant_id)
        similarity_threshold = getattr(request, "similarity_threshold", None) or 0.6
        clustering_service = IdentityClusteringService(
            session=session,
            tenant_id=request.tenant_id,
            similarity_threshold=similarity_threshold,
        )
        await clustering_service.cluster_identities_incremental()
    except Exception:  # pragma: no cover - clustering is best-effort
        logger.exception("Failed to cluster identities automatically for tenant %s", request.tenant_id)
        await session.rollback()

    return AnalyzeResponse(job_id=job.id, status=job.status, total_media=job.total_media)


@router.post("/clustering/jobs", response_model=StartClusteringJobResponse)
async def start_clustering_job(
    tenant_id: UUID = Query(..., description="Tenant ID for RLS scoping"),
    session: AsyncSession = Depends(get_session),
) -> StartClusteringJobResponse:
    """Kick off clustering for all unclustered identities. Returns job_id if queued."""

    await set_tenant_context(session, tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)
    result = await service.cluster_identities_hybrid()

    if result["status"] == "complete":
        clusters_raw = result.get("clusters") or []
        clusters_list = clusters_raw if isinstance(clusters_raw, list) else []
        assigned_raw = result.get("assigned")
        assigned_count = assigned_raw if isinstance(assigned_raw, int) else 0
        return StartClusteringJobResponse(
            status="complete",
            job_id=None,
            clusters_created=len(clusters_list),
            assigned=assigned_count,
        )

    job_id_obj = result.get("job_id")
    assigned_raw = result.get("assigned")
    assigned_count = assigned_raw if isinstance(assigned_raw, int) else 0
    return StartClusteringJobResponse(
        status="pending",
        job_id=str(job_id_obj) if isinstance(job_id_obj, (UUID, str)) else None,
        clusters_created=None,
        assigned=assigned_count,
    )


@router.get("/clustering/jobs/{job_id}", response_model=ClusteringJobResponse)
async def get_clustering_job_status(
    job_id: UUID,
    tenant_id: UUID = Query(..., description="Tenant ID for RLS scoping"),
    session: AsyncSession = Depends(get_session),
) -> ClusteringJobResponse:
    await set_tenant_context(session, tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)
    job = await service.get_clustering_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    progress = float(job.progress or 0.0)
    return ClusteringJobResponse(
        id=str(job.id),
        status=job.status,
        progress=progress,
        total_identities=job.total_identities,
        processed_identities=job.processed_identities,
        error_message=job.error_message,
    )


async def _ensure_tenant(session: AsyncSession, tenant_id: UUID, site_url: HttpUrl | None) -> None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant:
        return
    if not site_url:
        raise HTTPException(status_code=400, detail="Unknown tenant. Provide site_url to bootstrap tenant record.")
    session.add(Tenant(id=tenant_id, site_url=str(site_url)))
    await session.flush()


@router.get("/jobs/{job_id}")
async def get_analysis_job(
    job_id: UUID,
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    await set_tenant_context(session, tenant_id)
    job = await session.get(IdentityScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_media": job.total_media,
        "processed_media": job.processed_media,
        "identities_detected": job.identities_detected,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/cluster", response_model=ClusterResponse)
async def cluster_media(
    request: ClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> ClusterResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(
        session=session,
        tenant_id=request.tenant_id,
        similarity_threshold=request.similarity_threshold or 0.6,
    )
    clusters = await service.cluster_identities_incremental()
    settings = get_settings()

    merges = 0
    if settings.identity_clustering.auto_merge_enabled:
        try:
            merges = await service.merge_similar_clusters(
                threshold=settings.identity_clustering.auto_merge_threshold,
                max_iterations=settings.identity_clustering.auto_merge_max_iterations,
            )
            if merges:
                logger.info(
                    "Auto-merged %d clusters for tenant %s",
                    merges,
                    request.tenant_id,
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Auto-merge failed for tenant %s: %s", request.tenant_id, exc)

    total_identities = sum(cluster.identity_count for cluster in clusters)
    return ClusterResponse(
        clusters_created=len(clusters),
        total_identities_clustered=total_identities,
        merges_performed=merges,
    )


@router.get("/clusters", response_model=list[ClusterSummaryResponse])
async def list_clusters(
    tenant_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[ClusterSummaryResponse]:
    await set_tenant_context(session, tenant_id)
    stmt = (
        select(IdentityCluster)
        .where(IdentityCluster.tenant_id == tenant_id)
        .order_by(IdentityCluster.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt)
    clusters = result.scalars().all()

    service = IdentityClusteringService(session, tenant_id)
    summaries: list[ClusterSummaryResponse] = []

    for cluster in clusters:
        summary = await service.get_cluster_summary(cluster.id)
        summaries.append(ClusterSummaryResponse(**summary))  # type: ignore[arg-type]

    return summaries


@router.get("/media/identities", response_model=MediaIdentitiesResponse)
async def get_media_identities(
    tenant_id: UUID,
    request: Request,
    media_ids: list[int] | None = Query(
        None,
        max_length=100,
    ),
    session: AsyncSession = Depends(get_session),
) -> MediaIdentitiesResponse:
    await set_tenant_context(session, tenant_id)
    resolved_ids: list[int] = list(media_ids or [])
    if not resolved_ids:
        for key, value in request.query_params.multi_items():
            if key in {"media_ids", "media_ids[]"} or key.startswith("media_ids["):
                try:
                    resolved_ids.append(int(value))
                except ValueError:
                    raise HTTPException(status_code=422, detail="media_ids must be integers")

    if not resolved_ids:
        raise HTTPException(status_code=422, detail="At least one media_id is required")
    if len(resolved_ids) > 100:
        raise HTTPException(status_code=422, detail="Too many media_ids (max 100)")

    stmt = (
        select(MediaIdentity)
        .where(
            MediaIdentity.tenant_id == tenant_id,
            MediaIdentity.media_id.in_(resolved_ids),
        )
        .options(selectinload(MediaIdentity.cluster_memberships))
    )
    result = await session.execute(stmt)
    identities = result.scalars().all()

    cluster_ids = {membership.cluster_id for identity in identities for membership in identity.cluster_memberships}

    cluster_labels: dict[UUID, tuple[str | None, bool]] = {}
    if cluster_ids:
        cluster_stmt = select(IdentityCluster).where(IdentityCluster.id.in_(cluster_ids))
        cluster_result = await session.execute(cluster_stmt)
        for cluster in cluster_result.scalars().all():
            label = cluster.label or None
            is_auto = bool(label and label.startswith("cluster-"))
            cluster_labels[cluster.id] = (label, is_auto)

    identities_by_media: dict[str, list[MediaIdentityDetail]] = {}
    for media_id in resolved_ids:
        media_entries = [identity for identity in identities if identity.media_id == media_id]
        details: list[MediaIdentityDetail] = []
        for identity in media_entries:
            membership = identity.cluster_memberships[0] if identity.cluster_memberships else None
            cluster_id = str(membership.cluster_id) if membership else None
            label_info = cluster_labels.get(membership.cluster_id) if membership else None
            cluster_label = label_info[0] if label_info else None
            is_auto_label = label_info[1] if label_info else False
            details.append(
                MediaIdentityDetail(
                    id=str(identity.id),
                    media_id=identity.media_id,
                    cluster_id=cluster_id,
                    cluster_label=cluster_label,
                    is_auto_label=is_auto_label,
                    bbox=MediaIdentityBBox(
                        x=identity.bbox_x,
                        y=identity.bbox_y,
                        width=identity.bbox_width,
                        height=identity.bbox_height,
                    ),
                    confidence=identity.confidence,
                    similarity=membership.similarity if membership else None,
                    detected_at=identity.created_at.isoformat() if identity.created_at else None,
                    thumbnail_url=_resolve_thumbnail_url(getattr(identity, "thumbnail_url", None), request),
                )
            )
        identities_by_media[str(media_id)] = details

    return MediaIdentitiesResponse(identities_by_media=identities_by_media)


@router.patch("/clusters/{cluster_id}", response_model=UpdateClusterLabelResponse)
async def update_cluster_label(
    cluster_id: UUID,
    request: UpdateClusterLabelRequest,
    session: AsyncSession = Depends(get_session),
) -> UpdateClusterLabelResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    try:
        cluster = await service.rename_cluster(cluster_id, request.label)
    except ClusterNotFoundError:
        raise HTTPException(status_code=404, detail="Cluster not found")
    except ClusterLabelConflictError:
        raise HTTPException(status_code=409, detail="Label already exists for this tenant")

    return UpdateClusterLabelResponse(
        id=str(cluster.id),
        label=cluster.label or "",
        identity_count=cluster.identity_count,
        updated_at=cluster.updated_at.isoformat() if cluster.updated_at else "",
    )


@router.post("/clusters/{source_id}/merge", response_model=MergeClusterResponse)
async def merge_cluster(
    source_id: UUID,
    request: MergeClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> MergeClusterResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    try:
        target, moved = await service.merge_cluster_into_label(source_id, request.target_label)
    except ClusterNotFoundError:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return MergeClusterResponse(
        source_id=str(source_id),
        target_id=str(target.id),
        identities_moved=moved,
        target_identity_count=target.identity_count,
    )


@router.post("/clusters/merge-similar", response_model=MergeSimilarResponse)
async def merge_similar_clusters(
    request: MergeSimilarRequest,
    session: AsyncSession = Depends(get_session),
) -> MergeSimilarResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    settings = get_settings()
    max_iterations = request.max_iterations or settings.identity_clustering.auto_merge_max_iterations
    merges = await service.merge_similar_clusters(
        threshold=request.threshold,
        max_iterations=max_iterations,
    )
    return MergeSimilarResponse(merges_performed=merges)
