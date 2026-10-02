"""
Analyze routes: scan media and poll job status.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time as _time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sse_starlette.sse import EventSourceResponse

from db.tenant_context import require_tenant_record
from recognition.application.scan.capability import require_scan_dispatch_ready
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.tasks.scan import (
    chain_populate_and_process,
    extract_media_id,
    process_scan_job_inline,
)
from recognition.domain.job import TERMINAL_JOB_STATUSES, Job, JobPhase, JobStatus, JobType
from recognition.domain.portal_contracts import UsageTicket
from recognition.domain.repositories import JobRepository
from recognition.interface_adapters.http.deps import (
    RetentionPolicyServiceProtocol,
    get_job_repo,
    get_job_service_dependency,
    get_optional_session,
    get_retention_policy_service,
    get_scan_queue_repo,
    get_scan_queue_service_factory,
    get_scan_queue_service_optional,
    get_shared_insightface_adapter,
    require_auth,
    require_write_access,
)
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant_common import normalize_tenant_id
from recognition.interface_adapters.http.deps.usage_admission import (
    _is_usage_service,
    admit_usage,
    get_usage_admission_service,
)
from recognition.interface_adapters.http.job_utils import job_to_response as _job_to_response
from recognition.interface_adapters.http.middleware.correlation import get_correlation_id
from recognition.interface_adapters.http.schemas.requests import (
    AcknowledgeProjectionRequest,
    AnalyzeRequest,
    _validate_uuid,
)
from recognition.interface_adapters.http.schemas.responses import (
    ClusterDeltaResponse,
    JobProgressResponse,
    JobStatusResponse,
)
from recognition.shared.db.dialect import is_postgres

logger = logging.getLogger(__name__)

# A process that dies after claiming inline work leaves the job RUNNING. A
# replay may reclaim it after this bounded lease, using started_at as the lease
# timestamp without adding a schema column.
INLINE_PROCESSING_LEASE = timedelta(minutes=30)
INLINE_PROCESSING_HEARTBEAT_INTERVAL = timedelta(minutes=5)

# SEC-01 / API-05: fixed client-facing text for server faults. The exception body
# stays server-side in the log record; 501 would tell the caller the endpoint does
# not exist and change its retry/caching decision (API-08).
INTERNAL_ERROR_DETAIL = "internal server error"
_OPERATION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_IDENTITY_ENVELOPE_KEYS = frozenset({"tenant_id", "media_ids", "media_items", "operation_id", "idempotency_key"})

router = APIRouter(tags=["analyze"], dependencies=[Depends(require_auth), Depends(enforce_rate_limit)])


def _validate_operation_id(raw: str) -> str:
    stripped = raw.strip()
    if not _OPERATION_ID_RE.fullmatch(stripped):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="operation_id must be 1-128 characters in [A-Za-z0-9._:-]",
        )
    return stripped


def resolve_analyze_operation_id(
    *,
    header_value: str | None,
    envelope: Mapping[str, object] | None = None,
    required: bool = False,
) -> str:
    """Prefer Idempotency-Key, then envelope operation_id; never hash media sources."""
    candidates: list[str] = []
    if isinstance(header_value, str) and header_value.strip():
        candidates.append(_validate_operation_id(header_value))
    if envelope is not None:
        for key in ("operation_id", "idempotency_key"):
            value = envelope.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(_validate_operation_id(value))
                break
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    if len(unique) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key and envelope operation_id must match",
        )
    if unique:
        return unique[0]
    if required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "https://context-alt-text.dev/problems/idempotency-key-required",
                "title": "Idempotency-Key required",
                "status": status.HTTP_400_BAD_REQUEST,
                "detail": "Metered analyze requests require Idempotency-Key or an envelope operation_id/idempotency_key",
                "code": "idempotency_key_required",
            },
        )
    return str(uuid.uuid4())


def fingerprint_options_from_envelope(envelope: Mapping[str, object] | None) -> dict[str, object]:
    if not envelope:
        return {}
    return {key: value for key, value in envelope.items() if key not in _IDENTITY_ENVELOPE_KEYS}


def build_analyze_request_fingerprint(
    *,
    tenant_id: object,
    route: str,
    media_ids: Sequence[object],
    media_sources: Sequence[object],
    options: Mapping[str, object] | None = None,
) -> str:
    """Canonical content/options digest. Distinct from the logical operation id."""
    if len(media_ids) != len(media_sources):
        raise ValueError("media_ids and media_sources must have the same length")
    canonical_items = sorted(
        (str(media_id), str(media_source)) for media_id, media_source in zip(media_ids, media_sources, strict=True)
    )
    payload = {
        "media_ids": [media_id for media_id, _source in canonical_items],
        "media_sources": [source for _media_id, source in canonical_items],
        "options": dict(options or {}),
        "route": route,
        "tenant_id": str(tenant_id),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def is_usage_replay(ticket: UsageTicket | None, generated_job_id: uuid.UUID) -> bool:
    if ticket is None or not ticket.job_id:
        return False
    return str(ticket.job_id) != str(generated_job_id)


def bound_job_uuid(ticket: UsageTicket | None, generated_job_id: uuid.UUID) -> uuid.UUID:
    if ticket is None or not ticket.job_id:
        return generated_job_id
    try:
        return uuid.UUID(str(ticket.job_id))
    except ValueError:
        return generated_job_id


def queued_analyze_job_response(job_id: object, total: int) -> JobStatusResponse:
    progress = JobProgressResponse(
        completed=0,
        total=total,
        phase=JobPhase.QUEUED,
        images_processed=0,
        faces_found=0,
    )
    return JobStatusResponse(
        id=str(job_id),
        type=JobType.ANALYZE.value,
        status=JobStatus.PENDING,
        progress=progress,
        started_at=datetime.now(tz=UTC),
        finished_at=None,
        message=f"Queueing 0/{total} items",
    )


async def json_request_envelope(http_request: Request) -> dict[str, object]:
    try:
        payload = await http_request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _canonical_tenant_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return normalize_tenant_id(text)
    except HTTPException:
        return text


def _poll_tenant_authority(auth, *, x_tenant_id: str | None) -> str | None:
    """Return the tenant allowed to read a job, or None when auth is disabled.

    Tenant-scoped API keys always win. Query ``tenant_id`` is never authority.
    Admin keys may use ``X-Tenant-ID``. Enabled auth without a tenant fails closed.
    """
    if auth is None or not getattr(auth, "enabled", False):
        return None
    tenant_claim = getattr(auth, "tenant_claim", None)
    if tenant_claim:
        canonical = _canonical_tenant_id(tenant_claim)
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="tenant-scoped API key or admin override required",
            )
        return canonical
    if getattr(auth, "is_admin", False):
        if not x_tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="X-Tenant-ID header required")
        return normalize_tenant_id(x_tenant_id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="tenant-scoped API key or admin override required",
    )


def _job_is_visible(*, job: object, caller_tenant: str | None) -> bool:
    if caller_tenant is None:
        return True
    job_tenant = _canonical_tenant_id(getattr(job, "tenant_id", None))
    if job_tenant is None:
        return False
    return job_tenant == caller_tenant


def _followup_from_in_memory_jobs(repo: object, scan_job_id: str) -> Job | None:
    jobs_holder = getattr(repo, "repository", repo)
    jobs = getattr(jobs_holder, "jobs", None)
    if not isinstance(jobs, dict):
        return None
    matched: Job | None = None
    for job in jobs.values():
        if not isinstance(job, Job) or job.type is not JobType.CLUSTERING:
            continue
        payload = job.payload or {}
        if payload.get("scan_job_id") == scan_job_id:
            matched = job
    return matched


async def _load_followup_clustering_job(repo: JobRepository, scan_job_id: str) -> Job | None:
    getter = getattr(repo, "get_followup_clustering_job", None)
    if callable(getter):
        try:
            return await getter(scan_job_id)
        except AttributeError:
            pass
    return _followup_from_in_memory_jobs(repo, scan_job_id)


async def _resolve_pipeline_job(
    *,
    requested_job_id: str,
    domain_job: Job | None,
    repo: JobRepository,
    caller_tenant: str | None = None,
) -> Job | None:
    """Treat auto-chained clustering work as part of the original analyze pipeline."""
    if domain_job is None or domain_job.type is not JobType.ANALYZE or domain_job.status is not JobStatus.COMPLETED:
        return domain_job
    followup_job = await _load_followup_clustering_job(repo, requested_job_id)
    if followup_job is None:
        return domain_job
    if not _job_is_visible(job=followup_job, caller_tenant=caller_tenant):
        return domain_job
    return followup_job


async def _job_to_pipeline_response(
    *,
    requested_job_id: str,
    domain_job: Job | None,
    repo: JobRepository,
    scan_repo,
    cluster_repo=None,
    caller_tenant: str | None = None,
):
    resolved_job = await _resolve_pipeline_job(
        requested_job_id=requested_job_id,
        domain_job=domain_job,
        repo=repo,
        caller_tenant=caller_tenant,
    )
    if resolved_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    response = await _job_to_response(resolved_job, scan_repo=scan_repo)
    if resolved_job is not domain_job:
        response.id = requested_job_id
    if (
        resolved_job is not None
        and resolved_job.type is JobType.CLUSTERING
        and resolved_job.status is JobStatus.COMPLETED
        and resolved_job.tenant_id != ""
    ):
        projection = await repo.get_projection_status(resolved_job.id, resolved_job.tenant_id)
        if projection is not None:
            if response.progress is None:
                response.progress = JobProgressResponse(
                    completed=resolved_job.progress_completed,
                    total=resolved_job.progress_total,
                )
            if projection.snapshot_version == 0:
                # No clusters produced; nothing to project. Skip the sync/ack cycle.
                response.progress.phase = JobPhase.COMPLETE
            elif projection.acknowledged_at is None:
                response.progress.phase = JobPhase.AWAITING_PROJECTION
            else:
                response.progress.phase = JobPhase.COMPLETE
            response.snapshot_version = projection.snapshot_version
            response.source_job_id = projection.source_job_id
            response.projection_acknowledged_at = projection.acknowledged_at
            if projection.snapshot_version > 0 and projection.acknowledged_at is None:
                response.projection_payload = await _build_projection_payload(
                    tenant_id=resolved_job.tenant_id,
                    snapshot_version=projection.snapshot_version,
                    cluster_repo=cluster_repo,
                )
    return response


async def _build_projection_payload(
    *,
    tenant_id: str,
    snapshot_version: int,
    cluster_repo,
) -> ClusterDeltaResponse | None:
    if cluster_repo is None or snapshot_version <= 0:
        return None

    from recognition.interface_adapters.http.routers.clusters_snapshot import (
        _build_cluster_responses,
        _build_member_responses,
    )

    clusters, members_with_identities, payload_version = await cluster_repo.get_delta(tenant_id, since_version=0)
    if payload_version != snapshot_version:
        return None

    return ClusterDeltaResponse(
        tenant_id=tenant_id,
        snapshot_version=payload_version,
        generated_at=datetime.now(tz=UTC),
        clusters=_build_cluster_responses(clusters),
        members=_build_member_responses(members_with_identities),
    )


def _media_item_source(item) -> str:
    """Return the per-item analyze source, preferring blob_uri (multipart
    transport, E15-11) over media_url (legacy URL transport).

    The MediaItem schema validator guarantees exactly one of the two fields
    is set, so the fall-through ValueError is defensive only.
    """
    if item.blob_uri is not None:
        return item.blob_uri
    if item.media_url is not None:
        return item.media_url
    raise ValueError(f"MediaItem(media_id={item.media_id}) has neither blob_uri nor media_url")


def _prepare_media_items(request: AnalyzeRequest) -> tuple[list[str], list[str], list[tuple[int, str]]]:
    """Validate and normalize analyze request media inputs."""
    media_ids = request.media_ids
    media_sources: list[str] = []
    if request.media_items:
        media_sources = [_media_item_source(item) for item in request.media_items]
        media_ids = [str(item.media_id) for item in request.media_items]
    elif media_ids:
        media_sources = list(media_ids)

    if not media_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="media_ids are required")

    validated_media_ids = [_validate_uuid(mid) for mid in media_ids]
    if request.media_items:
        media_items = [(int(item.media_id), _media_item_source(item)) for item in request.media_items]
    else:
        media_items = [(extract_media_id(mid), str(mid)) for mid in media_sources]

    return validated_media_ids, media_sources, media_items


async def _prepare_tenant_context(
    *,
    request: AnalyzeRequest,
    auth,
    session: AsyncSession | None,
    inline_processing: bool,
) -> uuid.UUID:
    """Validate tenant/auth state and prepare DB tenant context when available."""
    if auth and auth.tenant_claim and auth.tenant_claim != str(request.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    try:
        tenant_uuid = uuid.UUID(str(request.tenant_id))
    except Exception as exc:  # pragma: no cover - request validation should catch this
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid tenant_id") from exc

    if session is not None and hasattr(session, "execute") and is_postgres(session):
        await require_tenant_record(session, tenant_uuid)
        await require_scan_dispatch_ready(session, inline_processing=inline_processing)

    return tenant_uuid


async def _renew_inline_processing_lease(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    owner_token: str,
) -> bool | None:
    """Renew an inline claim, returning None once its job reaches a terminal state."""
    from db.models import IdentityScanJob
    from db.tenant_context import set_tenant_context

    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        job = await session.scalar(
            select(IdentityScanJob)
            .where(IdentityScanJob.id == job_id, IdentityScanJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if job is None:
            return False
        if job.status in TERMINAL_JOB_STATUSES:
            return None
        if job.status != JobStatus.RUNNING or job.error_message != owner_token:
            return False
        job.started_at = datetime.now(tz=UTC)
        await session.commit()
        return True


async def _clear_inline_processing_owner(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    owner_token: str,
) -> None:
    """Clear lease metadata only if this processor still owns the job."""
    from db.models import IdentityScanJob
    from db.tenant_context import set_tenant_context

    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        job = await session.scalar(
            select(IdentityScanJob)
            .where(IdentityScanJob.id == job_id, IdentityScanJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if job is not None and job.error_message == owner_token:
            job.error_message = None
            await session.commit()


async def _process_inline_with_lease(*, kwargs: dict, owner_token: str) -> None:
    """Run inline work only while this dispatch still holds its fenced lease."""
    session_factory = kwargs["session_factory"]
    tenant_id = uuid.UUID(kwargs["tenant_id"])
    job_id = uuid.UUID(kwargs["job_id"])

    async def run_processor() -> None:
        from recognition.application.scan.service import inline_processing_owner

        token = inline_processing_owner.set((job_id, owner_token))
        try:
            await process_scan_job_inline(
                tenant_id=kwargs["tenant_id"],
                job_id=kwargs["job_id"],
                media_ids=kwargs["media_ids"],
                media_sources=kwargs["media_sources"],
                session_factory=session_factory,
                adapter_provider=kwargs["adapter_provider"],
            )
        finally:
            inline_processing_owner.reset(token)

    processor = asyncio.create_task(run_processor())
    try:
        while not processor.done():
            done, _ = await asyncio.wait(
                {processor},
                timeout=INLINE_PROCESSING_HEARTBEAT_INTERVAL.total_seconds(),
            )
            if done:
                break
            lease_state = await _renew_inline_processing_lease(
                session_factory=session_factory,
                tenant_id=tenant_id,
                job_id=job_id,
                owner_token=owner_token,
            )
            if lease_state is None:
                processor.cancel()
                await asyncio.gather(processor, return_exceptions=True)
                return
            if not lease_state:
                processor.cancel()
                await asyncio.gather(processor, return_exceptions=True)
                return
        await processor
    except BaseException:
        if not processor.done():
            processor.cancel()
            await asyncio.gather(processor, return_exceptions=True)
        raise
    finally:
        try:
            await _clear_inline_processing_owner(
                session_factory=session_factory,
                tenant_id=tenant_id,
                job_id=job_id,
                owner_token=owner_token,
            )
        except Exception:
            # The heartbeat remains bounded by its expiry if cleanup loses the DB.
            logger.exception("failed to clear inline processor owner for job_id=%s", job_id)


async def _dispatch_persisted_analysis(**kwargs) -> None:
    """Serialize dispatch, populate the queue, and claim any inline run.

    Both the original request and replays use this guard: a retry can arrive
    before the original background task starts. Queue population and the inline
    claim commit together, so a replay cannot repeat a partial batch or start a
    second inline processor. A stale inline claim can be recovered after its
    lease expires.
    """
    from db.models import IdentityScanJob, IdentityScanJobItem
    from db.tenant_context import set_tenant_context
    from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

    session_factory = kwargs.get("session_factory")
    if session_factory is None:
        from db.session import async_session_factory

        session_factory = async_session_factory
    job_id = uuid.UUID(kwargs["job_id"])
    tenant_id = uuid.UUID(kwargs["tenant_id"])
    should_process_inline = False
    inline_owner_token: str | None = None
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        job = await session.scalar(
            select(IdentityScanJob)
            .where(IdentityScanJob.id == job_id, IdentityScanJob.tenant_id == tenant_id)
            .with_for_update()
        )
        if job is None:
            return
        inline_processing = bool(kwargs["inline_processing"])
        now = datetime.now(tz=UTC)
        is_pending = job.status == JobStatus.PENDING
        is_stale_inline_claim = (
            inline_processing
            and job.status == JobStatus.RUNNING
            and job.started_at is not None
            and job.started_at <= now - INLINE_PROCESSING_LEASE
        )
        if not is_pending and not is_stale_inline_claim:
            return

        existing_item = await session.scalar(
            select(IdentityScanJobItem.id).where(IdentityScanJobItem.job_id == job_id).limit(1)
        )
        if existing_item is None and not is_pending:
            return
        if existing_item is None:
            queue = ScanQueueService(SqlAlchemyScanQueueRepository(session))
            await queue.populate_scan_job_items(
                job_id=job_id,
                tenant_id=tenant_id,
                media_items=kwargs["media_items"],
                correlation_id=kwargs.get("correlation_id"),
            )
        if inline_processing:
            # The row lock serializes contenders. Commit the transition before
            # releasing it so only this dispatcher can enter the processor.
            # error_message carries an opaque fencing token while RUNNING; the
            # processor replaces it if it fails, and the owner clears it on exit.
            job.status = JobStatus.RUNNING
            job.started_at = now
            inline_owner_token = f"inline:{uuid.uuid4()}"
            job.error_message = inline_owner_token
            should_process_inline = True
        await session.commit()
    if should_process_inline and inline_owner_token is not None:
        await _process_inline_with_lease(kwargs={**kwargs, "session_factory": session_factory}, owner_token=inline_owner_token)


async def _schedule_analysis(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession | None,
    scan_queue,
    tenant_uuid: uuid.UUID,
    media_items: list[tuple[int, str]],
    media_ids: list[str],
    media_sources: list[str],
    inline_processing: bool,
    auth,
    job_id: uuid.UUID | None = None,
    existing_job: bool = False,
) -> JobStatusResponse:
    """Create the scan job, schedule background work, and build the initial response."""
    if scan_queue is None:
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable",
            )
        scan_queue = get_scan_queue_service_factory(session)

    create_kwargs: dict[str, object] = {
        "tenant_id": tenant_uuid,
        "total": len(media_items),
        "created_by_user_id": getattr(auth, "user_id", None),
    }
    if job_id is not None:
        create_kwargs["job_id"] = job_id
    persisted_job_id = job_id if existing_job else await scan_queue.create_scan_job_record(**create_kwargs)

    if session is not None:
        await session.commit()

    session_factory: async_sessionmaker[AsyncSession] | None = None
    if session is not None and getattr(session, "bind", None) is not None and not is_postgres(session):
        session_factory = async_sessionmaker(bind=session.bind, expire_on_commit=False)

    try:
        correlation_id = get_correlation_id()
        background_tasks.add_task(
            _dispatch_persisted_analysis if isinstance(scan_queue, ScanQueueService) else chain_populate_and_process,
            tenant_id=str(tenant_uuid),
            job_id=str(persisted_job_id),
            media_items=media_items,
            media_ids=media_ids,
            media_sources=media_sources,
            scan_queue=scan_queue if not isinstance(scan_queue, ScanQueueService) else None,
            session_factory=session_factory,
            inline_processing=inline_processing,
            adapter_provider=get_shared_insightface_adapter if inline_processing else None,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception(
            "Scan dispatch failed after job commit",
            extra={"job_id": str(persisted_job_id), "tenant_id": str(tenant_uuid)},
        )
    return queued_analyze_job_response(persisted_job_id, len(media_items))


@router.post("/analyze", response_model=JobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_media(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    scan_queue=Depends(get_scan_queue_service_optional),
    _demo_quota=Depends(enforce_demo_quota),
    usage_admission_service=Depends(get_usage_admission_service),
) -> JobStatusResponse:
    """Scan media for face identities. Returns a job ID for polling."""
    tenant_uuid: uuid.UUID | None = None
    inline_processing = os.environ.get("RECOGNITION_ASYNC_ANALYZE_INLINE", "0") == "1"
    total_media_items = 0
    outcome = "error"
    started_at = _time.perf_counter()
    try:
        media_ids, media_sources, media_items = _prepare_media_items(request)
        total_media_items = len(media_items)
        tenant_uuid = await _prepare_tenant_context(
            request=request,
            auth=auth,
            session=session,
            inline_processing=inline_processing,
        )

        envelope = await json_request_envelope(http_request)
        operation_id = resolve_analyze_operation_id(
            header_value=idempotency_key,
            envelope=envelope,
            required=_is_usage_service(usage_admission_service),
        )
        fingerprint = build_analyze_request_fingerprint(
            tenant_id=tenant_uuid,
            route="analyze",
            media_ids=media_ids,
            media_sources=media_sources,
            options=fingerprint_options_from_envelope(envelope),
        )
        generated_job_id = uuid.uuid4()
        # NOTE: Tier-based batch limits removed for MVP (see progress-tracking-investigation-2026-01-20.md)
        async with admit_usage(
            usage_admission_service,
            tenant_id=tenant_uuid,
            idempotency_key=operation_id,
            job_id=str(generated_job_id),
            cost_units=total_media_items,
            operation_id=operation_id,
            request_fingerprint=fingerprint,
        ) as ticket:
            bound_job_id = bound_job_uuid(ticket, generated_job_id)
            response = await _schedule_analysis(
                background_tasks=background_tasks,
                session=session,
                scan_queue=scan_queue,
                tenant_uuid=tenant_uuid,
                media_items=media_items,
                media_ids=media_ids,
                media_sources=media_sources,
                inline_processing=inline_processing,
                auth=auth,
                job_id=bound_job_id,
                existing_job=is_usage_replay(ticket, generated_job_id),
            )
        outcome = "queued"
        return response
    except ProgrammingError as exc:
        outcome = "programming_error"
        if _is_insufficient_privilege(exc):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient privileges") from exc
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    except HTTPException:
        outcome = "http_exception"
        raise
    except Exception as exc:  # pragma: no cover - stub fallback
        outcome = "unexpected_exception"
        logger.exception("Unexpected error in analyze_media: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR_DETAIL) from exc
    finally:
        logger.info(
            "analyze_media_timing tenant_id=%s outcome=%s inline_processing=%s media_items=%d elapsed_ms=%.2f",
            request.tenant_id,
            outcome,
            inline_processing,
            total_media_items,
            (_time.perf_counter() - started_at) * 1000,
        )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    _query_tenant_id: str | None = Query(default=None, alias="tenant_id"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    auth=Depends(require_auth),
    job_service=Depends(get_job_service_dependency),
    session=Depends(get_optional_session),
) -> JobStatusResponse:
    """Poll job status by ID.

    Tenant authority is the authenticated key claim (or admin ``X-Tenant-ID``).
    Client query/header cannot override a tenant-scoped key. Auth-disabled
    polls remain unfenced for compatibility. Status reads never admit usage.
    """
    caller_tenant = _poll_tenant_authority(auth, x_tenant_id=x_tenant_id)

    # First check in-memory job service (for tests and in-memory mode)
    job = await job_service.get_job_status(job_id)
    if job and hasattr(job, "status") and hasattr(job, "id"):
        if isinstance(job, JobStatusResponse):
            if caller_tenant is not None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
            return job
        if not _job_is_visible(job=job, caller_tenant=caller_tenant):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        scan_repo = None
        cluster_repo = getattr(job_service, "cluster_repository", None)
        if session is not None:
            from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

            scan_repo = SqlAlchemyScanQueueRepository(session)
            if cluster_repo is None:
                from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository

                cluster_repo = SqlAlchemyClusterRepository(session)
        return await _job_to_pipeline_response(
            requested_job_id=job_id,
            domain_job=job,
            repo=job_service,
            scan_repo=scan_repo,
            cluster_repo=cluster_repo,
            caller_tenant=caller_tenant,
        )

    # Look up from database if we have a session

    if session is not None:
        from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

        repo = SqlAlchemyJobRepository(session)
        domain_job = await repo.get(job_id)
        if domain_job:
            if not _job_is_visible(job=domain_job, caller_tenant=caller_tenant):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
            from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
            from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

            scan_repo = SqlAlchemyScanQueueRepository(session)
            cluster_repo = SqlAlchemyClusterRepository(session)
            return await _job_to_pipeline_response(
                requested_job_id=job_id,
                domain_job=domain_job,
                repo=repo,
                scan_repo=scan_repo,
                cluster_repo=cluster_repo,
                caller_tenant=caller_tenant,
            )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


@router.post("/jobs/{job_id}/acknowledge-projection")
async def acknowledge_projection(
    job_id: str,
    request: AcknowledgeProjectionRequest,
    tenant_id: str = Header(alias="X-Tenant-ID"),
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
    retention_policy_service: RetentionPolicyServiceProtocol = Depends(get_retention_policy_service),
) -> dict[str, int | str]:
    """Record that WordPress projected the provided snapshot version for the pipeline job."""
    if session is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database unavailable")
    if auth and auth.tenant_claim and auth.tenant_claim != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")

    from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

    repo = SqlAlchemyJobRepository(session)
    projection = await repo.get_projection_status(job_id=job_id, tenant_id=tenant_id)
    if projection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="projection metadata not found for job")
    if projection.snapshot_version != request.snapshot_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="snapshot_version does not match job")
    if projection.acknowledged_at is None:
        try:
            await retention_policy_service.apply_disposal_after_ack(
                tenant_id=tenant_id,
                snapshot_generation_id=request.snapshot_generation_id,
                actor=f"tenant:{tenant_id}",
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        await repo.record_projection_acknowledgement(
            job_id=job_id,
            tenant_id=tenant_id,
            snapshot_version=request.snapshot_version,
            acknowledged_at=datetime.now(tz=UTC),
        )
        await session.commit()

    return {"status": "acknowledged", "snapshot_version": request.snapshot_version}


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(
    job_id: str,
    tenant_id: str = Header(alias="X-Tenant-ID"),
    job_repo=Depends(get_job_repo),
    scan_repo=Depends(get_scan_queue_repo),
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
        last_phase: str | None = None

        try:
            while True:
                # Poll DB for latest job state via general job repo
                job = await job_repo.get(job_id)
                if not job:
                    yield {"event": "error", "data": "Job not found"}
                    break

                progress = await _job_to_pipeline_response(
                    requested_job_id=job_id,
                    domain_job=job,
                    repo=job_repo,
                    scan_repo=scan_repo,
                )
                progress_payload = progress.progress.model_dump(exclude_none=True) if progress.progress else {}
                job_status = progress.status
                current_completed = progress_payload.get("completed", job.progress_completed)
                progress_payload.get("total", progress.progress.total if progress.progress else job.progress_total)
                event_type = "scan_progress" if progress.type == JobType.ANALYZE.value else "clustering_progress"

                now = time.time()
                # Yield if:
                # 1. Progress changed
                # 2. 500ms passed since last yield AND we have some progress
                # 3. 15s passed (heartbeat)
                phase = progress_payload.get("phase")
                should_yield = (
                    current_completed != last_completed
                    or phase != last_phase
                    or (now - last_emit > 0.5 and current_completed > 0)
                    or (now - last_heartbeat > 15)
                )

                if should_yield:
                    yield {
                        "event": "progress",
                        "data": json.dumps(
                            {
                                "type": event_type,
                                "job_id": progress.id,
                                "status": job_status,
                                **progress_payload,
                            }
                        ),
                    }
                    last_completed = current_completed
                    last_emit = now
                    last_heartbeat = now
                    last_phase = phase

                if job_status in TERMINAL_JOB_STATUSES:
                    yield {
                        "event": "done",
                        "data": json.dumps(
                            {
                                "type": event_type,
                                "job_id": progress.id,
                                "status": job_status,
                                **progress_payload,
                            }
                        ),
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
            tenant_uuid = uuid.UUID(str(tenant_id))
            await require_tenant_record(session, tenant_uuid)
        job_uuid = uuid.UUID(str(job_id))
        await scan_queue.cancel_scan_job(job_id=job_uuid)
        await session.flush()
        from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository

        repo = SqlAlchemyJobRepository(session)
        domain_job = await repo.get(job_id)
        if domain_job:
            from recognition.application.services.usage_settlement_service import settle_usage_job
            from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository

            await settle_usage_job(
                session,
                tenant_id=uuid.UUID(str(domain_job.tenant_id)),
                job_id=str(job_uuid),
            )
            scan_repo = SqlAlchemyScanQueueRepository(session)
            return await _job_to_response(domain_job, scan_repo=scan_repo)

    job = await job_service.cancel_job(job_id)
    return await _job_to_response(job)


# _job_to_response is imported from job_utils for shared use across routers
def _is_insufficient_privilege(exc: ProgrammingError) -> bool:
    """Detect RLS/permission errors from asyncpg/SQLAlchemy."""
    cause = exc.orig if hasattr(exc, "orig") else None
    if isinstance(cause, asyncpg.InsufficientPrivilegeError):
        return True
    return "InsufficientPrivilege" in str(exc)
