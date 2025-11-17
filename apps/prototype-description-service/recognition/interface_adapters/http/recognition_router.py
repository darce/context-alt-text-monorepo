"""Recognition HTTP routes for analysis and clustering."""

from __future__ import annotations

from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import IdentityCluster, IdentityMember, IdentityScanJob, MediaIdentity, Tenant
from db.session import get_session
from db.tenant_context import set_tenant_context
from recognition.application.identity_clustering_service import (
    ClusterLabelConflictError,
    ClusterNotFoundError,
    IdentityClusteringService,
)
from recognition.application.identity_scan_service import IdentityScanService
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider

router = APIRouter(tags=["recognition"])


class MediaItem(BaseModel):
    media_id: int
    media_url: HttpUrl


class AnalyzeRequest(BaseModel):
    tenant_id: UUID
    site_url: Optional[HttpUrl] = None
    media_items: List[MediaItem] = Field(..., min_items=1, max_items=100)
    user_id: Optional[int] = None


class AnalyzeResponse(BaseModel):
    job_id: UUID
    status: str
    total_media: int


class ClusterRequest(BaseModel):
    tenant_id: UUID
    similarity_threshold: Optional[float] = 0.6


class ClusterResponse(BaseModel):
    clusters_created: int
    total_identities_clustered: int


class ClusterSummaryResponse(BaseModel):
    id: str
    label: str
    identity_count: int
    member_ids: List[str]
    representative_identity: dict
    sample_identities: List[dict]


class MediaIdentityBBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class MediaIdentityDetail(BaseModel):
    id: str
    media_id: int
    cluster_id: Optional[str]
    cluster_label: Optional[str]
    is_auto_label: bool = False
    bbox: MediaIdentityBBox
    confidence: float
    similarity: Optional[float]
    detected_at: Optional[str]
    thumbnail_url: Optional[str] = None


class MediaIdentitiesResponse(BaseModel):
    identities_by_media: Dict[str, List[MediaIdentityDetail]]


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
    await session.commit()
    await session.refresh(job)

    service = IdentityScanService(session, provider, request.tenant_id)
    await service.scan_identities(job, [item.model_dump() for item in request.media_items], request.user_id)

    await session.refresh(job)
    return AnalyzeResponse(job_id=job.id, status=job.status, total_media=job.total_media)


async def _ensure_tenant(session: AsyncSession, tenant_id: UUID, site_url: Optional[HttpUrl]) -> None:
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
    clusters = await service.cluster_identities()
    total_identities = sum(cluster.identity_count for cluster in clusters)
    return ClusterResponse(clusters_created=len(clusters), total_identities_clustered=total_identities)


@router.get("/clusters", response_model=List[ClusterSummaryResponse])
async def list_clusters(
    tenant_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> List[ClusterSummaryResponse]:
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
    summaries: List[ClusterSummaryResponse] = []

    for cluster in clusters:
        summary = await service.get_cluster_summary(cluster.id)
        summaries.append(ClusterSummaryResponse(**summary))

    return summaries


@router.get("/media/identities", response_model=MediaIdentitiesResponse)
async def get_media_identities(
    tenant_id: UUID,
    media_ids: List[int] = Query(..., min_length=1, max_length=100),
    session: AsyncSession = Depends(get_session),
) -> MediaIdentitiesResponse:
    await set_tenant_context(session, tenant_id)
    stmt = (
        select(MediaIdentity)
        .where(
            MediaIdentity.tenant_id == tenant_id,
            MediaIdentity.is_deleted.is_(False),
            MediaIdentity.media_id.in_(media_ids),
        )
        .options(selectinload(MediaIdentity.cluster_memberships))
    )
    result = await session.execute(stmt)
    identities = result.scalars().all()

    cluster_ids = {
        membership.cluster_id
        for identity in identities
        for membership in identity.cluster_memberships
    }

    cluster_labels: Dict[UUID, tuple[Optional[str], bool]] = {}
    if cluster_ids:
        cluster_stmt = select(IdentityCluster).where(IdentityCluster.id.in_(cluster_ids))
        cluster_result = await session.execute(cluster_stmt)
        for cluster in cluster_result.scalars().all():
            label = cluster.label or None
            is_auto = bool(label and label.startswith("cluster-"))
            cluster_labels[cluster.id] = (label, is_auto)

    identities_by_media: Dict[str, List[MediaIdentityDetail]] = {}
    for media_id in media_ids:
        media_entries = [
            identity
            for identity in identities
            if identity.media_id == media_id
        ]
        details: List[MediaIdentityDetail] = []
        for identity in media_entries:
            membership = identity.cluster_memberships[0] if identity.cluster_memberships else None
            cluster_id = str(membership.cluster_id) if membership else None
            label_info = cluster_labels.get(membership.cluster_id) if membership else (None, False)
            details.append(
                MediaIdentityDetail(
                    id=str(identity.id),
                    media_id=identity.media_id,
                    cluster_id=cluster_id,
                    cluster_label=label_info[0],
                    is_auto_label=label_info[1],
                    bbox=MediaIdentityBBox(
                        x=identity.bbox_x,
                        y=identity.bbox_y,
                        width=identity.bbox_width,
                        height=identity.bbox_height,
                    ),
                    confidence=identity.confidence,
                    similarity=membership.similarity if membership else None,
                    detected_at=identity.created_at.isoformat() if identity.created_at else None,
                    thumbnail_url=getattr(identity, "thumbnail_url", None),
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
