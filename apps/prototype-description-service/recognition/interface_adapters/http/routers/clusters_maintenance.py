"""Centroid materialized-view maintenance routes.

Concern router split out of the former ``clusters.py`` god-router (Slice 6):
the centroid-MV health probe and the out-of-band refresh trigger.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from recognition.interface_adapters.http.deps import (
    get_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["clusters"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


@router.get("/clusters/centroid-health")
async def get_centroid_mv_health(
    session=Depends(get_session),
) -> dict:
    """Return centroid MV row count vs identity_clusters for health monitoring.

    Uses RLS bypass so counts reflect all tenants' data, not just the caller's.
    Intended for operator / monitoring use.
    """
    from sqlalchemy import text as sa_text

    from db.tenant_context import enable_rls_bypass as _enable_bypass

    await _enable_bypass(session)
    try:
        mv_count = await session.scalar(sa_text("SELECT COUNT(*) FROM mv_identity_cluster_centroids"))
        cluster_count = await session.scalar(sa_text("SELECT COUNT(*) FROM identity_clusters"))
        healthy = mv_count == cluster_count
        if not healthy:
            _logger.warning(
                "Centroid MV health check divergence: mv_count=%s cluster_count=%s",
                mv_count,
                cluster_count,
            )
        return {
            "mv_count": int(mv_count or 0),
            "cluster_count": int(cluster_count or 0),
            "healthy": healthy,
        }
    except Exception:
        _logger.exception("Centroid health check failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check query failed",
        )


@router.post("/clusters/maintenance/refresh-centroids", status_code=status.HTTP_202_ACCEPTED)
async def trigger_centroid_mv_refresh(
    session=Depends(get_session),
    auth=Depends(require_write_access),
    _demo_quota: object = Depends(enforce_demo_quota),
) -> dict:
    """Trigger an out-of-band refresh of the centroid materialized view.

    This is the dedicated maintenance path for MV refresh, independent of the
    scan worker's polling loop.  Returns ``ok: true`` on success.
    """
    from recognition.domain.repositories import MvRefreshOutcome, require_mv_refresh_outcome
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

    repo = SqlAlchemyClusterRepository(session)
    outcome = require_mv_refresh_outcome(
        await repo.refresh_centroids_view_concurrent(),
        source=f"{type(repo).__name__}.refresh_centroids_view_concurrent",
    )
    reasons = {
        MvRefreshOutcome.REFRESHED: "refresh_completed",
        MvRefreshOutcome.SKIPPED_HEADROOM: "insufficient_disk_headroom",
        MvRefreshOutcome.FAILED: "refresh_failed",
    }
    return {
        "ok": outcome is MvRefreshOutcome.REFRESHED,
        "outcome": outcome.value,
        "reason": reasons[outcome],
    }
