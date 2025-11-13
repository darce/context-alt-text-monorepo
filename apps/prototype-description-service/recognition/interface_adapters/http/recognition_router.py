"""Recognition HTTP routes for analysis and clustering."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import FaceCluster, FaceScanJob, Tenant
from db.session import get_session
from recognition.application.face_clustering_service import FaceClusteringService
from recognition.application.face_scan_service import FaceScanService
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
    total_faces_clustered: int


class ClusterSummaryResponse(BaseModel):
    id: str
    label: str
    face_count: int
    member_ids: List[str]
    representative_face: dict
    sample_faces: List[dict]


def get_embedding_provider() -> FaceEmbeddingProvider:
    return FaceEmbeddingProvider()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(
    request: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
    provider: FaceEmbeddingProvider = Depends(get_embedding_provider),
) -> AnalyzeResponse:
    await _ensure_tenant(session, request.tenant_id, request.site_url)
    job = FaceScanJob(
        tenant_id=request.tenant_id,
        status="pending",
        media_ids=[item.media_id for item in request.media_items],
        total_media=len(request.media_items),
        created_by_user_id=request.user_id,
    )

    session.add(job)
    await session.commit()
    await session.refresh(job)

    service = FaceScanService(session, provider, request.tenant_id)
    await service.scan_batch(job, [item.model_dump() for item in request.media_items], request.user_id)

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
async def get_analysis_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
    job = await session.get(FaceScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": str(job.id),
        "status": job.status,
        "total_media": job.total_media,
        "processed_media": job.processed_media,
        "faces_detected": job.faces_detected,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/cluster", response_model=ClusterResponse)
async def cluster_media(
    request: ClusterRequest,
    session: AsyncSession = Depends(get_session),
) -> ClusterResponse:
    service = FaceClusteringService(
        session=session,
        tenant_id=request.tenant_id,
        similarity_threshold=request.similarity_threshold or 0.6,
    )
    clusters = await service.cluster_faces()
    total_faces = sum(cluster.face_count for cluster in clusters)
    return ClusterResponse(clusters_created=len(clusters), total_faces_clustered=total_faces)


@router.get("/clusters", response_model=List[ClusterSummaryResponse])
async def list_clusters(
    tenant_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> List[ClusterSummaryResponse]:
    stmt = (
        select(FaceCluster)
        .where(FaceCluster.tenant_id == tenant_id)
        .order_by(FaceCluster.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(stmt)
    clusters = result.scalars().all()

    service = FaceClusteringService(session, tenant_id)
    summaries: List[ClusterSummaryResponse] = []

    for cluster in clusters:
        summary = await service.get_cluster_summary(cluster.id)
        summaries.append(ClusterSummaryResponse(**summary))

    return summaries
