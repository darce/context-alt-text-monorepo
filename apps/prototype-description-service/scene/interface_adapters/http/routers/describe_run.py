"""Async bulk describe-run routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from scene.application.describe_run_repository import DescribeRunRepository
from scene.interface_adapters.http.schemas.requests import DescribeRunCreateRequest
from scene.interface_adapters.http.schemas.responses import DescribeRunResponse

router = APIRouter(tags=["describe-runs"])


def _run_response(run) -> DescribeRunResponse:
    return DescribeRunResponse(
        tenant_id=str(run.tenant_id),
        run_id=str(run.id),
        status=run.status,
        phase=run.phase,
        completed=run.completed_items,
        failed=run.failed_items,
        skipped=run.skipped_items,
        total=run.total_items,
        cancel_requested=run.cancel_requested,
        gpu_state=None,
    )


@router.post("/describe/run", response_model=DescribeRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_describe_run(
    request: DescribeRunCreateRequest,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != request.tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch between auth and request envelope")

    tenant_id = uuid.UUID(request.tenant_id)
    await set_tenant_context(session, tenant_id)
    await require_tenant_record(session, tenant_id)
    repo = DescribeRunRepository(session)
    try:
        run_id = await repo.create_run(
            tenant_id=tenant_id,
            media_ids=request.media_ids,
            created_by_user_id=getattr(auth, "user_id", None),
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:  # pragma: no cover - defensive only
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "describe run was not persisted")
    return _run_response(run)
