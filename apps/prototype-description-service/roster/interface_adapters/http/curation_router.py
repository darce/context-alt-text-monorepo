from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.interface_adapters.http.deps.session import get_session
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from roster.application.curation_sync_service import CurationSyncService

router = APIRouter(tags=["roster"])


class CurationSyncRequest(BaseModel):
    """Request payload for one idempotent curation operation."""

    operation_type: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    entity_key: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    expected_base_version: int = Field(default=0, ge=0)
    local_revision: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class CurationSyncBatchRequest(BaseModel):
    """Request payload for one or more idempotent curation operations."""

    operations: list[CurationSyncRequest] = Field(min_length=1)


def _serialize_result(request: CurationSyncRequest, result: Any) -> dict[str, Any]:
    response = {
        "status": result.status,
        "backend_version": result.backend_version,
        "idempotency_key": request.idempotency_key,
    }
    if result.status == "conflict":
        response["conflict_code"] = result.conflict_code
        response["machine_payload"] = result.machine_payload

    return response


@router.post("/curation/sync", summary="Replay one or more curation operations")
async def sync_curation_operation(
    request: CurationSyncRequest | CurationSyncBatchRequest,
    tenant_id: str = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Accept one or more idempotent curation operations.
    """
    service = CurationSyncService(session=session)

    try:
        if isinstance(request, CurationSyncBatchRequest):
            results = await service.apply_batch(tenant_id=tenant_id, operations=request.operations)
        else:
            result = await service.apply(tenant_id=tenant_id, operation=request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if isinstance(request, CurationSyncBatchRequest):
        return {
            "results": [
                _serialize_result(operation, result)
                for operation, result in zip(request.operations, results, strict=True)
            ],
        }

    if result.status == "conflict":
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "conflict_code": result.conflict_code,
                "backend_version": result.backend_version,
                "machine_payload": result.machine_payload,
            },
        )

    return {
        "status": "acknowledged",
        "backend_version": result.backend_version,
        "idempotency_key": request.idempotency_key,
    }
