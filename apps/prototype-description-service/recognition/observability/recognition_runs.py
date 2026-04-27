"""
Run/event persistence primitives for the regression harness.

This module provides a light-weight context object for emitting `recognition_events` rows tied to a `recognition_runs`
record, without requiring every call site to construct ORM models directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RecognitionEvent, RecognitionRun
from db.tenant_context import enable_rls_bypass, set_tenant_context
from recognition.domain.job import JobStatus
from recognition.shared.ids import parse_optional_uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecognitionRunContext:
    """Context for emitting events for a single recognition run.

    Notes:
        `add_event()` is synchronous (no `await`) so it can be called from both sync and async code paths. It should only
        add ORM rows to the session; flushing/committing is handled by the surrounding transaction.
    """

    session: AsyncSession
    tenant_id: UUID
    run_id: UUID
    buffer_events: bool = False
    _pending_events: list[RecognitionEvent] = field(default_factory=list, init=False, repr=False)

    def add_event(
        self,
        *,
        event_type: str,
        timestamp: datetime | None = None,
        identity_id: str | UUID | None = None,
        cluster_id: str | UUID | None = None,
        source_cluster_id: str | UUID | None = None,
        target_cluster_id: str | UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Add a `recognition_events` row to the current session or pending buffer.

        When `buffer_events` is True the event is held in `_pending_events` and
        will be persisted by the next `flush_pending_events()` call in a separate
        short-lived session.  This decouples observability writes from the main
        clustering transaction so that an RLS or other DB error in observability
        cannot abort the clustering transaction (stretch goal).

        When `buffer_events` is False (default) the event is added directly to
        `self.session` and will be flushed/committed by the surrounding transaction.
        """
        identity_uuid = parse_optional_uuid(identity_id)
        cluster_uuid = parse_optional_uuid(cluster_id)
        source_cluster_uuid = parse_optional_uuid(source_cluster_id)
        target_cluster_uuid = parse_optional_uuid(target_cluster_id)

        event = RecognitionEvent(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            event_type=event_type,
            identity_id=identity_uuid,
            cluster_id=cluster_uuid,
            source_cluster_id=source_cluster_uuid,
            target_cluster_id=target_cluster_uuid,
            payload=dict(payload or {}),
        )
        if timestamp is not None:
            event.timestamp = timestamp
        if self.buffer_events:
            self._pending_events.append(event)
        else:
            self.session.add(event)

    async def flush_pending_events(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Persist buffered events; no-op if no events are pending.

        When `session_factory` is provided the events are written in a fresh
        short-lived session that is committed and closed independently of the
        main clustering session.  This ensures that an observability failure
        cannot roll back committed clustering data.

        When `session_factory` is None the events are added to `self.session`
        and flushed inline (fallback path for tests or callers without a factory).
        """
        if not self._pending_events:
            return
        events, self._pending_events = self._pending_events, []
        try:
            if session_factory is not None:
                async with session_factory() as obs_session:
                    await set_tenant_context(obs_session, self.tenant_id)
                    await enable_rls_bypass(obs_session)
                    for ev in events:
                        obs_session.add(ev)
                    await obs_session.commit()
            else:
                for ev in events:
                    self.session.add(ev)
                await self.session.flush()
        except Exception:
            logger.warning(
                "[observability] failed to flush %d events for run %s; events discarded",
                len(events),
                self.run_id,
            )


async def create_recognition_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    source: str | None = None,
    scan_job_id: UUID | None = None,
    clustering_job_id: UUID | None = None,
    git_sha: str | None = None,
    settings_snapshot: dict[str, object] | None = None,
    dataset_selector: dict[str, object] | None = None,
    started_at: datetime | None = None,
) -> RecognitionRunContext:
    """Create a `recognition_runs` row and return a bound run context.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID.
        source: Optional run source label (e.g. "clustering_job").
        scan_job_id: Optional scan job UUID to link.
        clustering_job_id: Optional clustering job UUID to link.
        git_sha: Optional git SHA string.
        settings_snapshot: Optional settings snapshot payload.
        dataset_selector: Optional dataset selector payload.
        started_at: Optional run start timestamp.

    Returns:
        RecognitionRunContext: Context bound to the created run.
    """
    run = RecognitionRun(
        tenant_id=tenant_id,
        status=JobStatus.RUNNING,
        source=source,
        scan_job_id=scan_job_id,
        clustering_job_id=clustering_job_id,
        git_sha=git_sha,
        settings_snapshot=dict(settings_snapshot or {}),
        dataset_selector=dict(dataset_selector or {}),
        started_at=started_at,
    )
    session.add(run)
    await session.flush()
    return RecognitionRunContext(session=session, tenant_id=tenant_id, run_id=run.id)


async def complete_recognition_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    status: str,
    completed_at: datetime | None = None,
    error_message: str | None = None,
) -> None:
    """Mark a recognition run as completed or failed.

    Args:
        session: Async SQLAlchemy session.
        run_id: Run UUID.
        status: "completed" or "failed".
        completed_at: Optional completion timestamp.
        error_message: Optional error message for failed runs.
    """
    if status not in {"completed", "failed"}:
        raise ValueError("status must be 'completed' or 'failed'")

    run = await session.get(RecognitionRun, run_id)
    if run is None:
        raise ValueError(f"RecognitionRun not found: {run_id}")

    run.status = status
    run.completed_at = completed_at
    run.error_message = error_message
    await session.flush()
