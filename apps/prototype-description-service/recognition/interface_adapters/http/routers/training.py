"""
Training stage endpoint for frontend readiness checks.

Implements curriculum learning thresholds:
- Early stage (few clusters): Strict thresholds to avoid false positives
- Developing stage: Thresholds gradually relax as clusters are validated
- Mature stage (30+ clusters): Base threshold reached, system is stable
"""

from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, MediaIdentity
from db.tenant_context import ensure_tenant_exists
from recognition.application.settings import ClusteringSettings
from recognition.interface_adapters.http.dependencies import get_session, get_settings, require_auth
from recognition.interface_adapters.http.deps.tenant import get_tenant_id

router = APIRouter(tags=["training"], dependencies=[Depends(require_auth)])


class TrainingStageResponse(BaseModel):
    """Training stage info based on curriculum learning principles."""

    tenant_id: str  # Tenant identifier
    stage: str  # 'early', 'developing', 'mature'
    stage_label: str  # Human-readable label
    cluster_count: int  # Total clusters
    identity_count: int  # Total detected identities
    current_threshold: float  # Active similarity threshold
    base_threshold: float  # Base threshold (at maturity)
    strict_threshold: float  # Strict threshold (early stage)
    maturity_point: int  # Cluster count for maturity
    progress_percent: int  # 0-100 progress to maturity


def _compute_adaptive_threshold(
    cluster_count: int,
    base_threshold: float,
    strict_threshold: float,
    maturity_point: int,
    decay_rate: float = 3.0,
) -> float:
    """Compute adaptive similarity threshold based on cluster maturity.

    Uses exponential decay from strict to base threshold as clusters grow.
    Inspired by CurricularFace: "address easy samples first, hard ones later".

    For clustering, we invert this: be strict early (avoid false positives when
    no ground truth exists), relax as the system learns (centroids become reliable).
    """
    if cluster_count == 0:
        return strict_threshold

    # Exponential decay from strict to base threshold
    rate = decay_rate / maturity_point
    adjustment = (strict_threshold - base_threshold) * math.exp(-rate * cluster_count)
    return base_threshold + adjustment


@router.get("/training-stage", response_model=TrainingStageResponse)
async def get_training_stage(
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
    settings: ClusteringSettings = Depends(get_settings),
) -> TrainingStageResponse:
    """Get current training stage based on curriculum learning.

    The system uses adaptive thresholds inspired by CurricularFace:
    - Early stage (few clusters): Strict thresholds to avoid false positives
    - Developing stage: Thresholds gradually relax as clusters are validated
    - Mature stage (30+ clusters): Base threshold reached, system is stable

    This helps users understand why some matches may not auto-assign.
    """
    tenant_uuid = uuid.UUID(tenant_id)
    await ensure_tenant_exists(session, tenant_uuid)

    # Count labeled clusters (excluding auto-generated labels like "cluster-xxx")
    labeled_stmt = select(func.count(IdentityCluster.id)).where(
        IdentityCluster.tenant_id == tenant_uuid,
        IdentityCluster.label.is_not(None),
        ~IdentityCluster.label.startswith("cluster-"),
    )
    labeled_result = await session.execute(labeled_stmt)
    labeled_count = labeled_result.scalar() or 0

    # Total cluster count
    total_stmt = select(func.count(IdentityCluster.id)).where(IdentityCluster.tenant_id == tenant_uuid)
    total_result = await session.execute(total_stmt)
    total_cluster_count = total_result.scalar() or 0

    # Identity count
    identity_stmt = select(func.count(MediaIdentity.id)).where(MediaIdentity.tenant_id == tenant_uuid)
    identity_result = await session.execute(identity_stmt)
    identity_count = identity_result.scalar() or 0

    # Threshold settings - use a reasonable strict threshold
    base_threshold = settings.similarity_threshold
    strict_threshold = 0.88  # Maximum threshold when no clusters exist
    maturity_point = settings.adaptive_threshold_maturity_point

    # Compute adaptive threshold
    current_threshold = _compute_adaptive_threshold(
        cluster_count=labeled_count,
        base_threshold=base_threshold,
        strict_threshold=strict_threshold,
        maturity_point=maturity_point,
    )

    # Compute progress (0-100%)
    progress = min(100, int((labeled_count / max(maturity_point, 1)) * 100))

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
        tenant_id=tenant_id,
        stage=stage,
        stage_label=stage_label,
        cluster_count=total_cluster_count,
        identity_count=identity_count,
        current_threshold=round(current_threshold, 3),
        base_threshold=base_threshold,
        strict_threshold=strict_threshold,
        maturity_point=maturity_point,
        progress_percent=progress,
    )
