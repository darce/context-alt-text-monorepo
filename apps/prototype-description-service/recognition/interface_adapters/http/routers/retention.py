"""Retention policy, export, purge, and audit routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, ValidationError

from recognition.application.services.export_service import EXPORT_SCHEMA_VERSION, run_export_to_file
from recognition.interface_adapters.http.deps import (
    AuditRepositoryProtocol,
    AuthContext,
    RetentionExportServiceProtocol,
    RetentionPolicyServiceProtocol,
    RetentionPurgeServiceProtocol,
    TenantImportServiceProtocol,
    get_audit_repository,
    get_authenticated_tenant_id,
    get_retention_export_service,
    get_retention_import_service,
    get_retention_policy_service,
    get_retention_purge_service,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.schemas.requests import (
    ApplyPresetRequest,
    ImportRequest,
    PurgeRequest,
    UpdateRetentionPolicyRequest,
)
from recognition.interface_adapters.http.schemas.responses import (
    AuditEventListResponse,
    AuditEventResponse,
    ExportJobStatusResponse,
    ImportResponse,
    PurgeResponse,
    RetentionPolicyResponse,
    StartExportResponse,
)

logger = logging.getLogger(__name__)

# SEC-01 / API-05: the client sits on the untrusted side of this boundary. Server
# faults are logged in full server-side and reported outward as this fixed string;
# driver text, file paths, and internal identifiers never cross.
INTERNAL_ERROR_DETAIL = "internal server error"

router = APIRouter(
    prefix="/retention",
    tags=["retention"],
    dependencies=[Depends(require_auth), Depends(enforce_rate_limit)],
)

RETENTION_MODES = {"retain_all", "dispose_after_ack", "purge_on_demand"}
PURGE_SCOPES = {"disposed", "all"}


class ExportSnapshotResponse(BaseModel):
    """Server-side contract for the export-download envelope.

    Before this model existed the route returned a bare ``dict`` with no
    ``response_model``, so nothing on the server pinned the wire shape and the
    admin client was free to invent envelopes that the exporter never emits
    (FEBT1-LG-01). The snapshot is the exporter's own top-level object -- the
    collections sit at the root, never nested under a ``data`` key -- and this
    model is the single place that says so (rg-015).

    ``extra="allow"`` is deliberate: FastAPI filters a response through its
    ``response_model``, so a closed model would silently drop any key the
    exporter adds before this file is updated. Allowing extras keeps the
    download lossless while still requiring every field the contract promises.
    """

    model_config = ConfigDict(extra="allow")

    tenant_id: str
    retention_mode: str
    exported_at: str
    schema_version: int
    clusters: list[dict[str, Any]]
    media_identities: list[dict[str, Any]]
    identity_suggestions: list[dict[str, Any]]
    name_suggestions: list[dict[str, Any]]
    cluster_merge_suggestions: list[dict[str, Any]]
    scan_jobs: list[dict[str, Any]]


def _actor_from_auth(auth: AuthContext) -> str:
    """Build a stable audit actor string from the authenticated request."""
    if auth.enabled and auth.api_key_id:
        return f"api_key:{auth.api_key_id[:12]}"
    if auth.enabled and auth.is_admin:
        return "admin_api_key"
    return "auth_disabled"


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    return RetentionPolicyResponse.model_validate(payload)


@router.post("/policy/preset", response_model=RetentionPolicyResponse)
async def apply_policy_preset(
    request: ApplyPresetRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: RetentionPolicyServiceProtocol = Depends(get_retention_policy_service),
) -> RetentionPolicyResponse:
    """Apply a named retention preset (e.g. 'gdpr')."""
    try:
        payload = await service.apply_preset(tenant_id, request.preset, _actor_from_auth(auth))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to apply retention preset for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    return RetentionPolicyResponse.model_validate(payload)


@router.post("/export", response_model=StartExportResponse)
async def trigger_export(
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: RetentionExportServiceProtocol = Depends(get_retention_export_service),
) -> StartExportResponse:
    """Start an async tenant data export job."""
    try:
        result = await service.start_async_export(tenant_id, _actor_from_auth(auth))
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to start export job for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc

    job_id = str(result["job_id"])
    background_tasks.add_task(run_export_to_file, job_id, tenant_id, _actor_from_auth(auth))
    return StartExportResponse(job_id=job_id, status="pending")


@router.get("/export/{job_id}/status", response_model=ExportJobStatusResponse)
async def get_export_job_status(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    service: RetentionExportServiceProtocol = Depends(get_retention_export_service),
) -> ExportJobStatusResponse:
    """Return the current status of an async export job."""
    try:
        result = await service.get_export_status(job_id, tenant_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to get export status for job %s", job_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc

    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export job not found")
    return ExportJobStatusResponse(
        job_id=str(result["job_id"]),
        status=str(result["status"]),
        file_size=result.get("file_size"),  # type: ignore[arg-type]
        error_message=result.get("error_message"),  # type: ignore[arg-type]
    )


@router.get("/export/{job_id}/data", response_model=ExportSnapshotResponse)
async def get_export_job_data(
    job_id: str,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    service: RetentionExportServiceProtocol = Depends(get_retention_export_service),
) -> ExportSnapshotResponse:
    """Return the stored export payload when the job is completed."""
    try:
        result = await service.get_export_status(job_id, tenant_id)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to retrieve export data for job %s", job_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc

    if result.get("error") == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="export job not found")
    if result.get("status") != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="export not yet ready")
    data = result.get("data_json")
    if not data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="export data not available")
    try:
        return ExportSnapshotResponse.model_validate(data)
    except ValidationError as exc:
        # rg-015: a stored snapshot that violates the export contract is an
        # explicit server fault, not a shape the download quietly supports.
        logger.error(
            "Stored export snapshot for job %s (tenant %s) violates schema_version %s contract: %s",
            job_id,
            tenant_id,
            EXPORT_SCHEMA_VERSION,
            exc.errors(include_url=False),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="stored export snapshot does not match the export contract",
        ) from exc


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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="confirm=true is required")
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    return _coerce_purge_response(payload, tenant_id, request.scope)


@router.get("/audit", response_model=AuditEventListResponse)
async def list_audit_events(
    tenant_id: str = Depends(get_authenticated_tenant_id),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    repository: AuditRepositoryProtocol = Depends(get_audit_repository),
) -> AuditEventListResponse:
    """List retention audit events, newest first."""
    try:
        items = await repository.list_events(tenant_id, limit=limit, offset=offset, event_type=event_type)
        total = await repository.count_events(tenant_id, event_type=event_type)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to list retention audit events for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc

    return AuditEventListResponse(
        items=[AuditEventResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/import", response_model=ImportResponse)
async def trigger_import(
    request: ImportRequest,
    tenant_id: str = Depends(get_authenticated_tenant_id),
    auth: AuthContext = Depends(require_auth),
    _: AuthContext = Depends(require_write_access),
    service: TenantImportServiceProtocol = Depends(get_retention_import_service),
) -> ImportResponse:
    """Validate an export payload and record an import audit event."""
    try:
        result = await service.validate_and_import(request.data, tenant_id, _actor_from_auth(auth))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - fallback path
        logger.exception("Failed to import tenant data for tenant %s", tenant_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    return ImportResponse.model_validate(result)
