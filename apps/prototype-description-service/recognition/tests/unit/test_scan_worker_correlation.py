"""Slice 2: worker correlation binding + scan_worker configure_logging (E15-2b).

Tests cover:
- ScanItemHandler binds the claimed item's correlation_id into the request
  contextvar before executing per-item logic, and resets it after.
- When an item has no correlation_id, the worker generates a fresh
  req-<uuid7> and binds it with CorrelationSource.WORKER.
- scan_worker._main calls configure_logging so worker stdout carries JSON
  with a correlation_id field.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from recognition.application.scan.queue_repository import ScanQueueItem
from recognition.interface_adapters.http.middleware.correlation import (
    CorrelationSource,
    _correlation_id_var,
    get_correlation_id,
)


def _make_item(correlation_id: str | None = None, source: str | None = None) -> ScanQueueItem:
    return ScanQueueItem(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        media_id=1,
        media_url="http://u/1.jpg",
        status="processing",
        attempts=1,
        identities_detected=0,
        last_error=None,
        created_at=datetime.now(tz=UTC),
        correlation_id=correlation_id,
        correlation_source=source,
    )


@pytest.mark.asyncio
async def test_scan_item_handler_binds_api_correlation_id_during_processing() -> None:
    """When a claimed item carries an API correlation_id, the worker must bind
    it into the contextvar before invoking scan_service.process_media_item, so
    that any logger.info() emitted during processing stamps that id."""
    from recognition.worker.handlers import scan as scan_mod

    captured_ids: list[str | None] = []

    async def _fake_process(*, tenant_id, media_id, media_url, job_id=None):  # noqa: ANN001
        captured_ids.append(get_correlation_id())
        return 0

    item = _make_item(correlation_id="req-from-api-111", source=CorrelationSource.API.value)

    handler = scan_mod.ScanItemHandler(
        session_factory=AsyncMock(),
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=1,
    )

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    handler._session_factory = lambda: fake_session  # type: ignore[assignment]

    with (
        patch.object(scan_mod, "enable_rls_bypass", new=AsyncMock()),
        patch.object(scan_mod, "SqlAlchemyScanQueueRepository") as repo_cls,
        patch.object(handler, "_build_scan_service") as build_svc,
        patch.object(handler, "_refresh_job_progress", new=AsyncMock()),
    ):
        repo = AsyncMock()
        repo_cls.return_value = repo
        svc = AsyncMock()
        svc.process_media_item = _fake_process
        build_svc.return_value = svc

        await handler.process_items(claimed=[item])

    assert captured_ids == ["req-from-api-111"], (
        f"Expected handler to bind correlation_id into contextvar before process_media_item; got {captured_ids}"
    )


@pytest.mark.asyncio
async def test_scan_item_handler_generates_worker_id_when_missing() -> None:
    """When a claimed item has no correlation_id (legacy or backfilled row),
    the worker must synthesize a fresh req-<uuid7> id and bind it, so every
    worker-side log line still carries some id."""
    from recognition.worker.handlers import scan as scan_mod

    captured_ids: list[str | None] = []

    async def _fake_process(*, tenant_id, media_id, media_url, job_id=None):  # noqa: ANN001
        captured_ids.append(get_correlation_id())
        return 0

    item = _make_item(correlation_id=None, source=None)

    handler = scan_mod.ScanItemHandler(
        session_factory=AsyncMock(),
        detector=AsyncMock(),
        generator=AsyncMock(),
        max_attempts=3,
        max_concurrency=1,
    )
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    handler._session_factory = lambda: fake_session  # type: ignore[assignment]

    with (
        patch.object(scan_mod, "enable_rls_bypass", new=AsyncMock()),
        patch.object(scan_mod, "SqlAlchemyScanQueueRepository") as repo_cls,
        patch.object(handler, "_build_scan_service") as build_svc,
        patch.object(handler, "_refresh_job_progress", new=AsyncMock()),
    ):
        repo = AsyncMock()
        repo_cls.return_value = repo
        svc = AsyncMock()
        svc.process_media_item = _fake_process
        build_svc.return_value = svc

        await handler.process_items(claimed=[item])

    assert len(captured_ids) == 1
    bound = captured_ids[0]
    assert bound is not None
    assert bound.startswith("req-"), f"Expected worker fallback id req-<uuid7>; got {bound!r}"


@pytest.mark.asyncio
async def test_scan_item_handler_resets_correlation_after_processing() -> None:
    """The handler must not leak the item's correlation_id into the ambient
    contextvar after _process_item returns."""
    from recognition.worker.handlers import scan as scan_mod

    outer_token = _correlation_id_var.set("outer-unrelated-xyz")
    try:
        item = _make_item(correlation_id="req-leaked-001", source=CorrelationSource.API.value)

        handler = scan_mod.ScanItemHandler(
            session_factory=AsyncMock(),
            detector=AsyncMock(),
            generator=AsyncMock(),
            max_attempts=3,
            max_concurrency=1,
        )
        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_session.__aexit__ = AsyncMock(return_value=False)
        handler._session_factory = lambda: fake_session  # type: ignore[assignment]

        with (
            patch.object(scan_mod, "enable_rls_bypass", new=AsyncMock()),
            patch.object(scan_mod, "SqlAlchemyScanQueueRepository") as repo_cls,
            patch.object(handler, "_build_scan_service") as build_svc,
            patch.object(handler, "_refresh_job_progress", new=AsyncMock()),
        ):
            repo = AsyncMock()
            repo_cls.return_value = repo
            svc = AsyncMock()
            svc.process_media_item = AsyncMock(return_value=0)
            build_svc.return_value = svc

            await handler.process_items(claimed=[item])

        assert get_correlation_id() == "outer-unrelated-xyz", (
            "Handler leaked the item correlation_id into the outer contextvar scope"
        )
    finally:
        _correlation_id_var.reset(outer_token)


def test_scan_worker_main_uses_structured_configure_logging() -> None:
    """scan_worker._main must call api.logging_config.configure_logging so
    worker stdout emits JSON records with a correlation_id field — not raw
    basicConfig text. Otherwise the two hops log in different formats and the
    aggregator can't join them."""
    import inspect

    from recognition.worker import scan_worker as scan_worker_mod

    src = inspect.getsource(scan_worker_mod._main)
    assert "configure_logging" in src, (
        "scan_worker._main() must call configure_logging() from api.logging_config "
        "so worker logs use the same structured JSON + correlation filter as the API."
    )


def test_scan_worker_logging_emits_correlation_field() -> None:
    """End-to-end: after configure_logging runs, a logger.info() inside the
    'recognition.*' namespace produces a LogRecord whose correlation_id
    attribute reflects the bound contextvar."""
    from api.logging_config import configure_logging

    configure_logging("INFO")
    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    handler = _CaptureHandler(level=logging.INFO)
    logging.getLogger().addHandler(handler)

    bound_id = "req-worker-test-777"
    token = _correlation_id_var.set(bound_id)
    try:
        logging.getLogger("recognition.application.test").info("hello")
        matches = [r for r in captured if r.message == "hello"]
        assert matches, "expected a recognition.* log record"
        assert getattr(matches[0], "correlation_id", None) == bound_id
    finally:
        _correlation_id_var.reset(token)
        logging.getLogger().removeHandler(handler)
