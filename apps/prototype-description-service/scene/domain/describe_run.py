"""Domain constants and guards for scene describe runs."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from scene.domain.description import DescriptionResultTier


class DescribeRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DescribeRunPhase(StrEnum):
    QUEUED = "queued"
    WARMING = "warming"
    DESCRIBING = "describing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DescribeItemStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunKind(StrEnum):
    """Bulk multi-item runs vs single-image async supersede jobs (VLM-5)."""

    BULK = "bulk"
    SINGLE = "single"


class DescribeJobStatus(StrEnum):
    """Wire-facing async poll status projected from a DescribeRunItem (VLM-5).

    Canonical home for the enum formerly defined on the volatile in-memory store
    (sr-007). Values stay wire-identical to the poll contract.
    """

    QUEUED = "queued"
    RUNNING = "running"
    PROVISIONAL = "provisional"
    FINAL = "final"
    DEGRADED = "degraded"
    FAILED = "failed"


TERMINAL_ITEM_STATUSES = {
    DescribeItemStatus.COMPLETED,
    DescribeItemStatus.FAILED,
    DescribeItemStatus.SKIPPED,
}
TERMINAL_RUN_STATUSES = {
    DescribeRunStatus.COMPLETED,
    DescribeRunStatus.COMPLETED_WITH_ERRORS,
    DescribeRunStatus.FAILED,
    DescribeRunStatus.CANCELLED,
}

# Default retention for terminal single-run async jobs (design (d)).
DEFAULT_ASYNC_JOB_RETENTION_HOURS = 24


def describe_run_max_items() -> int:
    return int(os.environ.get("ACX_DESCRIBE_RUN_MAX_ITEMS", "200"))


@dataclass(frozen=True)
class DescribeRunRequest:
    tenant_id: object
    media_ids: Sequence[int]
    max_items: int

    def validate(self) -> None:
        total = len(self.media_ids)
        if total < 1:
            raise ValueError("describe run requires at least one media item")
        if total > self.max_items:
            raise ValueError(f"describe run accepts at most {self.max_items} media items")


def compute_eta_seconds(run, *, now: datetime | None = None) -> float | None:
    """Honest ETA for an in-flight run.

    Returns ``None`` unless the run has started, has recorded at least one
    terminal item, and is not itself terminal — then ``remaining / rate`` where
    ``rate = done / elapsed``. Any degenerate input (no elapsed time, zero rate)
    yields ``None`` rather than a fabricated estimate. (S7-01)
    """
    started = getattr(run, "started_at", None)
    if started is None:
        return None
    if DescribeRunStatus(run.status) in TERMINAL_RUN_STATUSES:
        return None
    done = run.completed_items + run.failed_items + run.skipped_items
    if done <= 0:
        return None
    now = now or datetime.now(tz=UTC)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    elapsed = (now - started).total_seconds()
    if elapsed <= 0:
        return None
    rate = done / elapsed
    if rate <= 0:
        return None
    remaining = max(run.total_items - done, 0)
    return remaining / rate


def terminal_run_status(*, completed: int, failed: int, skipped: int, cancel_requested: bool) -> DescribeRunStatus:
    """Map terminal item outcomes to a run's terminal status.

    Single source of truth shared by the live recompute path and startup
    reclaim so both agree on the mapping (S5-01):
    - cancel requested -> CANCELLED (a cancel that lands mid-run wins even if
      some items completed first);
    - only skips, nothing completed -> CANCELLED (cancel-before-run);
    - any failure -> COMPLETED_WITH_ERRORS;
    - otherwise -> COMPLETED.
    """
    if cancel_requested:
        return DescribeRunStatus.CANCELLED
    if skipped and not failed and completed == 0:
        return DescribeRunStatus.CANCELLED
    if failed:
        return DescribeRunStatus.COMPLETED_WITH_ERRORS
    return DescribeRunStatus.COMPLETED


def phase_for_status(status: DescribeRunStatus) -> DescribeRunPhase:
    if status == DescribeRunStatus.PENDING:
        return DescribeRunPhase.QUEUED
    if status == DescribeRunStatus.RUNNING:
        return DescribeRunPhase.DESCRIBING
    if status in {DescribeRunStatus.COMPLETED, DescribeRunStatus.COMPLETED_WITH_ERRORS}:
        return DescribeRunPhase.COMPLETE
    if status == DescribeRunStatus.CANCELLED:
        return DescribeRunPhase.CANCELLED
    return DescribeRunPhase.FAILED


def _tier_value(item: Any) -> str | None:
    tier = getattr(item, "tier", None)
    if tier is None:
        return None
    return tier.value if isinstance(tier, DescriptionResultTier) else str(tier)


def describe_job_status(item: Any) -> DescribeJobStatus:
    """Pure, total projection of item row state → async poll status (design (g)).

    Maps every ``DescribeItemStatus`` member, including ``skipped`` → ``failed``
    (error via :func:`describe_job_error`). Never raises on a well-formed item.
    """
    status = DescribeItemStatus(item.status)
    if status is DescribeItemStatus.QUEUED:
        return DescribeJobStatus.QUEUED
    if status is DescribeItemStatus.RUNNING:
        if getattr(item, "visual_facts", None) is not None:
            return DescribeJobStatus.PROVISIONAL
        return DescribeJobStatus.RUNNING
    if status is DescribeItemStatus.COMPLETED:
        if _tier_value(item) == DescriptionResultTier.FINAL_GPU:
            return DescribeJobStatus.FINAL
        # completed + provisional_cpu (+ last_error on reclaim/degrade) → degraded
        return DescribeJobStatus.DEGRADED
    if status is DescribeItemStatus.FAILED:
        return DescribeJobStatus.FAILED
    if status is DescribeItemStatus.SKIPPED:
        # External cancel of a single run is not a bulk surface; map to failed
        # so poll handlers never see an unmapped status (design (g)).
        return DescribeJobStatus.FAILED
    # Exhaustiveness guard — new enum members must extend this projection.
    raise ValueError(f"unhandled DescribeItemStatus: {status!r}")


def describe_job_error(item: Any) -> str | None:
    """Wire ``error`` field for the poll projection paired with :func:`describe_job_status`."""
    status = DescribeItemStatus(item.status)
    if status is DescribeItemStatus.SKIPPED:
        return "cancelled"
    job_status = describe_job_status(item)
    if job_status in {DescribeJobStatus.FAILED, DescribeJobStatus.DEGRADED}:
        return getattr(item, "last_error", None)
    return None


def async_job_retention_hours() -> int:
    return int(os.environ.get("ACX_ASYNC_JOB_RETENTION_HOURS", str(DEFAULT_ASYNC_JOB_RETENTION_HOURS)))
