#!/usr/bin/env python3
"""Verify that a planning artifact has a prior `plan-analyze` triage run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_handoff_state, review_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN_ANALYZE_PREFIX = "plan-analyze-"


def _normalize_doc_path(repo_root: Path, doc_path: str) -> str:
    candidate = Path(doc_path)
    resolved = (candidate if candidate.is_absolute() else repo_root / candidate).resolve()
    try:
        return resolved.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"document must live under {repo_root}") from exc


def _active_task_ref(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    active = data.get("active")
    if not isinstance(active, dict):
        return None
    task_ref = active.get("task_ref")
    return task_ref if isinstance(task_ref, str) and task_ref else None


def check_plan_analyze(
    *,
    doc_path: str,
    repo_root: Path = REPO_ROOT,
    task_ref: str | None = None,
    runtime_factory: Callable[[Path], RuntimeConfig] = RuntimeConfig.for_repo,
    configure_runtime_fn: Callable[[RuntimeConfig], Any] = configure_runtime,
    get_handoff_state_fn: Callable[..., dict[str, Any]] = get_handoff_state,
    review_runs_fn: Callable[..., dict[str, Any]] = review_runs,
) -> tuple[int, str]:
    relative_doc = _normalize_doc_path(repo_root, doc_path)
    try:
        configure_runtime_fn(runtime_factory(repo_root))
        resolved_task_ref = task_ref or _active_task_ref(get_handoff_state_fn(sections="identity", detail="summary"))
        review_payload: dict[str, Any] = {
            "operation": "list",
            "subject_path": relative_doc,
            "review_mode": "planning",
            "limit": 100,
        }
        if resolved_task_ref is not None:
            review_payload["task_ref"] = resolved_task_ref
        result = review_runs_fn(review=review_payload)
    except Exception as exc:  # pragma: no cover - exercised via tests with stub failures
        return 1, f"plan-analyze gate: ERROR - {exc}"

    if not result.get("ok"):
        error = ((result.get("data") or {}).get("error")) if isinstance(result.get("data"), dict) else None
        return 1, f"plan-analyze gate: ERROR - {error or 'unable to query review runs'}"

    runs = ((result.get("data") or {}).get("runs")) if isinstance(result.get("data"), dict) else None
    matching_runs = [
        run for run in (runs or []) if isinstance(run, dict) and str(run.get("session", "")).startswith(PLAN_ANALYZE_PREFIX)
    ]
    if matching_runs:
        return 0, f"plan-analyze gate: PASS ({len(matching_runs)} runs for {relative_doc})"
    return 2, f"plan-analyze gate: MISSING - run `make plan-analyze DOC={relative_doc}` before plan-review."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", required=True, help="Planning document path to verify.")
    parser.add_argument("--task-ref", help="Optional task_ref to scope the review-run lookup.")
    args = parser.parse_args(argv)

    try:
        exit_code, message = check_plan_analyze(doc_path=args.doc, task_ref=args.task_ref)
    except ValueError as exc:
        print(f"plan-analyze gate: ERROR - {exc}", file=sys.stderr)
        return 1

    stream = sys.stdout if exit_code in {0, 2} else sys.stderr
    print(message, file=stream)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
