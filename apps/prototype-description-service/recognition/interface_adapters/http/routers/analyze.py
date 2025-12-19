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
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.exc import ProgrammingError

from db.settings import get_database_settings
from db.tenant_context import clear_tenant_context, ensure_tenant_exists, set_tenant_context
from recognition.domain.job import Job, JobType
from recognition.interface_adapters.http.dependencies import (
    get_job_service_dependency,
    get_optional_session,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_scan_service_builder,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.schemas.requests import AnalyzeRequest, _validate_uuid
from recognition.interface_adapters.http.schemas.responses import JobProgressResponse, JobStatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analyze"], dependencies=[Depends(require_auth)])

_DB_SETTINGS = get_database_settings()
_DEFAULT_TIER_BATCH_LIMITS: dict[str, int] = {
    "free": 50,
    "pro": 500,
    "business": 2000,
    "enterprise": 10000,
}


def _load_tier_batch_limits() -> dict[str, int]:
    """Load tier batch limits from env or defaults.

    Environment:
        RECOGNITION_TIER_BATCH_LIMITS_JSON
            JSON object mapping tier -> max items per batch.
            Example: {"free":50,"pro":500,"business":2000,"enterprise":10000}
    """
    raw = os.getenv("RECOGNITION_TIER_BATCH_LIMITS_JSON")
    if not raw:
        return dict(_DEFAULT_TIER_BATCH_LIMITS)

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return dict(_DEFAULT_TIER_BATCH_LIMITS)

    if not isinstance(decoded, dict):
        return dict(_DEFAULT_TIER_BATCH_LIMITS)

    limits: dict[str, int] = {}
    for tier, default in _DEFAULT_TIER_BATCH_LIMITS.items():
        value = decoded.get(tier, default)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        limits[tier] = parsed if parsed > 0 else default

    return limits


_TIER_BATCH_LIMITS = _load_tier_batch_limits()


def _max_batch_for_tier(tier: str | None) -> int:
    """Return maximum media items per analyze request for a given tier."""
    normalized = (tier or "free").strip().lower()
    return _TIER_BATCH_LIMITS.get(normalized, _TIER_BATCH_LIMITS["free"])


@router.post("/analyze", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_service_builder=Depends(get_scan_service_builder),
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

        if tenant_uuid is None:
            tenant_uuid = uuid.UUID(str(request.tenant_id))

        media_items: list[tuple[int, str]] = []
        if request.media_items:
            media_items = [(int(item.media_id), str(item.media_url)) for item in request.media_items]
        else:
            media_items = [(_extract_media_id(mid), str(mid)) for mid in media_sources]

        if getattr(auth, "enabled", False) and not getattr(auth, "is_admin", False):
            tier = getattr(auth, "rate_limit_tier", None)
            max_batch = _max_batch_for_tier(tier)
            if len(media_items) > max_batch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(f"Batch size {len(media_items)} exceeds limit {max_batch} for tier '{(tier or 'free')}'."),
                )

        # Use injected scan_queue if available (for tests), otherwise create from factory
        if scan_queue is None:
            if session is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Database unavailable",
                )
            scan_queue = get_scan_queue_service_factory(session)

        enqueue_result = await scan_queue.enqueue_scan_job(
            tenant_id=tenant_uuid,
            media_items=media_items,
        )

        # Commit the job BEFORE the background task runs, so the task can find it
        if session is not None:
            await session.commit()

        if os.environ.get("RECOGNITION_ASYNC_ANALYZE_INLINE", "0") == "1":
            background_tasks.add_task(
                _process_scan_job_inline,
                tenant_id=str(request.tenant_id),
                job_id=str(enqueue_result.job_id),
                media_ids=media_ids,
                media_sources=media_sources,
                scan_service_builder=scan_service_builder,
            )
        progress = JobProgressResponse(completed=0, total=enqueue_result.total)
        return JobStatusResponse(
            id=str(enqueue_result.job_id),
            type=JobType.ANALYZE.value,
            status="pending",
            progress=progress,
            started_at=datetime.now(tz=UTC),
            finished_at=None,
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
        if session is not None and hasattr(session, "execute") and tenant_uuid and _is_postgres_session(session):
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
        if tenant_id and _is_postgres_session(session):
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
        if tenant_id and _is_postgres_session(session):
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
            if tenant_id and _is_postgres_session(session):
                with contextlib.suppress(Exception):
                    await clear_tenant_context(session)

    job = await job_service.cancel_job(job_id)
    return _job_to_response(job)


def _extract_media_id(value: str) -> int:
    """Convert short ID into an integer media identifier."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits:
        return int(digits[-6:])
    return abs(hash(value)) % 1_000_000


async def _process_scan_job_inline(
    *,
    tenant_id: str,
    job_id: str,
    media_ids: list[str] | None,
    media_sources: list[str],
    scan_service_builder,
) -> None:
    """Inline processor used in tests/dev to keep integration tests deterministic.

    Production should run a dedicated worker process instead.

    This function tries to use the injected scan_service_builder first (for tests).
    If that fails (production with stale session), it creates a fresh session.
    """
    try:
        # First, try using the injected builder (works in tests with session overrides)
        service = scan_service_builder(str(tenant_id))
        await service.process_scan_job(
            tenant_id=str(tenant_id),
            job_id=uuid.UUID(str(job_id)),
            media_ids=media_ids or [],
            media_sources=media_sources,
        )
        # If service has a session, commit it
        if hasattr(service, "_session") and service._session is not None:
            await service._session.commit()
    except Exception as e:
        # If the injected builder fails (stale session in production),
        # create a fresh session for the background task
        logger.debug("Injected service builder failed, creating fresh session: %s", e)
        from db.session import async_session_factory
        from db.tenant_context import set_tenant_context

        async with async_session_factory() as session:
            tenant_uuid = uuid.UUID(str(tenant_id))
            await set_tenant_context(session, tenant_uuid)

            from recognition.application.embedding.service import EmbeddingService
            from recognition.config import get_settings as get_recognition_settings

            settings = get_recognition_settings()
            runtime_mode = settings.runtime_mode

            embedder = EmbeddingService()

            if runtime_mode == "test":
                from recognition.application.embedding.detector import StubFaceDetector
                from recognition.application.embedding.generator import StubEmbeddingGenerator

                detector = StubFaceDetector()
                generator = StubEmbeddingGenerator()
            else:
                try:
                    from recognition.application.embedding.detector import InsightFaceFaceDetector
                    from recognition.application.embedding.generator import InsightFaceEmbeddingGenerator
                    from recognition.infrastructure.embeddings import InsightFaceAdapter

                    adapter = InsightFaceAdapter()
                    detector = InsightFaceFaceDetector(adapter)
                    generator = InsightFaceEmbeddingGenerator(adapter)
                except ImportError:
                    from recognition.application.embedding.detector import StubFaceDetector
                    from recognition.application.embedding.generator import StubEmbeddingGenerator

                    logger.warning("InsightFace not installed, using stub detectors.")
                    detector = StubFaceDetector()
                    generator = StubEmbeddingGenerator()

            from recognition.application.scan.service import ScanService

            service = ScanService(
                session=session,
                detector=detector,
                generator=generator,
                embedder=embedder,
            )

            await service.process_scan_job(
                tenant_id=str(tenant_id),
                job_id=uuid.UUID(str(job_id)),
                media_ids=media_ids or [],
                media_sources=media_sources,
            )

            await session.commit()


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
