"""Worker-published embedding-runtime capability read by API intake and health."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.worker_capability import (
    EMBEDDING_RUNTIME_CAPABILITY,
    SCAN_WORKER_KIND,
    WorkerCapability,
)

# 3 × (poll_interval_seconds 1 × ~30s effective claim/process cycle).
HEARTBEAT_STALE_SECONDS = 90.0


@dataclass(slots=True)
class ScanWorkerCounters:
    """Cumulative scan reconcile counters published on the worker heartbeat ([OBS-05]).

    ``rows_matched`` / ``rows_new`` are re-scan MediaIdentity recycling counts,
    not assignment/unknown (FIR-6 / clustering). Always present, including zero
    ([OBS-08] silence distinguishable from health).
    """

    media_processed: int = 0
    faces_detected: int = 0
    rows_matched: int = 0
    rows_new: int = 0

    def record(self, *, detected: int, matched: int, new: int) -> None:
        self.media_processed += 1
        self.faces_detected += int(detected)
        self.rows_matched += int(matched)
        self.rows_new += int(new)

    def format_suffix(self) -> str:
        """Stable key=value suffix always including zeros."""
        return (
            f"media_processed={self.media_processed}; "
            f"faces_detected={self.faces_detected}; "
            f"rows_matched={self.rows_matched}; "
            f"rows_new={self.rows_new}"
        )


@dataclass(frozen=True, slots=True)
class EmbeddingRuntimeCapability:
    available: bool
    reason: str | None
    updated_at: datetime | None
    heartbeat_age_seconds: float | None


def is_embedding_runtime_available(capability: EmbeddingRuntimeCapability) -> bool:
    """Return True when the worker heartbeat is fresh and runtime is available."""
    if capability.updated_at is None:
        return False
    if capability.heartbeat_age_seconds is not None and capability.heartbeat_age_seconds > HEARTBEAT_STALE_SECONDS:
        return False
    return capability.available


def _heartbeat_age_seconds(updated_at: datetime | None, *, now: datetime | None = None) -> float | None:
    if updated_at is None:
        return None
    reference = now or datetime.now(tz=UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return max(0.0, (reference - updated_at).total_seconds())


async def read_embedding_runtime_capability(session: AsyncSession) -> EmbeddingRuntimeCapability:
    """Read the scan worker's embedding-runtime capability without importing models."""
    stmt = (
        select(WorkerCapability.available, WorkerCapability.reason, WorkerCapability.updated_at)
        .where(WorkerCapability.worker_kind == SCAN_WORKER_KIND)
        .where(WorkerCapability.capability == EMBEDDING_RUNTIME_CAPABILITY)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return EmbeddingRuntimeCapability(
            available=False,
            reason="capability heartbeat missing",
            updated_at=None,
            heartbeat_age_seconds=None,
        )
    available, reason, updated_at = row
    return EmbeddingRuntimeCapability(
        available=bool(available),
        reason=reason,
        updated_at=updated_at,
        heartbeat_age_seconds=_heartbeat_age_seconds(updated_at),
    )


def format_capability_reason(
    *,
    profile: str,
    available_detail: str | None = None,
    counters: ScanWorkerCounters | None = None,
) -> str:
    """Build heartbeat reason with profile + always-present counters ([OBS-05]/[OBS-08])."""
    parts: list[str] = [f"profile={profile}"]
    if available_detail:
        parts.append(available_detail)
    parts.append((counters or ScanWorkerCounters()).format_suffix())
    return "; ".join(parts)


async def publish_embedding_runtime_capability(
    session: AsyncSession,
    *,
    available: bool,
    reason: str | None,
    now: datetime | None = None,
) -> None:
    """Upsert the scan worker embedding-runtime capability heartbeat."""
    timestamp = now or datetime.now(tz=UTC)
    stmt = (
        insert(WorkerCapability)
        .values(
            worker_kind=SCAN_WORKER_KIND,
            capability=EMBEDDING_RUNTIME_CAPABILITY,
            available=available,
            reason=reason,
            updated_at=timestamp,
        )
        .on_conflict_do_update(
            index_elements=[WorkerCapability.worker_kind, WorkerCapability.capability],
            set_={
                "available": available,
                "reason": reason,
                "updated_at": timestamp,
            },
        )
    )
    await session.execute(stmt)


async def require_scan_dispatch_ready(session: AsyncSession, *, inline_processing: bool) -> None:
    """Fail fast when the scan worker process or embedding runtime is unavailable."""
    from recognition.application.tasks.scan import scan_worker_available

    if inline_processing:
        return
    if not await scan_worker_available(session):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scan worker unavailable. Start the scan worker or enable inline processing.",
        )
    capability = await read_embedding_runtime_capability(session)
    if not is_embedding_runtime_available(capability):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason": "embedding_runtime_unavailable",
                "detail": capability.reason or "embedding runtime unavailable",
            },
        )


def embedding_runtime_health_payload(capability: EmbeddingRuntimeCapability) -> dict[str, object]:
    """Shape the operator-facing /health/detailed embedding_runtime field."""
    return {
        "available": is_embedding_runtime_available(capability),
        "reason": capability.reason,
        "heartbeat_age_seconds": capability.heartbeat_age_seconds,
    }
