"""Async bulk describe-run routes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import UploadFile

from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.infrastructure.repositories.audit_repository import AuditRepository
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import maybe_consume_demo_quota
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import DescribeItemOutcome, gpu_run_policy, run_describe_job
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.visual_facts_service import VisualFactsService
from scene.config.settings import DescriptionSettings
from scene.domain.describe_run import (
    RunKind,
    compute_eta_seconds,
)
from scene.interface_adapters.http.deps import get_description_adapter
from scene.interface_adapters.http.routers.describe import (
    _DescriptionAuditSink,
    _DescriptionMetricsSink,
    _generation_timeout_seconds,
    worker_session_factory,
)
from scene.interface_adapters.http.schemas.responses import (
    DescribeRunItemResponse,
    DescribeRunItemsResponse,
    DescribeRunResponse,
)

router = APIRouter(tags=["describe-runs"])

_IMAGE_KEY_PREFIX = "image_"


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
        eta_seconds=compute_eta_seconds(run),
        gpu_state=None,
    )


def _run_items_response(run, items) -> DescribeRunItemsResponse:
    return DescribeRunItemsResponse(
        tenant_id=str(run.tenant_id),
        run_id=str(run.id),
        items=[
            DescribeRunItemResponse(
                media_id=item.media_id,
                status=item.status,
                alt_text_draft=item.alt_text_draft,
                caption=item.caption,
                provenance=item.provenance,
            )
            for item in items
        ],
    )


def _require_tenant_uuid(auth) -> uuid.UUID:
    """Resolve the tenant claim to a UUID, or 400 (never an unhandled 500). (S3-02)"""
    claim = (getattr(auth, "tenant_claim", None) or "").strip()
    if not claim:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "tenant claim required")
    try:
        return uuid.UUID(claim)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid tenant claim") from exc


async def _prepare_repo(*, session, auth, tenant_id: uuid.UUID) -> DescribeRunRepository:
    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != str(tenant_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch")
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")
    await set_tenant_context(session, tenant_id)
    await require_tenant_record(session, tenant_id)
    return DescribeRunRepository(session)


def _build_describe_one(
    *, session_factory: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, adapter=None, settings=None
):
    """Real per-item describe adapter: load bytes -> VisualFactsService -> outcome.

    Reuses describe.py's exact adapter/service construction (auth-free here; the
    submit route already validated the tenant). Opens its own session per call so
    the cache read/write is independent of the worker's item-tracking session.
    """
    adapter = adapter or get_description_adapter()
    settings = settings or DescriptionSettings()
    timeout = _generation_timeout_seconds(settings, adapter)

    async def describe_one(media_id: int, image_bytes: bytes | None, content_type: str | None) -> DescribeItemOutcome:
        if not image_bytes:
            raise ValueError(f"no image bytes stored for media_id={media_id}")
        async with session_factory() as svc_session:
            await set_tenant_context(svc_session, tenant_id)
            service = VisualFactsService(
                adapter=adapter,
                repository=ImageDescriptionRepository(svc_session),
                audit_sink=_DescriptionAuditSink(AuditRepository(svc_session)),
                metrics=_DescriptionMetricsSink(),
                generation_timeout_seconds=timeout,
            )
            response = await service.describe(
                tenant_id=tenant_id,
                media_id=media_id,
                image_bytes=image_bytes,
                context=None,
            )
            await svc_session.commit()
        provenance = {
            "adapter": str(response.adapter),
            "model_id": response.model_id,
            "model_version": response.model_version,
            "prompt_or_task_version": response.prompt_or_task_version,
            "image_hash": response.image_hash,
            "context_hash": response.context_hash,
            "cached": response.cached,
            "duration_ms": response.duration_ms,
        }
        return DescribeItemOutcome(
            alt_text_draft=response.alt_text_draft,
            caption=response.visual_facts.caption,
            provenance=provenance,
            tier=response.tier,
        )

    return describe_one


def _parse_media_ids(raw: object) -> list[int]:
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "form field 'media_ids' (JSON int array) is required"
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'media_ids' is not valid JSON: {exc}") from exc
    if not isinstance(parsed, list) or not all(isinstance(m, int) and not isinstance(m, bool) for m in parsed):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'media_ids' must be a JSON array of integers")
    if any(m <= 0 for m in parsed):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "media_ids must be positive integers")
    return parsed


async def _read_image_parts(form, settings: DescriptionSettings) -> Mapping[int, tuple[bytes, str | None]]:
    """Read + bound each image_<media_id> part, mirroring describe.py's caps.

    BE-03: enforce the allowed content-type set (415) and the per-file byte cap
    (413) so a caller cannot stream unbounded bytes into memory or smuggle a
    non-image part into the run.
    """
    images: dict[int, tuple[bytes, str | None]] = {}
    for key, value in form.multi_items():
        if not key.startswith(_IMAGE_KEY_PREFIX):
            continue
        suffix = key[len(_IMAGE_KEY_PREFIX) :]
        try:
            media_id = int(suffix)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"image part key '{key}' must be 'image_<media_id>'"
            ) from exc
        if not isinstance(value, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"form key '{key}' must be a file upload")
        content_type = value.content_type or ""
        if content_type not in settings.allowed_description_mime_types:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"unsupported image content-type '{content_type}' for part '{key}'",
            )
        data = await value.read()
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"image part '{key}' is empty")
        if len(data) > settings.max_description_image_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"image part '{key}' exceeds the description size cap ({settings.max_description_image_bytes} bytes)",
            )
        images[media_id] = (data, content_type)
    return images


@router.post("/describe/run", response_model=DescribeRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_describe_run(
    request: Request,
    background_tasks: BackgroundTasks,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    if session is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database session unavailable")

    form = await request.form()
    tenant_raw = form.get("tenant_id")
    if not isinstance(tenant_raw, str) or not tenant_raw.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "form field 'tenant_id' (uuid) is required")
    try:
        tenant_id = uuid.UUID(tenant_raw.strip())
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'tenant_id' is not a valid uuid") from exc

    auth_tenant = (getattr(auth, "tenant_claim", None) or "").strip()
    if auth_tenant and auth_tenant != str(tenant_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant mismatch between auth and request envelope")

    media_ids = _parse_media_ids(form.get("media_ids"))
    settings = DescriptionSettings()
    images = await _read_image_parts(form, settings)
    missing = [m for m in media_ids if m not in images]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"missing image_<media_id> part(s) for media_ids: {missing}",
        )
    if not media_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "'media_ids' must be non-empty",
        )
    # Capture the adapter and its GPU execution policy before persisting the
    # run. The worker must use this exact pairing even if process configuration
    # changes before the background task begins.
    adapter = get_description_adapter()
    run_gpu_policy = gpu_run_policy(adapter_kind=adapter.kind, settings=settings)

    await set_tenant_context(session, tenant_id)
    await require_tenant_record(session, tenant_id)
    # Charge unique media ids only (order-preserving dedupe); durable at dispatch.
    unique_media_ids = list(dict.fromkeys(media_ids))
    await maybe_consume_demo_quota(auth, session, units=len(unique_media_ids))
    await set_tenant_context(session, tenant_id)
    repo = DescribeRunRepository(session)
    try:
        run_id = await repo.create_run(
            tenant_id=tenant_id,
            media_ids=media_ids,
            created_by_user_id=getattr(auth, "user_id", None),
            images=images,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()

    session_factory = worker_session_factory(session)
    # GPUW-1: publish the load dump *before* the job is queued, so the burst-GPU
    # start cycle sees batch_in_progress on its next tick rather than a tick
    # after the first item already needed the GPU.
    await dump_load_snapshot(session_factory)
    background_tasks.add_task(
        run_describe_job,
        tenant_id=tenant_id,
        run_id=run_id,
        session_factory=session_factory,
        describe_one=_build_describe_one(
            session_factory=session_factory,
            tenant_id=tenant_id,
            adapter=adapter,
            settings=settings,
        ),
        timeout_seconds=_generation_timeout_seconds(settings, adapter),
        gpu_policy=run_gpu_policy,
    )

    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:  # pragma: no cover - defensive only
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "describe run was not persisted")
    return _run_response(run)


def _reject_single_run(run) -> None:
    """Bulk wire surface is disjoint from async single-runs (design (g))."""
    if run is not None and run.run_kind == RunKind.SINGLE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")


@router.get("/describe/run/{run_id}", response_model=DescribeRunResponse)
async def get_describe_run(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    tenant_id = _require_tenant_uuid(auth)
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    _reject_single_run(run)
    return _run_response(run)


@router.get("/describe/run/{run_id}/items", response_model=DescribeRunItemsResponse)
async def list_describe_run_items(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunItemsResponse:
    """WBUX-4 INT-01a: per-item drafts so a completed run's work product is
    reachable by the operator (the WP History write-back consumer)."""
    tenant_id = _require_tenant_uuid(auth)
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    _reject_single_run(run)
    items = await repo.list_run_items(tenant_id=tenant_id, run_id=run_id)
    return _run_items_response(run, items)


@router.delete("/describe/run/{run_id}", response_model=DescribeRunResponse)
async def cancel_describe_run(
    run_id: uuid.UUID,
    auth=Depends(require_write_access),
    session=Depends(get_optional_session),
) -> DescribeRunResponse:
    tenant_id = _require_tenant_uuid(auth)
    repo = await _prepare_repo(session=session, auth=auth, tenant_id=tenant_id)
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    _reject_single_run(run)
    if not await repo.request_cancel(tenant_id=tenant_id, run_id=run_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    await session.commit()
    run = await repo.get_run(tenant_id=tenant_id, run_id=run_id)
    if run is None:  # pragma: no cover - defensive only
        raise HTTPException(status.HTTP_404_NOT_FOUND, "describe run not found")
    return _run_response(run)
