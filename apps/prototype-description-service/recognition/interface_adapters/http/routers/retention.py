"""Retention policy, export, purge, and audit routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from recognition.config import get_settings as get_recognition_settings
from recognition.interface_adapters.http.dependencies import (
    AuditRepositoryProtocol,
    AuthContext,
    RetentionExportServiceProtocol,
    RetentionPolicyServiceProtocol,
    RetentionPurgeServiceProtocol,
    get_audit_repository,
    get_authenticated_tenant_id,
    get_retention_export_service,
    get_retention_policy_service,
    get_retention_purge_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.schemas.requests import PurgeRequest, UpdateRetentionPolicyRequest
from recognition.interface_adapters.http.schemas.responses import (
    AuditEventListResponse,
    AuditEventResponse,
    ExportResponse,
    PurgeResponse,
    RetentionPolicyResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retention", tags=["retention"])

RETENTION_MODES = {"retain_all", "dispose_after_ack", "purge_on_demand"}
PURGE_SCOPES = {"disposed", "all"}


def _actor_from_auth(auth: AuthContext) -> str:
    """Build a stable audit actor string from the authenticated request."""
    if auth.enabled and auth.api_key_id:
        return f"api_key:{auth.api_key_id[:12]}"
    if auth.enabled and auth.is_admin:
        return "admin_api_key"
    return "auth_disabled"


def _coerce_export_response(result: dict[str, Any], tenant_id: str) -> ExportResponse:
    exported_at = result.get("exported_at")
    if exported_at is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="export service returned no exported_at timestamp",
        )
    data = result.get("data")
    if not isinstance(data, dict):
        data = result.get("payload")
    if not isinstance(data, dict):
        data = {
            str(key): value
            for key, value in result.items()
            if key not in {"tenant_id", "exported_at", "schema_version", "counts"}
        }
    counts = result.get("counts")
    if not isinstance(counts, dict):
        counts = {str(key): len(value) for key, value in data.items() if isinstance(value, list)}
    schema_version = result.get("schema_version", 1)
    return ExportResponse(
        tenant_id=str(result.get("tenant_id", tenant_id)),
        exported_at=exported_at,
        schema_version=int(schema_version),
        counts={str(key): int(value) for key, value in counts.items()},
        data=data,
    )


def _coerce_purge_response(result: dict[str, Any], tenant_id: str, scope: str) -> PurgeResponse:
    deleted_counts = result.get("deleted_counts")
    if not isinstance(deleted_counts, dict):
        deleted_counts = result.get("counts")
    if not isinstance(deleted_counts, dict):
        deleted_counts = {}
    last_purge_at = result.get("last_purge_at")
    if last_purge_at is None:
        last_purge_at = result.get("purged_at")
    return PurgeResponse(
        tenant_id=str(result.get("tenant_id", tenant_id)),
        scope=str(result.get("scope", scope)),
        deleted_counts={str(key): int(value) for key, value in deleted_counts.items()},
        last_purge_at=last_purge_at,
    )


@router.get("/policy", response_model=RetentionPolicyResponse)
async def get_retention_policy(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    service: RetentionPolicyServiceProtocol = Depends(get_retention_policy_service),
) -> RetentionPolicyResponse:
    """Read the current tenant retention policy."""
    try:
        payload = await service.get_policy(tenant_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to load retention policy for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return RetentionPolicyResponse.model_validate(payload)


@router.patch("/policy", response_model=RetentionPolicyResponse)
async def update_retention_policy(
    request: UpdateRetentionPolicyRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: RetentionPolicyServiceProtocol = Depends(get_retention_policy_service),
) -> RetentionPolicyResponse:
    """Update the tenant retention mode."""
    if request.retention_mode not in RETENTION_MODES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid retention_mode")
    try:
        payload = await service.update_policy(tenant_id, request.retention_mode, _actor_from_auth(auth))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to update retention policy for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return RetentionPolicyResponse.model_validate(payload)


@router.post("/export", response_model=ExportResponse)
async def trigger_export(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: RetentionExportServiceProtocol = Depends(get_retention_export_service),
) -> ExportResponse:
    """Export tenant machine-derived state inline."""
    settings = get_recognition_settings()
    try:
        exportable_identities = await service.count_exportable_identities(tenant_id)
        if exportable_identities > settings.retention_export_max_identities:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=("tenant export exceeds synchronous response limit; use the async export flow once available"),
            )
        payload = await service.export_tenant_data(tenant_id, _actor_from_auth(auth))
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to export tenant data for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return _coerce_export_response(payload, tenant_id)


@router.post("/purge", response_model=PurgeResponse)
async def trigger_purge(
    request: PurgeRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: RetentionPurgeServiceProtocol = Depends(get_retention_purge_service),
) -> PurgeResponse:
    """Permanently delete retained machine-derived state for a tenant."""
    if not request.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="confirm=true is required")
    if request.scope not in PURGE_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid scope")
    try:
        payload = await service.purge_tenant_data(tenant_id, _actor_from_auth(auth), scope=request.scope)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to purge tenant data for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return _coerce_purge_response(payload, tenant_id, request.scope)


@router.get("/audit", response_model=AuditEventListResponse)
async def list_audit_events(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repository: AuditRepositoryProtocol = Depends(get_audit_repository),
) -> AuditEventListResponse:
    """List retention audit events, newest first."""
    try:
        items = await repository.list_events(tenant_id, limit=limit, offset=offset)
        total = await repository.count_events(tenant_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to list retention audit events for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc

    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
