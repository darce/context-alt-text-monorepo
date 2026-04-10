"""Health and monitoring endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_pool_stats
from recognition.interface_adapters.http.dependencies import get_optional_session, require_auth
from recognition.interface_adapters.http.deps.circuit_breaker import (
    BreakerState,
    get_or_create_session_dependency_circuit_breaker,
)
from recognition.interface_adapters.http.schemas.responses import ConnectionPoolStats, HealthCheckResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthCheckResponse, summary="Recognition service health")
async def health_check(
    request: Request,
    session: AsyncSession | None = Depends(get_optional_session),
) -> HealthCheckResponse:
    """Health check with database connectivity."""
    breaker = get_or_create_session_dependency_circuit_breaker(request.app)
    breaker_snapshot = breaker.snapshot()
    db_status = "connected" if session is not None else "disconnected"
    status = "healthy" if db_status == "connected" else "degraded"
    database_detail = None
    if session is None:
        database_detail = "circuit_breaker_open" if breaker_snapshot.state is BreakerState.OPEN else "connection_unavailable"
    return HealthCheckResponse(
        status=status,
        database=db_status,
        database_detail=database_detail,
        breaker_state=breaker_snapshot.state,
        pool_stats=None,
        timestamp=datetime.now(tz=UTC).isoformat(),
    )


@router.get("/pool", response_model=ConnectionPoolStats, summary="Connection pool statistics")
async def pool_stats(
    _auth=Depends(require_auth),
) -> ConnectionPoolStats:
    """Get connection pool statistics."""
    stats = get_pool_stats()
    return ConnectionPoolStats(**stats)
