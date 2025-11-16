"""Recognition HTTP routes for analysis and clustering."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityScanJob, Tenant
from db.session import get_session
from recognition.application.identity_clustering_service import IdentityClusteringService
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


def get_embedding_provider() -> FaceEmbeddingProvider:
    return FaceEmbeddingProvider()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_media(
    request: AnalyzeRequest,
    session: AsyncSession = Depends(get_session),
    provider: FaceEmbeddingProvider = Depends(get_embedding_provider),
) -> AnalyzeResponse:
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
async def get_analysis_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> dict:
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
