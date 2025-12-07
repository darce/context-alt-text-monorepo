"""
Diagnostics routes for decision inspection.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.interface_adapters.http.dependencies import (
    DecisionStore,
    get_decision_store,
    get_observability_repository,
    require_auth,
)
from recognition.observability.persistence import ObservabilityRepository

router = APIRouter(tags=["diagnostics"], dependencies=[Depends(require_auth)])


@router.get("/diagnostics/decisions", response_model=list[dict[str, Any]])
async def list_decisions(
    tenant_id: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    cluster_id: str | None = Query(default=None),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    store: DecisionStore = Depends(get_decision_store),
    repo: ObservabilityRepository | None = Depends(get_observability_repository),
    auth=Depends(require_auth),
) -> list[dict[str, Any]]:
    """Return recent decisions with optional filters."""
    if auth and auth.enabled and not auth.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin token required")
    if repo:
        return await repo.list_decisions(
            tenant_id=tenant_id,
            outcome=outcome,
            cluster_id=cluster_id,
            start_at=start_at,
            end_at=end_at,
            limit=limit,
            offset=offset,
        )
    return store.list(
        tenant_id=tenant_id,
        outcome=outcome,
        cluster_id=cluster_id,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
