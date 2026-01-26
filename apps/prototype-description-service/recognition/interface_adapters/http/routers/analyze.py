"""
Analyze routes: scan media and poll job status.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from db.tenant_context import clear_tenant_context, ensure_tenant_exists, set_tenant_context
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.tasks.scan import (
    chain_populate_and_process,
    extract_media_id,
    scan_worker_available,
)
from recognition.domain.job import JobType
from recognition.interface_adapters.http.dependencies import (
    get_job_repo,
    get_job_service_dependency,
    get_optional_session,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_shared_insightface_adapter,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.job_utils import job_to_response as _job_to_response
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest, _validate_uuid
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyze"], dependencies=[Depends(require_auth)])


@router.post("/analyze", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_queue=Depends(get_scan_queue_service_optional),
) -> JobStatusResponse:
    """Scan media for face identities. Returns a job ID for polling."""
    tenant_uuid: uuid.UUID | None = None
    try:
        # Extract media IDs and URLs
        media_ids = request.media_ids
        media_sources: list[str] = []  # URLs or IDs to pass to detector
        if request.media_items:
            # Use URLs for detection (InsightFaceFaceDetector will fetch them)
            media_sources = [item.media_url for item in request.media_items]
            media_ids = [str(item.media_id) for item in request.media_items]
        elif media_ids:
            # No URLs available, pass IDs (will work with StubFaceDetector)
            media_sources = list(media_ids)
        if not media_ids:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="media_ids are required")
        media_ids = [_validate_uuid(mid) for mid in media_ids]
        inline_processing = os.environ.get("RECOGNITION_ASYNC_ANALYZE_INLINE", "0") == "1"
        if session is not None and hasattr(session, "execute") and is_postgres(session):
            try:
                tenant_uuid = uuid.UUID(str(request.tenant_id))
                # Auto-provision tenant if it doesn't exist (first-use provisioning)
                await ensure_tenant_exists(session, tenant_uuid)
                await set_tenant_context(session, tenant_uuid)
            except Exception as exc:  # pragma: no cover - validation should handle
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid tenant_id") from exc
            if not inline_processing and not await scan_worker_available(session):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Scan worker unavailable. Start the scan worker or enable inline processing.",
                )
        if auth and auth.tenant_claim and auth.tenant_claim != str(request.tenant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

        if tenant_uuid is None:
            tenant_uuid = uuid.UUID(str(request.tenant_id))

        media_items: list[tuple[int, str]] = []
        if request.media_items:
            media_items = [(int(item.media_id), str(item.media_url)) for item in request.media_items]
        else:
            media_items = [(extract_media_id(mid), str(mid)) for mid in media_sources]

        # NOTE: Tier-based batch limits removed for MVP (see progress-tracking-investigation-2026-01-20.md)

        # Use injected scan_queue if available (for tests), otherwise create from factory
        if scan_queue is None:
            if session is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database unavailable",
                )
            scan_queue = get_scan_queue_service_factory(session)

        job_id = await scan_queue.create_scan_job_record(
            tenant_id=tenant_uuid,
            total=len(media_items),
            created_by_user_id=getattr(auth, "user_id", None),
        )

        # Commit the job BEFORE the background task runs, so the task can find it
        if session is not None:
            await session.commit()

        session_factory: async_sessionmaker[AsyncSession] | None = None
        # Only use request-bound factory for testing (SQLite/in-memory)
        # For Postgres, use the default factory to get fresh connections from the pool
        if session is not None and getattr(session, "bind", None) is not None and not is_postgres(session):
            session_factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)

        background_tasks.add_task(
            chain_populate_and_process,
            tenant_id=str(request.tenant_id),
            job_id=str(job_id),
            media_items=media_items,
            media_ids=media_ids,
            media_sources=media_sources,
            scan_queue=scan_queue if not isinstance(scan_queue, ScanQueueService) else None,
            session_factory=session_factory,
            inline_processing=inline_processing,
            adapter_provider=get_shared_insightface_adapter if inline_processing else None,
        )

        total = len(media_items)
        progress = JobProgressResponse(completed=0, total=total)
        return JobStatusResponse(
            id=str(job_id),
            type=JobType.ANALYZE.value,
            status="pending",
            progress=progress,
            started_at=datetime.now(tz=UTC),
            finished_at=None,
            message=f"Queueing 0/{total} items",
        )
    except ProgrammingError as exc:
        if _is_insufficient_privilege(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient privileges") from exc
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - stub fallback
        logger.exception("Unexpected error in analyze_media: %s", exc)
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    finally:
        if session is not None and hasattr(session, "execute") and tenant_uuid and is_postgres(session):
            with contextlib.suppress(Exception):
                await clear_tenant_context(session)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    tenant_id: str = Query(default=None),
    job_service=Depends(get_job_service_dependency),
    session=Depends(get_optional_session),
) -> JobStatusResponse:
    """Poll job status by ID."""
    # First check in-memory job service (for tests and in-memory mode)
    job = await job_service.get_job_status(job_id)
    if job and hasattr(job, "status") and hasattr(job, "id"):
        if isinstance(job, JobStatusResponse):
            return job
        return _job_to_response(job)

    # Look up from database if we have a session

    if session is not None:
        # Set tenant context for RLS
        if tenant_id and is_postgres(session):
            try:
                tenant_uuid = uuid.UUID(str(tenant_id))
                await ensure_tenant_exists(session, tenant_uuid)
                await set_tenant_context(session, tenant_uuid)
            except Exception:
                pass  # Continue without RLS if context fails

        from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

        repo = SqlAlchemyJobRepository(session)
        domain_job = await repo.get(job_id)
        if domain_job:
            return _job_to_response(domain_job)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    tenant_id: str = Header(alias="X-Tenant-ID"),
    job_repo=Depends(get_job_repo),
) -> EventSourceResponse:
    """Stream real-time job progress via SSE.

    Args:
        job_id: UUID of the job to track.
        tenant_id: Tenant ID for RLS scoping.
        job_repo: Repository for job status lookups.

    Returns:
        SSE response streaming progress events.
    """
    import asyncio
    import time

    async def event_generator():
        last_completed = -1
        last_emit = 0
        last_heartbeat = time.time()

        try:
            while True:
                # Poll DB for latest job state via general job repo
                job = await job_repo.get(job_id)
                if not job:
                    yield {"event": "error", "data": "Job not found"}
                    break

                current_completed = job.progress_completed
                total = job.progress_total
                job_status = job.status.value

                now = time.time()
                # Yield if:
                # 1. Progress changed
                # 2. 500ms passed since last yield AND we have some progress
                # 3. 15s passed (heartbeat)
                should_yield = (
                    current_completed != last_completed
                    or (now - last_emit > 0.5 and current_completed > 0)
                    or (now - last_heartbeat > 15)
                )

                if should_yield:
                    yield {
                        "event": "progress",
                        "data": json.dumps(
                            {
                                "completed": current_completed,
                                "total": total,
                                "status": job_status,
                            }
                        ),
                    }
                    last_completed = current_completed
                    last_emit = now
                    last_heartbeat = now

                if job_status in ("completed", "failed"):
                    yield {
                        "event": "done",
                        "data": json.dumps({"status": job_status}),
                    }
                    break

                await asyncio.sleep(0.1)  # 100ms polling for smooth UI
        except asyncio.CancelledError:
            # Client disconnected
            pass
        except Exception as exc:
            logger.exception("Error in SSE stream for job %s", job_id)
            yield {"event": "error", "data": str(exc)}

    return EventSourceResponse(event_generator())


@router.post("/jobs/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(
    job_id: str,
    tenant_id: str = Query(default=None),
    auth=Depends(require_write_access),
    job_service=Depends(get_job_service_dependency),
    session=Depends(get_optional_session),
    scan_queue=Depends(get_scan_queue_service_optional),
) -> JobStatusResponse:
    """Cancel a long-running job."""
    # Prefer canceling persisted scan jobs when a DB session is available.
    if session is not None and scan_queue is not None:
        if tenant_id and is_postgres(session):
            with contextlib.suppress(Exception):
                tenant_uuid = uuid.UUID(str(tenant_id))
                await ensure_tenant_exists(session, tenant_uuid)
                await set_tenant_context(session, tenant_uuid)
        try:
            job_uuid = uuid.UUID(str(job_id))
            await scan_queue.cancel_scan_job(job_id=job_uuid)
            from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

            repo = SqlAlchemyJobRepository(session)
            domain_job = await repo.get(job_id)
            if domain_job:
                return _job_to_response(domain_job)
        finally:
            if tenant_id and is_postgres(session):
                with contextlib.suppress(Exception):
                    await clear_tenant_context(session)

    job = await job_service.cancel_job(job_id)
    return _job_to_response(job)


# _job_to_response is imported from job_utils for shared use across routers
def _is_insufficient_privilege(exc: ProgrammingError) -> bool:
    """Detect RLS/permission errors from asyncpg/SQLAlchemy."""
    cause = exc.orig if hasattr(exc, "orig") else None
    if isinstance(cause, asyncpg.InsufficientPrivilegeError):
        return True
    return "InsufficientPrivilege" in str(exc)
