"""Domain constants and guards for scene describe runs."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class DescribeRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DescribeRunPhase(StrEnum):
    QUEUED = "queued"
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
