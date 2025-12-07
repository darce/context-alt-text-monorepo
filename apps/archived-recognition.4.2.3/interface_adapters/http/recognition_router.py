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
from recognition.application.clustering.clustering_settings import (
    ClusteringSettings as ClusteringSettingsModel,
)
from recognition.application.clustering.identity_clustering_service import (
    ClusterLabelConflictError,
    ClusterNotFoundError,
    IdentityClusteringService,
)
from recognition.application.clustering.suggestion_service import SuggestionService
from recognition.application.scanning.identity_scan_service import IdentityScanService
from recognition.config import get_settings
from recognition.domain.embeddings.layout import PoseMetrics, decode_debug_metrics
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


# NOTE: ClusterRequest and ClusterResponse were removed as dead code.
# The old POST /cluster endpoint was removed in favor of POST /clustering/jobs.


class ClusterSummaryResponse(BaseModel):
    id: str
    label: str | None = None
    is_auto_label: bool = False
    identity_count: int
    member_ids: list[str]
    representative_identity: dict
    sample_identities: list[dict]


class MediaIdentityBBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class DebugMetrics(BaseModel):
    """InsightFace debug metrics extracted from extended embeddings."""

    pose: PoseMetrics  # pitch, yaw, roll in degrees
    age: float
    gender: str  # 'female' or 'male'
    det_score: float  # detection confidence [0, 1]
    bbox_area: int  # bounding box area in pixels²
    landmark_quality: float  # std deviation of landmark positions
    # Clustering decision info
    clustering_method: str | None = None  # e.g., 'representative_match', 'centroid_match', 'new_cluster'
    clustering_algorithm: str | None = None  # e.g., 'cosine_similarity', 'chinese_whispers', 'hdbscan'
    similarity_threshold: float | None = None  # threshold used for cluster assignment
    match_similarity: float | None = None  # actual similarity score when matched


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
    debug_metrics: DebugMetrics | None = None


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
    n_clusters: int = 0  # 0 = auto-detect, 2+ = fixed number of clusters


class SplitClusterResponse(BaseModel):
    """Response for split operation. Returns lists for multi-way splits."""

    new_cluster_ids: list[str]  # IDs of newly created clusters
    moved_counts: list[int]  # Number of identities moved to each new cluster
    # Legacy single-cluster fields for backward compatibility
    new_cluster_id: str | None = None
    moved_count: int = 0


# === Suggestion Models ===


class SuggestionResponse(BaseModel):
    """A pending suggestion for user review."""

    id: str
    identity_id: str
    identity_thumbnail_url: str | None
    identity_media_id: int
    suggested_cluster_id: str
    cluster_label: str | None
    cluster_thumbnail_url: str | None
    representative_similarity: float
    avg_member_similarity: float
    confidence_score: float
    created_at: str


class SuggestionsListResponse(BaseModel):
    """List of pending suggestions with count."""

    suggestions: list[SuggestionResponse]
    total_count: int


class SuggestionActionResponse(BaseModel):
    """Response after accepting or rejecting a suggestion."""

    suggestion_id: str
    resolution: str
    identity_id: str
    cluster_id: str
    message: str


class ReassignIdentityRequest(BaseModel):
    """Request to reassign an identity to a different cluster or create a new one."""

    tenant_id: UUID
    identity_id: UUID
    target_cluster_id: UUID | None = Field(
        None,
        description="Target cluster UUID. If null, the identity is removed from its current cluster.",
    )
    target_label: str | None = Field(
        None,
        max_length=255,
        description="Optional: create or find a cluster with this label instead of using target_cluster_id.",
    )
    user_id: int | None = None


class ReassignIdentityResponse(BaseModel):
    """Response for identity reassignment."""

    identity_id: str
    previous_cluster_id: str | None
    target_cluster_id: str | None
    target_label: str | None
    created_new_cluster: bool = False
    message: str


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
    result = await service.cluster_unclustered_identities()

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


# NOTE: The old POST /cluster endpoint was removed as dead code.
# It used a legacy clustering path which did NOT run Chinese Whispers.
# All clustering should go through POST /clustering/jobs which uses cluster_unclustered_identities().


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


class TrainingStageResponse(BaseModel):
    """Training stage info based on curriculum learning principles."""

    stage: str  # 'early', 'developing', 'mature'
    stage_label: str  # Human-readable label
    cluster_count: int  # Total labeled clusters
    identity_count: int  # Total detected identities
    current_threshold: float  # Active similarity threshold
    base_threshold: float  # Base threshold (at maturity)
    strict_threshold: float  # Strict threshold (early stage)
    maturity_point: int  # Cluster count for maturity
    progress_percent: int  # 0-100 progress to maturity


@router.get("/training-stage", response_model=TrainingStageResponse)
async def get_training_stage(
    tenant_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> TrainingStageResponse:
    """Get current training stage based on curriculum learning.

    The system uses adaptive thresholds inspired by CurricularFace:
    - Early stage (few clusters): Strict thresholds to avoid false positives
    - Developing stage: Thresholds gradually relax as clusters are validated
    - Mature stage (30+ clusters): Base threshold reached, system is stable

    This helps users understand why some matches may not auto-assign.
    """
    await set_tenant_context(session, tenant_id)

    # Get cluster count (labeled clusters only, excluding auto-generated labels)
    labeled_stmt = select(IdentityCluster).where(
        IdentityCluster.tenant_id == tenant_id,
        IdentityCluster.label.is_not(None),
        ~IdentityCluster.label.startswith("cluster-"),
    )
    labeled_result = await session.execute(labeled_stmt)
    labeled_count = len(labeled_result.scalars().all())

    # Get total cluster count
    total_stmt = select(IdentityCluster).where(IdentityCluster.tenant_id == tenant_id)
    total_result = await session.execute(total_stmt)
    total_cluster_count = len(total_result.scalars().all())

    # Get identity count
    identity_stmt = select(MediaIdentity).where(MediaIdentity.tenant_id == tenant_id)
    identity_result = await session.execute(identity_stmt)
    identity_count = len(identity_result.scalars().all())

    # Compute adaptive threshold
    clustering_settings = ClusteringSettingsModel()
    current_threshold = clustering_settings.compute_adaptive_threshold(labeled_count)

    maturity_point = clustering_settings.adaptive_threshold_maturity_point
    progress = min(100, int((labeled_count / maturity_point) * 100))

    # Determine stage
    if labeled_count == 0:
        stage = "early"
        stage_label = "Early Stage - High Precision Mode"
    elif labeled_count < 10:
        stage = "early"
        stage_label = f"Early Stage - {labeled_count} labeled identities"
    elif labeled_count < maturity_point:
        stage = "developing"
        stage_label = f"Developing - {labeled_count}/{maturity_point} to maturity"
    else:
        stage = "mature"
        stage_label = f"Mature - {labeled_count} labeled identities"

    return TrainingStageResponse(
        stage=stage,
        stage_label=stage_label,
        cluster_count=total_cluster_count,
        identity_count=identity_count,
        current_threshold=round(current_threshold, 3),
        base_threshold=clustering_settings.similarity_threshold,
        strict_threshold=clustering_settings.adaptive_threshold_strict,
        maturity_point=maturity_point,
        progress_percent=progress,
    )


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
    include_debug: bool = Query(
        False,
        description="Include InsightFace debug metrics (pose, age, gender, etc.)",
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

    # Store label, is_auto, similarity_threshold, clustering_algorithm per cluster
    cluster_info: dict[UUID, dict] = {}
    if cluster_ids:
        cluster_stmt = select(IdentityCluster).where(IdentityCluster.id.in_(cluster_ids))
        cluster_result = await session.execute(cluster_stmt)
        for cluster in cluster_result.scalars().all():
            label = cluster.label or None
            is_auto = bool(label and label.startswith("cluster-"))
            cluster_info[cluster.id] = {
                "label": label,
                "is_auto": is_auto,
                "similarity_threshold": cluster.similarity_threshold,
                "clustering_algorithm": cluster.clustering_algorithm,
            }

    identities_by_media: dict[str, list[MediaIdentityDetail]] = {}
    for media_id in resolved_ids:
        media_entries = [identity for identity in identities if identity.media_id == media_id]
        details: list[MediaIdentityDetail] = []
        for identity in media_entries:
            membership = identity.cluster_memberships[0] if identity.cluster_memberships else None
            cluster_id = str(membership.cluster_id) if membership else None
            info = cluster_info.get(membership.cluster_id) if membership else None
            cluster_label = info["label"] if info else None
            is_auto_label = info["is_auto"] if info else False

            # Extract debug metrics from embedding if requested
            debug_metrics: DebugMetrics | None = None
            if include_debug and identity.embedding is not None:
                raw_metrics = decode_debug_metrics(list(identity.embedding))
                if raw_metrics is not None:
                    # Determine clustering method based on similarity
                    # If similarity == 1.0, it's the founding member (new cluster)
                    # Otherwise it was matched to an existing cluster
                    raw_similarity = membership.similarity if membership else None
                    if raw_similarity is not None:
                        if raw_similarity >= 0.9999:
                            # Founding member - not a "match" to anything
                            clustering_method = "new_cluster"
                            match_similarity = None  # Don't show 100% for singletons
                        else:
                            clustering_method = "similarity_match"
                            match_similarity = raw_similarity
                    else:
                        clustering_method = None
                        match_similarity = None

                    debug_metrics = DebugMetrics(
                        pose=raw_metrics["pose"],
                        age=raw_metrics["age"],
                        gender=raw_metrics["gender"],
                        det_score=raw_metrics["det_score"],
                        bbox_area=raw_metrics["bbox_area"],
                        landmark_quality=raw_metrics["landmark_quality"],
                        clustering_method=clustering_method,
                        clustering_algorithm=info["clustering_algorithm"] if info else None,
                        similarity_threshold=info["similarity_threshold"] if info else None,
                        match_similarity=match_similarity,
                    )

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
                    debug_metrics=debug_metrics,
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


@router.post("/clusters/reassign", response_model=ReassignIdentityResponse)
async def reassign_identity(
    request: ReassignIdentityRequest,
    session: AsyncSession = Depends(get_session),
) -> ReassignIdentityResponse:
    """
    Reassign an identity to a different cluster, or remove it from its current cluster.

    This is used when:
    - Assigning a singleton identity to an existing cluster
    - Moving an identity from one cluster to another
    - Removing an identity from a cluster ("wrong person" - creates new singleton cluster)
    """
    from uuid import uuid4

    from sqlalchemy import select

    await set_tenant_context(session, request.tenant_id)

    # Get the identity
    identity = await session.get(MediaIdentity, request.identity_id)
    if not identity or identity.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Identity not found")

    # Find current membership
    from db.models import IdentityMember

    current_stmt = select(IdentityMember).where(
        IdentityMember.identity_id == request.identity_id,
        IdentityMember.tenant_id == request.tenant_id,
    )
    current_result = await session.execute(current_stmt)
    current_member = current_result.scalar_one_or_none()
    previous_cluster_id = current_member.cluster_id if current_member else None

    created_new_cluster = False
    new_cluster_id: UUID | None = None
    new_cluster_label: str | None = None

    if request.target_cluster_id:
        # Assign to existing cluster
        # First, remove old membership if exists to avoid duplicate key
        if current_member and current_member.cluster_id != request.target_cluster_id:
            await session.delete(current_member)
            # Decrement old cluster count
            old_cluster = await session.get(IdentityCluster, current_member.cluster_id)
            if old_cluster:
                old_cluster.identity_count = max(0, old_cluster.identity_count - 1)
            await session.flush()  # Ensure deletion is processed before new assignment

        # Now assign to target cluster
        service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
        await service.assign_identity_to_cluster(request.identity_id, request.target_cluster_id)

        await session.commit()
        message = "Identity assigned to cluster"
    else:
        # "Wrong person" - remove from current cluster and create new singleton cluster
        if current_member:
            old_cluster = await session.get(IdentityCluster, current_member.cluster_id)

            # Delete old membership
            await session.delete(current_member)
            if old_cluster:
                old_cluster.identity_count = max(0, old_cluster.identity_count - 1)

            # Create new singleton cluster for this identity
            new_cluster_id = uuid4()
            new_cluster = IdentityCluster(
                id=new_cluster_id,
                tenant_id=request.tenant_id,
                label=None,  # User can name it later
                representative_identity_id=request.identity_id,
                identity_count=1,
                clustering_algorithm="user_reassign",
                user_confirmed=True,
                confirmation_source="reject",
            )
            session.add(new_cluster)
            await session.flush()

            # Create membership in new cluster
            new_member = IdentityMember(
                id=uuid4(),
                tenant_id=request.tenant_id,
                cluster_id=new_cluster_id,
                identity_id=request.identity_id,
                similarity=1.0,  # Perfect self-similarity
            )
            session.add(new_member)

            await session.commit()
            created_new_cluster = True
            message = "Identity moved to new singleton cluster"
        else:
            message = "Identity was not in any cluster"

    return ReassignIdentityResponse(
        identity_id=str(request.identity_id),
        previous_cluster_id=str(previous_cluster_id) if previous_cluster_id else None,
        target_cluster_id=str(new_cluster_id)
        if new_cluster_id
        else (str(request.target_cluster_id) if request.target_cluster_id else None),
        target_label=new_cluster_label,
        created_new_cluster=created_new_cluster,
        message=message,
    )


class CreateClusterForIdentityRequest(BaseModel):
    tenant_id: UUID
    identity_id: UUID
    label: str = Field(..., min_length=1, max_length=255)
    user_id: int | None = None


class CreateClusterForIdentityResponse(BaseModel):
    cluster_id: str
    label: str
    identity_id: str
    message: str


@router.post("/clusters/create-for-identity", response_model=CreateClusterForIdentityResponse)
async def create_cluster_for_identity(
    request: CreateClusterForIdentityRequest,
    session: AsyncSession = Depends(get_session),
) -> CreateClusterForIdentityResponse:
    """
    Create a new cluster with a label and assign a singleton identity to it.

    This is used when a user gives a name to an unclustered identity.
    """
    from sqlalchemy import select

    from db.models import IdentityMember

    await set_tenant_context(session, request.tenant_id)

    # Get the identity
    identity = await session.get(MediaIdentity, request.identity_id)
    if not identity or identity.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Identity not found")

    # Check if label already exists
    existing_stmt = select(IdentityCluster).where(
        IdentityCluster.tenant_id == request.tenant_id,
        IdentityCluster.label == request.label,
    )
    existing_result = await session.execute(existing_stmt)
    existing_cluster = existing_result.scalar_one_or_none()

    if existing_cluster:
        raise HTTPException(
            status_code=409,
            detail=f"Label '{request.label}' already exists. Use reassign to add identity to existing cluster.",
        )

    # Check if identity is already a member of another cluster and remove it
    current_member_stmt = select(IdentityMember).where(
        IdentityMember.identity_id == request.identity_id,
        IdentityMember.tenant_id == request.tenant_id,
    )
    current_member_result = await session.execute(current_member_stmt)
    current_member = current_member_result.scalar_one_or_none()

    if current_member:
        # Remove from old cluster
        old_cluster = await session.get(IdentityCluster, current_member.cluster_id)
        await session.delete(current_member)
        if old_cluster:
            old_cluster.identity_count = max(0, old_cluster.identity_count - 1)
        logger.info(
            "Removed identity %s from cluster %s before creating new cluster",
            request.identity_id,
            current_member.cluster_id,
        )

    # Create new cluster with the identity
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)

    cluster, _search_entry = await service.factory.create_cluster_with_centroid(
        identities=[identity],
        label=request.label,
    )

    await session.commit()

    logger.info(
        "Created cluster %s with label '%s' for singleton identity %s",
        cluster.id,
        request.label,
        request.identity_id,
    )

    return CreateClusterForIdentityResponse(
        cluster_id=str(cluster.id),
        label=request.label,
        identity_id=str(request.identity_id),
        message="Created new cluster for identity",
    )


@router.post("/clusters/{cluster_id}/split", response_model=SplitClusterResponse)
async def split_cluster(
    cluster_id: UUID,
    request: SplitClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> SplitClusterResponse:
    """
    Split a cluster using hierarchical clustering.

    If n_clusters=0 (default), automatically determines the optimal split
    based on face similarity. If n_clusters>=2, forces exactly that many groups.
    The largest group stays in the original cluster; others become new clusters.
    """
    logger.info(
        "Split cluster request: cluster_id=%s, n_clusters=%d, tenant_id=%s",
        cluster_id,
        request.n_clusters,
        request.tenant_id,
    )
    await set_tenant_context(session, request.tenant_id)
    service = IdentityClusteringService(session=session, tenant_id=request.tenant_id)
    new_ids, counts = await service.split_cluster(cluster_id, n_clusters=request.n_clusters)

    # Build response with both new list format and legacy single-cluster fields
    return SplitClusterResponse(
        new_cluster_ids=[str(id) for id in new_ids],
        moved_counts=counts,
        # Legacy fields: use first new cluster if any
        new_cluster_id=str(new_ids[0]) if new_ids else None,
        moved_count=counts[0] if counts else 0,
    )


# =============================================================================
# Suggestion Endpoints
# =============================================================================


@router.get("/suggestions", response_model=SuggestionsListResponse)
async def list_pending_suggestions(
    tenant_id: UUID,
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> SuggestionsListResponse:
    """Get pending suggestions for user review, ordered by confidence (highest first)."""
    await set_tenant_context(session, tenant_id)

    suggestion_service = SuggestionService(session, tenant_id)
    suggestions = await suggestion_service.get_pending_suggestions(limit=limit, offset=offset)
    total_count = await suggestion_service.count_pending_suggestions()

    # Build response with related entity details
    response_suggestions: list[SuggestionResponse] = []
    for s in suggestions:
        # Load identity and cluster details
        identity = await session.get(MediaIdentity, s.identity_id)
        cluster = await session.get(IdentityCluster, s.suggested_cluster_id)

        if identity is None or cluster is None:
            continue

        # Get cluster representative thumbnail
        cluster_thumbnail = None
        if cluster.representative_identity_id:
            rep_identity = await session.get(MediaIdentity, cluster.representative_identity_id)
            if rep_identity:
                cluster_thumbnail = rep_identity.thumbnail_url

        response_suggestions.append(
            SuggestionResponse(
                id=str(s.id),
                identity_id=str(s.identity_id),
                identity_thumbnail_url=identity.thumbnail_url,
                identity_media_id=identity.media_id,
                suggested_cluster_id=str(s.suggested_cluster_id),
                cluster_label=cluster.label,
                cluster_thumbnail_url=cluster_thumbnail,
                representative_similarity=s.representative_similarity,
                avg_member_similarity=s.avg_member_similarity,
                confidence_score=s.confidence_score,
                created_at=s.created_at.isoformat() if s.created_at else "",
            )
        )

    return SuggestionsListResponse(
        suggestions=response_suggestions,
        total_count=total_count,
    )


@router.post("/suggestions/{suggestion_id}/accept", response_model=SuggestionActionResponse)
async def accept_suggestion(
    suggestion_id: UUID,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> SuggestionActionResponse:
    """Accept a suggestion: assign the identity to the suggested cluster."""
    await set_tenant_context(session, tenant_id)

    suggestion_service = SuggestionService(session, tenant_id)
    suggestion = await suggestion_service.get_suggestion_by_id(suggestion_id)

    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.resolution != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion already resolved: {suggestion.resolution}",
        )

    # Get the identity and assign it to the cluster
    identity = await session.get(MediaIdentity, suggestion.identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")

    # Use clustering service to properly assign with representative management
    service = IdentityClusteringService(session=session, tenant_id=tenant_id)

    # Get identity embedding
    from recognition.domain.embeddings import prepare_embedding

    identity_vector = prepare_embedding(identity.embedding)

    # Assign to cluster
    await service.assigner.assign_to_cluster_by_id(
        identity=identity,
        identity_vector=identity_vector,
        cluster_id=suggestion.suggested_cluster_id,
        similarity=suggestion.representative_similarity,
    )

    # Try to add as representative if high quality
    await service._rep_manager.add_representative(suggestion.suggested_cluster_id, identity)

    # Mark the cluster as user-confirmed and increment confirmation count
    cluster = await session.get(IdentityCluster, suggestion.suggested_cluster_id)
    if cluster:
        cluster.user_confirmed = True
        cluster.confirmation_count += 1
        if not cluster.confirmation_source:
            cluster.confirmation_source = "assignment"

    # Mark suggestion as accepted
    await suggestion_service.accept_suggestion(suggestion_id)

    # Expire any other pending suggestions for this identity
    await suggestion_service.expire_suggestions_for_identity(suggestion.identity_id)

    await session.commit()

    return SuggestionActionResponse(
        suggestion_id=str(suggestion_id),
        resolution="accepted",
        identity_id=str(suggestion.identity_id),
        cluster_id=str(suggestion.suggested_cluster_id),
        message="Identity assigned to cluster",
    )


@router.post("/suggestions/{suggestion_id}/reject", response_model=SuggestionActionResponse)
async def reject_suggestion(
    suggestion_id: UUID,
    tenant_id: UUID = Query(...),
    session: AsyncSession = Depends(get_session),
) -> SuggestionActionResponse:
    """Reject a suggestion: identity stays in its current cluster/singleton."""
    await set_tenant_context(session, tenant_id)

    suggestion_service = SuggestionService(session, tenant_id)
    suggestion = await suggestion_service.get_suggestion_by_id(suggestion_id)

    if suggestion is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")

    if suggestion.resolution != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Suggestion already resolved: {suggestion.resolution}",
        )

    # Mark suggestion as rejected
    await suggestion_service.reject_suggestion(suggestion_id)
    await session.commit()

    return SuggestionActionResponse(
        suggestion_id=str(suggestion_id),
        resolution="rejected",
        identity_id=str(suggestion.identity_id),
        cluster_id=str(suggestion.suggested_cluster_id),
        message="Suggestion rejected - identity remains unchanged",
    )
