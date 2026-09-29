from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from db.tenant_context import set_tenant_context
from recognition.interface_adapters.http.deps import get_persisted_cluster_job_service
from recognition.interface_adapters.http.deps.session import get_session
from recognition.interface_adapters.http.deps.tenant import get_authenticated_tenant_id
from recognition.interface_adapters.http.deps.usage_admission import (
    admit_usage,
    build_usage_operation_id,
    build_usage_request_fingerprint,
    get_required_usage_admission_service,
)
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
    tenant_id: str = Depends(get_authenticated_tenant_id),
    session: AsyncSession = Depends(get_session),
    job_service=Depends(get_persisted_cluster_job_service),
    usage_admission_service=Depends(get_required_usage_admission_service),
) -> Any:
    """
    Accept one or more idempotent curation operations.
    """
    tenant_uuid = UUID(tenant_id)
    await set_tenant_context(session, tenant_uuid)
    operations = request.operations if isinstance(request, CurationSyncBatchRequest) else [request]
    operation_id = build_usage_operation_id(
        tenant_uuid,
        route="roster_curation_sync",
        idempotency_keys=[operation.idempotency_key for operation in operations],
    )
    request_fingerprint = build_usage_request_fingerprint(
        tenant_uuid,
        route="roster_curation_sync",
        payload=request.model_dump(mode="json"),
    )
    service = CurationSyncService(session=session, job_service=job_service)

    async with admit_usage(
        usage_admission_service,
        tenant_id=tenant_uuid,
        idempotency_key=operation_id,
        job_id=None,
        cost_units=len(operations),
        operation_id=operation_id,
        request_fingerprint=request_fingerprint,
    ) as ticket:
        try:
            if isinstance(request, CurationSyncBatchRequest):
                results = await service.apply_batch(tenant_id=tenant_id, operations=request.operations)
            else:
                result = await service.apply(tenant_id=tenant_id, operation=request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if isinstance(request, CurationSyncBatchRequest):
            response: Any = {
                "results": [
                    _serialize_result(operation, result)
                    for operation, result in zip(request.operations, results, strict=True)
                ],
            }
        elif result.status == "conflict":
            response = JSONResponse(
                status_code=409,
                content={
                    "status": "conflict",
                    "conflict_code": result.conflict_code,
                    "backend_version": result.backend_version,
                    "machine_payload": result.machine_payload,
                },
            )
        else:
            response = {
                "status": "acknowledged",
                "backend_version": result.backend_version,
                "idempotency_key": request.idempotency_key,
            }

    if ticket is not None:
        await usage_admission_service.commit(ticket)

    return response
