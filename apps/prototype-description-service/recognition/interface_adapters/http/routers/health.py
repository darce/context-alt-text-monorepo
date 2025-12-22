"""Health and monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="Recognition service health")
async def health_check() -> dict[str, str]:
    """Health check with database connectivity and pool stats."""
    raise NotImplementedError("TODO: implement health_check")


@router.get("/pool", summary="Connection pool statistics")
async def pool_stats() -> dict[str, int | float]:
    """Get connection pool statistics."""
    raise NotImplementedError("TODO: implement pool_stats")
