"""
Run/event persistence primitives for the regression harness.

This module provides a light-weight context object for emitting `recognition_events` rows tied to a `recognition_runs`
record, without requiring every call site to construct ORM models directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RecognitionEvent, RecognitionRun
from recognition.shared.ids import parse_optional_uuid


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
        """Add a `recognition_events` row to the current session.

        Args:
            event_type: Event type string (e.g. "assignment_decision", "cluster_created").
            timestamp: Optional explicit timestamp; defaults to DB/server time.
            identity_id: Optional identity UUID (string or UUID).
            cluster_id: Optional cluster UUID (string or UUID).
            source_cluster_id: Optional source cluster UUID.
            target_cluster_id: Optional target cluster UUID.
            payload: JSON payload for the event.
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
        self.session.add(event)


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
        status="running",
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
