"""Slice 1: correlation_id persistence + HTTP-layer capture (E15-2b).

Tests cover:
- CorrelationSource enum exists with API/WORKER members.
- ScanQueueItem dataclass carries correlation_id + correlation_source.
- ScanQueueService.populate_scan_job_items accepts a correlation_id kwarg and
  threads it through the chunk loop into every repository.enqueue_items call.
- When the kwarg is omitted, enqueue calls receive correlation_id=None.
- The repository round-trips the correlation_id via claim_pending_items.
- The HTTP layer (_schedule_analysis) captures get_correlation_id() from the
  request-scoped contextvar BEFORE background_tasks.add_task schedules
  chain_populate_and_process, and forwards the captured value as an explicit
  kwarg into populate_scan_job_items_async.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from db.models import IdentityScanJob, IdentityScanJobItem
from recognition.application.scan.queue_repository import ScanQueueItem, ScanQueueRepository
from recognition.application.scan.scan_queue_service import ScanQueueService
from recognition.application.tasks.scan import populate_scan_job_items_async
from recognition.infrastructure.repositories.scan_queue_repository import SqlAlchemyScanQueueRepository
from recognition.interface_adapters.http.middleware.correlation import (
    CorrelationSource,
    _correlation_id_var,
)


def test_correlation_source_enum_members() -> None:
    assert CorrelationSource.API.value == "api"
    assert CorrelationSource.WORKER.value == "worker"
    # StrEnum: equal to its string value.
    assert CorrelationSource.API == "api"
    assert CorrelationSource.WORKER == "worker"


def test_scan_queue_item_has_correlation_fields() -> None:
    item = ScanQueueItem(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_id=1,
        media_url="u",
        status="pending",
        attempts=0,
        identities_detected=0,
        last_error=None,
        correlation_id="req-abc",
        correlation_source=CorrelationSource.API.value,
    )
    assert item.correlation_id == "req-abc"
    assert item.correlation_source == "api"


class _RecordingRepo:
    """In-memory ScanQueueRepository stub that records enqueue_items calls."""

    def __init__(self) -> None:
        self.enqueue_calls: list[dict[str, object]] = []
        self.messages: dict[uuid.UUID, str] = {}
        self.media_ids_recorded: list[int] = []

    async def create_job(self, *, tenant_id, media_ids, created_by_user_id=None):  # noqa: ANN001
        return uuid.uuid4()

    async def create_job_with_message(self, *, tenant_id, media_ids, total, message, created_by_user_id=None):  # noqa: ANN001
        jid = uuid.uuid4()
        self.messages[jid] = message or ""
        return jid

    async def enqueue_items(self, *, job_id, tenant_id, items, correlation_id=None):  # noqa: ANN001
        items_list = list(items)
        self.enqueue_calls.append(
            {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "items": items_list,
                "correlation_id": correlation_id,
            }
        )
        return len(items_list)

    async def update_job_message(self, *, job_id, message):  # noqa: ANN001
        self.messages[job_id] = message or ""

    async def finalize_job_queue(self, *, job_id, media_ids, message):  # noqa: ANN001
        self.media_ids_recorded = list(media_ids)
        self.messages[job_id] = message or ""


@pytest.mark.asyncio
async def test_populate_threads_correlation_id_through_chunk_loop() -> None:
    repo = _RecordingRepo()
    queue = ScanQueueService(repo)  # type: ignore[arg-type]
    media_items = [(i, f"http://u/{i}.jpg") for i in range(1, 6)]

    await queue.populate_scan_job_items(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_items=media_items,
        chunk_size=2,
        correlation_id="req-fixed-abc",
    )

    assert len(repo.enqueue_calls) >= 2
    for call in repo.enqueue_calls:
        assert call["correlation_id"] == "req-fixed-abc"


@pytest.mark.asyncio
async def test_populate_without_correlation_passes_none() -> None:
    repo = _RecordingRepo()
    queue = ScanQueueService(repo)  # type: ignore[arg-type]

    await queue.populate_scan_job_items(
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_items=[(1, "u")],
    )

    assert repo.enqueue_calls[0]["correlation_id"] is None


@pytest.mark.asyncio
async def test_populate_scan_job_items_async_forwards_correlation_id() -> None:
    """chain_populate_and_process -> populate_scan_job_items_async path."""

    captured: dict[str, object] = {}

    class _CaptureQueue:
        async def populate_scan_job_items(self, *, job_id, tenant_id, media_items, correlation_id=None):  # noqa: ANN001
            captured["correlation_id"] = correlation_id
            return len(list(media_items))

    await populate_scan_job_items_async(
        tenant_id=str(uuid.uuid4()),
        job_id=str(uuid.uuid4()),
        media_items=[(1, "u")],
        scan_queue=_CaptureQueue(),  # type: ignore[arg-type]
        correlation_id="req-captured-xyz",
    )
    assert captured["correlation_id"] == "req-captured-xyz"


@pytest.mark.asyncio
async def test_enqueue_items_persists_correlation_and_claim_round_trips(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)

    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[42])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[(42, "http://example.test/42.jpg")],
        correlation_id="req-rt-001",
    )

    row = (
        await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id))
    ).scalar_one()
    assert row.correlation_id == "req-rt-001"
    assert row.correlation_source == CorrelationSource.API.value

    claimed = await repo.claim_pending_items(tenant_id=tenant.id, job_id=job_id, limit=1, now=datetime.now(tz=UTC))
    assert len(claimed) == 1
    assert claimed[0].correlation_id == "req-rt-001"
    assert claimed[0].correlation_source == CorrelationSource.API.value


@pytest.mark.asyncio
async def test_enqueue_items_without_correlation_leaves_null(db_session, tenant) -> None:
    repo = SqlAlchemyScanQueueRepository(db_session)
    job_id = await repo.create_job(tenant_id=tenant.id, media_ids=[7])
    await repo.enqueue_items(
        job_id=job_id,
        tenant_id=tenant.id,
        items=[(7, "http://u/7.jpg")],
    )
    row = (
        await db_session.execute(select(IdentityScanJobItem).where(IdentityScanJobItem.job_id == job_id))
    ).scalar_one()
    assert row.correlation_id is None
    assert row.correlation_source is None


def test_analyze_router_captures_contextvar_before_background_task(monkeypatch) -> None:
    """_schedule_analysis must read the contextvar at request scope and pass it as a kwarg.

    The background task runs after the HTTP response and (worst case) outside
    the contextvar's request scope; the defensive design captures the id
    eagerly and forwards it explicitly.
    """
    import asyncio

    from recognition.interface_adapters.http.routers import analyze as analyze_router

    scheduled_kwargs: dict[str, object] = {}

    class _BG:
        def add_task(self, func, /, **kwargs):  # noqa: ANN001
            scheduled_kwargs.update(kwargs)

    class _FakeQueue:
        async def create_scan_job_record(self, *, tenant_id, total, created_by_user_id=None):  # noqa: ANN001
            return uuid.uuid4()

    tenant_uuid = uuid.uuid4()
    token = _correlation_id_var.set("req-captured-123")
    try:
        asyncio.get_event_loop().run_until_complete(
            analyze_router._schedule_analysis(
                background_tasks=_BG(),
                session=None,
                scan_queue=_FakeQueue(),
                tenant_uuid=tenant_uuid,
                media_items=[(1, "u")],
                media_ids=["1"],
                media_sources=["wp"],
                inline_processing=False,
                auth=None,
            )
        )
    finally:
        _correlation_id_var.reset(token)

    assert scheduled_kwargs.get("correlation_id") == "req-captured-123"
