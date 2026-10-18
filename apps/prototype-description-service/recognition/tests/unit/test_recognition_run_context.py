"""Unit tests for RecognitionRunContext event buffering (stretch goal).

Covers the decoupled observability write path introduced to prevent an
observability failure from aborting a committed clustering transaction.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from recognition.observability.recognition_runs import RecognitionRunContext


class _FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.flushed = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


class _FakeObsSession:
    """Tracks adds and commits made by flush_pending_events."""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_add_event_buffers_when_buffer_events_true() -> None:
    """With buffer_events=True, add_event() must not call session.add()."""
    fake_session = _FakeSession()
    ctx = RecognitionRunContext(
        session=fake_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    with (
        patch("recognition.observability.recognition_runs.set_tenant_context", new_callable=AsyncMock),
        patch("recognition.observability.recognition_runs.enable_rls_bypass", new_callable=AsyncMock),
    ):
        ctx.add_event(event_type="test_event")

    assert len(fake_session.added) == 0, "session.add() must not be called when buffer_events=True"
    assert len(ctx._pending_events) == 1, "event must be appended to _pending_events"


@pytest.mark.asyncio
async def test_add_event_writes_to_session_when_buffer_events_false() -> None:
    """With buffer_events=False (default), add_event() must call session.add() directly."""
    fake_session = _FakeSession()
    ctx = RecognitionRunContext(
        session=fake_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
    )

    ctx.add_event(event_type="test_event")

    assert len(fake_session.added) == 1, "session.add() must be called when buffer_events=False"
    assert len(ctx._pending_events) == 0, "_pending_events must be empty in direct mode"


@pytest.mark.asyncio
async def test_flush_pending_events_writes_to_separate_session() -> None:
    """flush_pending_events() must write buffered events to the factory session, not self.session."""
    main_session = _FakeSession()
    obs_session = _FakeObsSession()
    factory = MagicMock(return_value=obs_session)

    tenant_id = uuid.uuid4()
    ctx = RecognitionRunContext(
        session=main_session,
        tenant_id=tenant_id,
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    with (
        patch("recognition.observability.recognition_runs.set_tenant_context", new_callable=AsyncMock) as set_ctx,
        patch("recognition.observability.recognition_runs.enable_rls_bypass", new_callable=AsyncMock) as bypass,
    ):
        ctx.add_event(event_type="cluster_created")
        ctx.add_event(event_type="assignment_decision")

        await ctx.flush_pending_events(session_factory=factory)

        # Context must be set in the new session
        assert set_ctx.call_count == 1
        assert bypass.call_count == 1
        passed_tenant = (
            set_ctx.call_args.args[1] if set_ctx.call_args.args else set_ctx.call_args.kwargs.get("tenant_id")
        )
        assert passed_tenant == tenant_id

    # Events were written to the obs_session, not the main session
    assert len(obs_session.added) == 2, "both events must be added to obs_session"
    assert obs_session.committed, "obs_session must be committed"
    assert len(main_session.added) == 0, "main session must not receive buffered events"


@pytest.mark.asyncio
async def test_flush_pending_events_clears_buffer_after_write() -> None:
    """_pending_events must be empty after a successful flush."""
    fake_session = _FakeSession()
    obs_session = _FakeObsSession()
    factory = MagicMock(return_value=obs_session)

    ctx = RecognitionRunContext(
        session=fake_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    with (
        patch("recognition.observability.recognition_runs.set_tenant_context", new_callable=AsyncMock),
        patch("recognition.observability.recognition_runs.enable_rls_bypass", new_callable=AsyncMock),
    ):
        ctx.add_event(event_type="test_event")
        await ctx.flush_pending_events(session_factory=factory)

    assert ctx._pending_events == [], "buffer must be cleared after flush"


@pytest.mark.asyncio
async def test_flush_pending_events_noop_when_empty() -> None:
    """flush_pending_events() must be a no-op when there are no pending events."""
    fake_session = _FakeSession()
    factory = MagicMock()

    ctx = RecognitionRunContext(
        session=fake_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    # No events added; flush should not call the factory at all
    await ctx.flush_pending_events(session_factory=factory)

    factory.assert_not_called()


@pytest.mark.asyncio
async def test_flush_pending_events_fallback_to_main_session_without_factory() -> None:
    """Without a session_factory, buffered events are added to self.session and flushed inline."""
    main_session = _FakeSession()
    ctx = RecognitionRunContext(
        session=main_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    with (
        patch("recognition.observability.recognition_runs.set_tenant_context", new_callable=AsyncMock),
        patch("recognition.observability.recognition_runs.enable_rls_bypass", new_callable=AsyncMock),
    ):
        ctx.add_event(event_type="graph_run")
        await ctx.flush_pending_events(session_factory=None)

    assert len(main_session.added) == 1, "event should fall back to main session"
    assert main_session.flushed == 1, "main session should be flushed once"


@pytest.mark.asyncio
async def test_flush_pending_events_discards_events_on_failure() -> None:
    """flush_pending_events() must swallow exceptions and discard unwritable events."""
    fake_session = _FakeSession()

    class _FailingSession:
        def add(self, obj) -> None:  # noqa: ANN001
            pass

        async def commit(self) -> None:
            raise RuntimeError("DB failure")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    factory = MagicMock(return_value=_FailingSession())
    ctx = RecognitionRunContext(
        session=fake_session,
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        buffer_events=True,
    )

    with (
        patch("recognition.observability.recognition_runs.set_tenant_context", new_callable=AsyncMock),
        patch("recognition.observability.recognition_runs.enable_rls_bypass", new_callable=AsyncMock),
    ):
        ctx.add_event(event_type="test_event")
        # Must not raise despite the DB failure
        await ctx.flush_pending_events(session_factory=factory)

    # Buffer must be cleared (events discarded)
    assert ctx._pending_events == [], "failed events must be discarded"
