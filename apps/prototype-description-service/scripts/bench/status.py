"""Canonical bench status vocabulary (sr-007). Mirrors live JobStatus; no invented literals."""

from __future__ import annotations

from enum import StrEnum

from recognition.domain.job import JobStatus


class ItemPhase(StrEnum):
    INGEST = "ingest"
    ANALYZE = "analyze"


class ItemOutcome(StrEnum):
    OK = "ok"
    FAILED = "failed"


class RunPhase(StrEnum):
    INIT = "init"
    INCOMPLETE = "incomplete"
    DONE = "done"
    FAILED = "failed"


class TerminalIngest(StrEnum):
    SUCCESS = "success"


CLUSTER_SUCCESS_STATUSES: frozenset[str] = frozenset(
    {
        JobStatus.COMPLETED.value,
        JobStatus.COMPLETED_WITH_ERRORS.value,
    }
)

ANALYZE_PARTIAL_SUCCESS = JobStatus.COMPLETED_WITH_ERRORS.value
