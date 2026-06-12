"""Unit tests for worker-published embedding runtime capability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from recognition.application.scan.capability import (
    HEARTBEAT_STALE_SECONDS,
    EmbeddingRuntimeCapability,
    is_embedding_runtime_available,
    read_embedding_runtime_capability,
)


@pytest.mark.asyncio
async def test_read_embedding_runtime_capability_returns_missing_when_no_row() -> None:
    from recognition.tests.api.conftest import FakeSession, FakeSessionResult

    session = FakeSession()
    session.queue_execute_result(scalar_one_or_none=None)

    capability = await read_embedding_runtime_capability(session)

    assert capability.available is False
    assert capability.reason == "capability heartbeat missing"
    assert capability.updated_at is None


def test_is_embedding_runtime_available_rejects_stale_heartbeat() -> None:
    updated_at = datetime.now(tz=UTC) - timedelta(seconds=HEARTBEAT_STALE_SECONDS + 5)
    capability = EmbeddingRuntimeCapability(
        available=True,
        reason=None,
        updated_at=updated_at,
        heartbeat_age_seconds=HEARTBEAT_STALE_SECONDS + 5,
    )

    assert is_embedding_runtime_available(capability) is False


@pytest.mark.asyncio
async def test_worker_probe_publish_retries_runtime_before_heartbeat() -> None:
    from recognition.worker.scan_worker import ScanWorker

    worker = object.__new__(ScanWorker)
    worker._ensure_embedding_runtime = AsyncMock()  # type: ignore[attr-defined]
    worker._heartbeat_embedding_runtime_capability = AsyncMock()  # type: ignore[attr-defined]

    await worker._probe_and_publish_embedding_runtime_capability()

    worker._ensure_embedding_runtime.assert_awaited_once()
    worker._heartbeat_embedding_runtime_capability.assert_awaited_once()
