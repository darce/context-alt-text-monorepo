"""Tracking for cancelable jobs (in-memory placeholder)."""

from __future__ import annotations

from typing import Final

CANCELED_JOBS: Final[set[str]] = set()


def mark_canceled(job_id: str) -> None:
    CANCELED_JOBS.add(job_id)


def is_canceled(job_id: str) -> bool:
    return job_id in CANCELED_JOBS
