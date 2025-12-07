"""
Analyze routes: scan media and poll job status.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import ProgrammingError

from db.settings import get_database_settings
from db.tenant_context import clear_tenant_context, ensure_tenant_exists, set_tenant_context
from recognition.application.scan.service import ScanService
from recognition.domain.job import Job, JobType
from recognition.interface_adapters.http.dependencies import (
    get_job_service_dependency,
    get_optional_session,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest, _validate_uuid
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse

router = APIRouter(tags=["analyze"], dependencies=[Depends(require_auth)])

_DB_SETTINGS = get_database_settings()


@router.post("/analyze", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> JobStatusResponse:
    """Scan media for face identities. Returns a job ID for polling."""
    tenant_uuid: uuid.UUID | None = None
    try:
        scan_service = ScanService(session=session)
        media_ids = request.media_ids
        if not media_ids and request.media_items:
            media_ids = [str(item.media_id) for item in request.media_items]
        if not media_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="media_ids are required")
        media_ids = [_validate_uuid(mid) for mid in media_ids]
        if session is not None and hasattr(session, "execute") and _is_postgres_session(session):
            try:
                tenant_uuid = uuid.UUID(str(request.tenant_id))
                # Auto-provision tenant if it doesn't exist (first-use provisioning)
                await ensure_tenant_exists(session, tenant_uuid)
                await set_tenant_context(session, tenant_uuid)
            except Exception as exc:  # pragma: no cover - validation should handle
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid tenant_id") from exc
        if auth and auth.tenant_claim and auth.tenant_claim != str(request.tenant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
        scan_job = await scan_service.analyze_media(request.tenant_id, media_ids)
        progress = JobProgressResponse(completed=scan_job.processed_media or 0, total=scan_job.total_media or 0)
        return JobStatusResponse(
            id=str(scan_job.id),
            type=JobType.ANALYZE.value,
            status=scan_job.status,
            progress=progress,
            started_at=scan_job.started_at or datetime.now(tz=UTC),
            finished_at=scan_job.completed_at,
        )
    except ProgrammingError as exc:
        if _is_insufficient_privilege(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient privileges") from exc
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - stub fallback
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    finally:
        if session is not None and hasattr(session, "execute") and tenant_uuid and _is_postgres_session(session):
            with contextlib.suppress(Exception):
                await clear_tenant_context(session)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    job_service=Depends(get_job_service_dependency),
    session=Depends(get_optional_session),
) -> JobStatusResponse:
    """Poll job status by ID."""
    # First try the in-memory job service (for tests and recently created jobs)
    job = await job_service.get_job_status(job_id)

    # If not found and we have a session, look up from database
    if not job and session is not None:
        from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

        repo = SqlAlchemyJobRepository(session)
        job = await repo.get(job_id)

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return _job_to_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(
    job_id: str,
    auth=Depends(require_write_access),
    job_service=Depends(get_job_service_dependency),
) -> JobStatusResponse:
    """Cancel a long-running job."""
    job = await job_service.cancel_job(job_id)
    return _job_to_response(job)


def _extract_media_id(value: str) -> int:
    """Convert short ID into an integer media identifier."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


def _job_to_response(job: Job) -> JobStatusResponse:
    """Convert domain Job to API response."""
    progress = JobProgressResponse(completed=job.progress_completed, total=job.progress_total)
    started_at = job.started_at or datetime.now(tz=UTC)
    return JobStatusResponse(
        id=job.id,
        type=job.type.value,
        status=job.status.value,
        progress=progress,
        started_at=started_at,
        finished_at=job.finished_at,
    )


def _is_insufficient_privilege(exc: ProgrammingError) -> bool:
    """Detect RLS/permission errors from asyncpg/SQLAlchemy."""
    cause = exc.orig if hasattr(exc, "orig") else None
    if isinstance(cause, asyncpg.InsufficientPrivilegeError):
        return True
    return "InsufficientPrivilege" in str(exc)


def _is_postgres_session(session) -> bool:
    """Return True when session is backed by PostgreSQL."""
    bind = getattr(session, "bind", None)
    dialect = getattr(bind, "dialect", None) if bind else None
    name = getattr(dialect, "name", "")
    return name.startswith("postgres")
