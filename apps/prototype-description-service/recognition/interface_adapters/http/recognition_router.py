"""Recognition HTTP routes for analysis and clustering."""

from __future__ import annotations

import logging
from typing import TypeVar
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import IdentityCluster, IdentityScanJob, MediaIdentity, Tenant
from db.session import async_session_factory, get_session
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


def get_embedding_provider() -> FaceEmbeddingProvider:
    """Provide a FaceEmbeddingProvider instance for dependency injection."""
    return FaceEmbeddingProvider()


router = APIRouter(tags=["recognition"])


class MediaItem(BaseModel):
    media_id: int
    media_url: HttpUrl


class AnalyzeRequest(BaseModel):
    tenant_id: UUID
    site_url: HttpUrl | None = None
    media_items: list[MediaItem] = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Attachment IDs and URLs to analyze (chunked server-side into batches of 10).",
    )
    user_id: int | None = None


class AnalyzeResponse(BaseModel):
    job_ids: list[UUID]  # List of job IDs for each processed chunk
    job_id: UUID | None = Field(
        default=None,
        description="Primary job ID for backward compatibility (first job in the list).",
    )
    status: str
    total_media: int


T = TypeVar("T")


def _chunk_items(items: list[T], size: int) -> list[list[T]]:
    """Split a list into chunks of given size."""
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _process_scan_chunk(
    job_id: UUID,
    tenant_id: UUID,
    media_items: list[dict[str, object]],
    user_id: int | None,
) -> None:
    """Run a scan job in the background using a fresh session and provider."""
    async with async_session_factory() as session:
        try:
            await set_tenant_context(session, tenant_id)
            provider = FaceEmbeddingProvider()
            service = IdentityScanService(session, provider, tenant_id)
            job = await session.get(IdentityScanJob, job_id)
            if not job:
                logger.error("Background scan job %s not found for tenant %s", job_id, tenant_id)
                return
            await service.scan_identities(job, media_items, user_id)
        except Exception:
            logger.exception("Background scan job %s failed", job_id)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> AnalyzeResponse:
    """
    Enqueue chunked scan jobs and return immediately so the caller is not blocked by long-running inference.
    """
    await set_tenant_context(session, request.tenant_id)
    await _ensure_tenant(session, request.tenant_id, request.site_url)

    # Split media items into chunks of 10 to avoid timeouts
    chunks = _chunk_items(request.media_items, 10)
    job_ids: list[UUID] = []
    total_media = len(request.media_items)

    for chunk in chunks:
        # Re-set tenant context for each chunk (RLS requirement after commit)
        await set_tenant_context(session, request.tenant_id)

        job = IdentityScanJob(
            tenant_id=request.tenant_id,
            status="pending",
            media_ids=[item.media_id for item in chunk],
            total_media=len(chunk),
            created_by_user_id=request.user_id,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
        logger.info("Created IdentityScanJob with ID: %s", job_id)
        job_ids.append(job_id)

        background_tasks.add_task(
            _process_scan_chunk,
            job_id,
            request.tenant_id,
            [item.model_dump() for item in chunk],
            request.user_id,
        )

    await session.commit()

    primary_job = job_ids[0] if job_ids else None
    return AnalyzeResponse(job_ids=job_ids, job_id=primary_job, status="queued", total_media=total_media)


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
    source_label: str | None = None
    target_id: str
    target_label: str | None = None
    identities_moved: int
    moved_identity_ids: list[str] = Field(
        default_factory=list,
        description="Identity IDs moved from the source into the target cluster",
    )
    target_identity_count: int


class RevertMergeRequest(BaseModel):
    tenant_id: UUID
    target_cluster_id: UUID
    moved_identity_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Identity IDs that were moved during the merge operation.",
    )
    source_label: str | None = Field(
        None,
        max_length=255,
        description="Original label of the merged cluster (if available).",
    )
    user_id: int | None = None


class RevertMergeResponse(BaseModel):
    restored_cluster_id: str
    restored_label: str | None
    restored_identity_count: int
    target_cluster_id: str
    target_identity_count: int


class MergeSimilarRequest(BaseModel):
    tenant_id: UUID
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    max_iterations: int | None = Field(default=None, ge=1, le=10)


class MergeSimilarResponse(BaseModel):
    merges_performed: int


class SplitClusterRequest(BaseModel):
    tenant_id: UUID


class SplitClusterResponse(BaseModel):
    new_cluster_id: str | None
    moved_count: int


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


@router.get("/clusters/labels", response_model=list[str])
async def list_cluster_labels(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[str]:
    """Get a list of unique, user-assigned cluster labels for autocomplete."""
    await set_tenant_context(session, tenant_id)
    stmt = (
        select(IdentityCluster.label)
        .where(
            IdentityCluster.tenant_id == tenant_id,
            IdentityCluster.label.is_not(None),
            ~IdentityCluster.label.startswith("cluster-"),  # Exclude auto-generated labels
        )
        .distinct()
        .order_by(IdentityCluster.label)
    )
    result = await session.execute(stmt)
    labels = result.scalars().all()
    return [label for label in labels if label is not None]


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
        target, moved, moved_ids, source_label = await service.merge_cluster_into_label(
            source_id,
            request.target_label,
        )
    except ClusterNotFoundError:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return MergeClusterResponse(
        source_id=str(source_id),
        source_label=source_label,
        target_id=str(target.id),
        target_label=target.label,
        identities_moved=moved,
        moved_identity_ids=[str(identity_id) for identity_id in moved_ids],
        target_identity_count=target.identity_count,
    )


@router.post("/clusters/revert-merge", response_model=RevertMergeResponse)
async def revert_merge(
    request: RevertMergeRequest,
    session: AsyncSession = Depends(get_session),
) -> RevertMergeResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    try:
        restored, target = await service.revert_merge(
            target_cluster_id=request.target_cluster_id,
            moved_identity_ids=request.moved_identity_ids,
            source_label=request.source_label,
        )
    except ClusterNotFoundError:
        raise HTTPException(status_code=404, detail="Cluster not found")
    except ClusterLabelConflictError:
        raise HTTPException(status_code=409, detail="Label already exists for this tenant")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return RevertMergeResponse(
        restored_cluster_id=str(restored.id),
        restored_label=restored.label,
        restored_identity_count=restored.identity_count,
        target_cluster_id=str(target.id),
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


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse)
async def split_cluster(
    cluster_id: UUID,
    request: SplitClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> SplitClusterResponse:
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    new_id, count = await service.split_cluster(cluster_id)
    return SplitClusterResponse(
        new_cluster_id=str(new_id) if new_id else None,
        moved_count=count,
    )
