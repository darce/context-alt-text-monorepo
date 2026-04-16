from __future__ import annotations

from typing import Any

OPEN_HANDOFF_SECTIONS = "findings_open,blockers_open,actions_pending"
REVIEW_READY_STATE_SECTIONS = "identity,tests_recent"
GLOBAL_CONTEXT_SECTIONS = "blockers_open,actions_pending,findings_open,decisions_recent,tests_recent"
REVIEW_READY_TEST_LIMIT = 4


def active_task_identity_kwargs() -> dict[str, Any]:
    return {"sections": "identity"}


def open_handoff_items_kwargs(task_ref: str) -> dict[str, Any]:
    return {
        "task_ref": task_ref,
        "sections": OPEN_HANDOFF_SECTIONS,
        "top_n_blockers": 500,
        "top_n_actions": 500,
        "top_n_findings": 500,
    }


def review_ready_state_kwargs(task_ref: str) -> dict[str, Any]:
    return {
        "task_ref": task_ref,
        "sections": REVIEW_READY_STATE_SECTIONS,
        "detail": "summary",
        "top_n_tests": REVIEW_READY_TEST_LIMIT,
    }


def global_context_kwargs(task_ref: str, *, limit: int) -> dict[str, Any]:
    return {
        "task_ref": task_ref,
        "sections": GLOBAL_CONTEXT_SECTIONS,
        "top_n_blockers": limit,
        "top_n_actions": limit,
        "top_n_decisions": limit,
        "top_n_tests": limit,
        "top_n_findings": limit,
    }


def hot_state_metric_kwargs(task_ref: str, *, limits: dict[str, int]) -> dict[str, Any]:
    return {
        "task_ref": task_ref,
        "top_n_blockers": limits["blockers"],
        "top_n_actions": limits["actions"],
        "top_n_decisions": limits["decisions"],
        "top_n_tests": limits["tests"],
        "top_n_findings": limits["findings"],
    }
