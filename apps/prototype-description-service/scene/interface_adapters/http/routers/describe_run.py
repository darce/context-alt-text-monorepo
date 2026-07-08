"""Async bulk describe-run routes."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import TERMINAL_RUN_STATUSES, DescribeRunStatus
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


async def _prepare_repo(*, session, auth, tenant_id: uuid.UUID) -> DescribeRunRepository:
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != str(tenant_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")
    await set_tenant_context(session, tenant_id)
    await require_tenant_record(session, tenant_id)
    return DescribeRunRepository(session)


def _progress_payload(run) -> dict[str, object]:
    return {
        "type": "describe_progress",
        "run_id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "status": str(run.status),
        "completed": run.completed_items + run.failed_items + run.skipped_items,
        "total": run.total_items,
        "phase": str(run.phase),
        "desc": None,
        "gpu_state": None,
    }


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


@router.get("/describe/run/{run_id}", response_model=DescribeRunResponse)
async def get_describe_run(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    tenant_id = uuid.UUID(getattr(auth, "tenant_claim", ""))
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    return _run_response(run)


@router.delete("/describe/run/{run_id}", response_model=DescribeRunResponse)
async def cancel_describe_run(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    tenant_id = uuid.UUID(getattr(auth, "tenant_claim", ""))
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)
    if not await repo.request_cancel(tenant_id=tenant_id, run_id=run_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    await session.commit()
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:  # pragma: no cover - defensive only
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    return _run_response(run)


@router.get("/describe/run/{run_id}/stream")
async def stream_describe_run(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> EventSourceResponse:
    tenant_id = uuid.UUID(getattr(auth, "tenant_claim", ""))
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)

    async def events() -> AsyncIterator[dict[str, str]]:
        run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
        if run is None:
            yield {"event": "error", "data": json.dumps({"error": "describe run not found"})}
            return
        yield {"event": "progress", "data": json.dumps(_progress_payload(run))}
        if DescribeRunStatus(run.status) in TERMINAL_RUN_STATUSES:
            yield {"event": "done", "data": json.dumps(_progress_payload(run))}

    return EventSourceResponse(events())
