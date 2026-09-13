"""Async bulk describe-run routes."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.datastructures import UploadFile

from db.models import DemoInstance
from db.tenant_context import require_tenant_record, set_tenant_context
from recognition.infrastructure.repositories.audit_repository import AuditRepository
from recognition.interface_adapters.http.deps import get_optional_session, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import (
    hash_api_key_for_quota,
    maybe_consume_demo_quota,
)
from scene.application.describe_load import dump_load_snapshot
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import (
    DescribeItemOutcome,
    FusionNamingInputs,
    MissingNamingSnapshotError,
    gpu_run_policy,
    item_envelope_seconds,
    run_describe_job,
)
from scene.application.description_repository import ImageDescriptionRepository
from scene.application.gpu_state import read_gpu_state
from scene.application.visual_facts_service import VisualFactsService
from scene.config.settings import DescriptionSettings
from scene.domain.describe_run import (
    DescribeRunErrorCode,
    InvalidIdempotencyKeyError,
    RunKind,
    compute_eta_seconds,
    compute_request_digest,
    describe_job_error,
    normalize_idempotency_key,
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

logger = logging.getLogger(__name__)

_IMAGE_KEY_PREFIX = "image_"
# GUIDEDFIX-2 [S05]: the one constraint whose violation means "this key is
# already reserved". Every other IntegrityError is a real, permanent failure.
_IDEMPOTENCY_CONSTRAINT = "uq_image_description_runs_idempotency_key"
_IDEMPOTENCY_SQLITE_COLUMNS = ("image_description_runs.tenant_id", "image_description_runs.idempotency_key")


def _is_idempotency_reservation_conflict(exc: IntegrityError) -> bool:
    """True only when ``exc`` is the idempotency-key unique violation.

    psycopg exposes the constraint name on ``exc.orig.diag``; when the driver
    does not (or the diagnostic is empty) fall back to SQLSTATE 23505 plus the
    constraint name in the message. SQLite names no constraints at all — its
    UNIQUE violations list the columns instead — so match those explicitly
    rather than treating any SQLite IntegrityError as a collision.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name:
        return str(constraint_name) == _IDEMPOTENCY_CONSTRAINT
    message = str(orig) if orig is not None else str(exc)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate is not None:
        return str(sqlstate) == "23505" and _IDEMPOTENCY_CONSTRAINT in message
    lowered = message.lower()
    if "unique constraint failed" in lowered:
        return all(column in lowered for column in _IDEMPOTENCY_SQLITE_COLUMNS)
    return _IDEMPOTENCY_CONSTRAINT in message


async def _reject_when_demo_quota_is_already_spent(auth, session, *, units: int) -> None:
    """Cheap read-only 429 for an over-quota demo key, ahead of any insert.

    Mirrors ``consume_demo_quota_units``'s reject shape without consuming: it is
    an optimisation, not the enforcement point. The atomic guarded UPDATE in
    ``try_consume_demo_quota`` (called after the reservation lands) remains the
    only authority on the balance, so a concurrent charge between this read and
    that update still yields the correct 429 — just later, and after the insert.
    """
    if session is None or not getattr(auth, "enabled", False):
        return
    token = getattr(auth, "token", None)
    if not token:
        return
    key_hash = hash_api_key_for_quota(token)
    row = (
        await session.execute(
            select(DemoInstance.recognition_quota, DemoInstance.recognition_used, DemoInstance.revoked)
            .where(DemoInstance.api_key_ref == key_hash)
            .limit(1)
        )
    ).first()
    if row is None:
        # Not a demo registry key: no metering applies (main-compatible).
        return
    quota, used, revoked = int(row[0]), int(row[1]), bool(row[2])
    remaining = 0 if revoked else max(0, quota - used)
    if units > remaining:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {
                "code": "demo_quota_exceeded",
                "message": "demo recognition quota exceeded",
                "quota_remaining": remaining,
            },
        )


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
        gpu_state=read_gpu_state(),
        recognition_enabled=bool(run.recognition_enabled),
        deadline_seconds=run.deadline_seconds,
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
                error=describe_job_error(item),
                tier=item.tier,
                result_generation=item.result_generation,
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
    *,
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    adapter=None,
    settings=None,
    recognition_enabled: bool = True,
):
    """Real per-item describe adapter: load bytes -> VisualFactsService -> outcome.

    Reuses describe.py's exact adapter/service construction (auth-free here; the
    submit route already validated the tenant). Opens its own session per call so
    the cache read/write is independent of the worker's item-tracking session.
    """
    adapter = adapter or get_description_adapter()
    settings = settings or DescriptionSettings()
    timeout = _generation_timeout_seconds(settings, adapter)

    async def describe_one(
        media_id: int,
        image_bytes: bytes | None,
        content_type: str | None,
        *,
        naming_inputs: FusionNamingInputs | None = None,
    ) -> DescribeItemOutcome:
        if not image_bytes:
            raise ValueError(f"no image bytes stored for media_id={media_id}")
        if naming_inputs is None and recognition_enabled:
            raise MissingNamingSnapshotError(
                f"recognition-enabled bulk describe requires preloaded naming_inputs for media_id={media_id}"
            )
        async with session_factory() as svc_session:
            await set_tenant_context(svc_session, tenant_id)
            confirmed_faces: list = []
            naming_policy = None
            if naming_inputs is not None:
                confirmed_faces, naming_policy = naming_inputs
                # DATA-19: face elements + naming_policy are the shared snapshot;
                # copy the list so Stage-2 mutation cannot alias Stage-3's sequence.
                confirmed_faces = list(confirmed_faces or [])
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
                # No context to drop: the /describe/run multipart form defines
                # only tenant_id, media_ids, recognition_enabled and
                # image_<media_id> -- unlike /describe, which carries an
                # envelope context/context_pack. Identity context does reach
                # here, as naming_inputs. Passing None rather than a synthesized
                # stand-in keeps context_hash the empty-context digest, so a
                # bulk row can only share a cache row with a genuinely
                # context-free describe (rg-015: never invent contract
                # metadata). Add a form field before threading anything here.
                context=None,
                confirmed_faces=confirmed_faces,
                naming_policy=naming_policy,
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
            phrase_boxes=tuple(service.last_phrase_boxes or ()),
            attachments=tuple(service.last_attachments or ()),
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


def _parse_recognition_enabled(raw: object) -> bool:
    """Multipart boolean; omitted → True so today's naming-on path stays the default."""
    if raw is None:
        return True
    if isinstance(raw, bool):
        return raw
    if not isinstance(raw, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "form field 'recognition_enabled' must be a boolean")
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "form field 'recognition_enabled' must be a boolean")


def _parse_idempotency_key(raw: object) -> str | None:
    """Caller retry token; omitted → None (today's non-deduped accept)."""
    try:
        return normalize_idempotency_key(raw)
    except InvalidIdempotencyKeyError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": DescribeRunErrorCode.INVALID_IDEMPOTENCY_KEY.value,
                "message": str(exc),
                "field": "idempotency_key",
            },
        ) from exc


def _stored_request_digest(run) -> str:
    """The digest ``run`` was reserved under, recomputed only when absent.

    Runs created before ``request_digest`` existed (or outside the keyed submit
    path) carry NULL; derive the same canonical form from the stored columns so
    the comparison below is digest-to-digest in every case.
    """
    stored = getattr(run, "request_digest", None)
    if stored:
        return str(stored)
    return compute_request_digest(
        media_ids=list(run.media_ids or []),
        recognition_enabled=bool(run.recognition_enabled),
    )


def _replay_or_conflict(run, *, media_ids: list[int], recognition_enabled: bool) -> DescribeRunResponse:
    """Return the reserved run, or 409 when the token names a different payload.

    The replay is deliberately indistinguishable from a first accept (202, same
    body): a caller must never be able to tell a retry succeeded twice.

    [S03] The comparison is a digest of the CANONICAL request (sorted unique
    media ids + recognition_enabled), not a positional list compare. The WP
    client builds media_ids from a query with no pinned ordering, so [70, 71]
    and [71, 70] are one submission — 409'ing the reshuffle would reject exactly
    the blind retry this feature exists to serve and force the caller to mint a
    new key, spending the second paid run the key was added to prevent.

    [S04] Image bytes are outside the binding by design; see
    ``compute_request_digest`` for why, and the published schema says so.
    """
    if _stored_request_digest(run) != compute_request_digest(
        media_ids=media_ids, recognition_enabled=recognition_enabled
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": DescribeRunErrorCode.IDEMPOTENCY_CONFLICT.value,
                "message": (
                    "this 'idempotency_key' is already bound to a describe run submitted with a different payload"
                ),
                "field": "idempotency_key",
                # [S09] Never echo the reserved run's id or media ids. This
                # lookup runs before require_tenant_record and POST only binds
                # the tenant when the caller carries a claim, so a write-capable
                # caller with no claim could otherwise name any tenant_id, guess
                # a key, and read back that tenant's run id and media id list.
            },
        )
    return _run_response(run)


async def _read_image_parts(
    form, settings: DescriptionSettings, *, media_ids: Sequence[int]
) -> Mapping[int, tuple[bytes, str | None]]:
    """Read + bound each image_<media_id> part, mirroring describe.py's caps.

    Bound reads before materialising bytes so unused or oversized uploads cannot exhaust memory.
    """
    images: dict[int, tuple[bytes, str | None]] = {}
    requested = set(media_ids)
    total = 0
    cap = settings.max_description_image_bytes
    chunk_size = 1024 * 1024
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
        if media_id not in requested or media_id in images:
            continue
        if not isinstance(value, UploadFile):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"form key '{key}' must be a file upload")
        content_type = value.content_type or ""
        if content_type not in settings.allowed_description_mime_types:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"unsupported image content-type '{content_type}' for part '{key}'",
            )
        size_error = f"image part '{key}' exceeds the description size cap ({cap} bytes)"
        if value.size is not None and value.size > cap:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, size_error)
        data = bytearray()
        while chunk := await value.read(chunk_size):
            data.extend(chunk)
            total += len(chunk)
            if len(data) > cap or total > cap * len(requested):
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, size_error)
        if not data:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"image part '{key}' is empty")
        images[media_id] = (bytes(data), content_type)
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
    recognition_enabled = _parse_recognition_enabled(form.get("recognition_enabled"))
    idempotency_key = _parse_idempotency_key(form.get("idempotency_key"))
    settings = DescriptionSettings()

    if idempotency_key is not None:
        # Resolve a replay before any paid or expensive work: no image bytes
        # read, no quota charged, no run created, no background task queued.
        await set_tenant_context(session, tenant_id)
        reserved = await DescribeRunRepository(session).get_run_by_idempotency_key(
            tenant_id=tenant_id, idempotency_key=idempotency_key
        )
        if reserved is not None:
            return _replay_or_conflict(reserved, media_ids=media_ids, recognition_enabled=recognition_enabled)

    if not media_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "'media_ids' must be non-empty",
        )
    images = await _read_image_parts(form, settings, media_ids=media_ids)
    missing = [m for m in media_ids if m not in images]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"missing image_<media_id> part(s) for media_ids: {missing}",
        )
    # Capture the adapter and its GPU execution policy before persisting the
    # run. The worker must use this exact pairing even if process configuration
    # changes before the background task begins.
    adapter = get_description_adapter()
    run_gpu_policy = gpu_run_policy(adapter_kind=adapter.kind, settings=settings)

    # Charge unique media ids only (order-preserving dedupe); durable at dispatch.
    unique_media_ids = list(dict.fromkeys(media_ids))
    # [S01] ONE number, derived from the value the worker is actually handed
    # below, so disclosure and enforcement cannot drift on either axis:
    #   * per item: _generation_timeout_seconds(settings, adapter) is what
    #     run_describe_job receives; settings.generation_timeout_seconds alone is
    #     wrong for LOCAL_CPU, which enforces VlmSettings().inference_timeout_seconds.
    #   * per run: the worker's real per-item bound is item_envelope_seconds()
    #     (naming budget + describe timeout) and it processes items serially, so
    #     the run's budget is that envelope times the item count.
    # Warm-up is deliberately excluded — see the DescribeRunResponse contract.
    item_timeout_seconds = _generation_timeout_seconds(settings, adapter)
    run_deadline_seconds = float(item_envelope_seconds(item_timeout_seconds) * len(unique_media_ids))

    await set_tenant_context(session, tenant_id)
    await require_tenant_record(session, tenant_id)
    repo = DescribeRunRepository(session)
    # [S07] Reject an over-quota demo key BEFORE create_run. The durable charge
    # stays behind the reservation (below), but create_run flushes the run row
    # plus one item per media id with image bytes inline (up to
    # max_description_image_bytes each, up to 200 items) — so a 429 raised only
    # after the insert costs ~N x image-size of write-then-rollback IO per
    # rejected request. This pre-check reads and mutates nothing.
    await _reject_when_demo_quota_is_already_spent(auth, session, units=len(unique_media_ids))
    await set_tenant_context(session, tenant_id)
    # Reserve before charging: the insert is the reservation, and the unique
    # (tenant_id, idempotency_key) index — not the read above — is what makes two
    # concurrent retries converge on one run. The loser rolls back before it can
    # spend quota, so a network fault cannot buy a second run ([COST-10]).
    try:
        run_id = await repo.create_run(
            tenant_id=tenant_id,
            media_ids=media_ids,
            created_by_user_id=getattr(auth, "user_id", None),
            images=images,
            recognition_enabled=recognition_enabled,
            idempotency_key=idempotency_key,
            request_digest=compute_request_digest(media_ids=media_ids, recognition_enabled=recognition_enabled),
            deadline_seconds=run_deadline_seconds,
        )
    except IntegrityError as exc:
        # [S05] Only the idempotency reservation may be reinterpreted as a
        # collision. A blanket except turns every permanent IntegrityError —
        # e.g. the tenant row cascade-deleted between require_tenant_record and
        # this flush — into a 503 telling the client to retry a deterministically
        # failing insert forever, with the real cause buried in the __cause__
        # chain and no log line.
        if idempotency_key is None or not _is_idempotency_reservation_conflict(exc):
            logger.error(
                "describe run insert failed for tenant %s (not an idempotency collision)",
                tenant_id,
                exc_info=exc,
            )
            raise
        await session.rollback()
        await set_tenant_context(session, tenant_id)
        winner = await repo.get_run_by_idempotency_key(tenant_id=tenant_id, idempotency_key=idempotency_key)
        if winner is None:
            # The key is taken but unreadable from here: fail closed rather than
            # create a second run under an uncertain reservation.
            logger.error(
                "describe run reservation uncertain for tenant %s: the idempotency key collided but no "
                "live run holds it",
                tenant_id,
                exc_info=exc,
            )
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "describe run reservation is uncertain; retry with the same idempotency_key",
            ) from exc
        return _replay_or_conflict(winner, media_ids=media_ids, recognition_enabled=recognition_enabled)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    # Durable charge. NOTE: for a demo key maybe_consume_demo_quota ->
    # consume_demo_quota_units commits internally (no-refund metering), so the
    # reservation above is made durable by the quota dep; for a non-demo key the
    # session.commit() below is the only commit and the sole durability point.
    await maybe_consume_demo_quota(auth, session, units=len(unique_media_ids))
    await set_tenant_context(session, tenant_id)
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
            recognition_enabled=recognition_enabled,
        ),
        # [S01] The same value run_deadline_seconds was derived from.
        timeout_seconds=item_timeout_seconds,
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
