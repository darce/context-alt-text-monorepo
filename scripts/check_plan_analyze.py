#!/usr/bin/env python3
"""Verify that a planning artifact has a prior `plan-analyze` triage run.

The gate passes when at least one recorded review finding for the target
document has both:
  - ``session`` beginning with ``plan-analyze-``
  - ``file_path`` equal to the repo-relative path of the target document

The lookup uses ``list_review_findings(review_mode="planning")`` and filters
the returned rows in Python, because the review-findings API does not expose
``session`` or ``file_path`` as server-side query parameters.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_handoff_state,
    list_review_findings,
)

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


def _is_plan_analyze_finding_for(finding: Any, relative_doc: str) -> bool:
    if not isinstance(finding, dict):
        return False
    session = finding.get("session")
    file_path = finding.get("file_path")
    if not isinstance(session, str) or not session.startswith(PLAN_ANALYZE_PREFIX):
        return False
    if not isinstance(file_path, str) or file_path != relative_doc:
        return False
    return True


def check_plan_analyze(
    *,
    doc_path: str,
    repo_root: Path = REPO_ROOT,
    task_ref: str | None = None,
    runtime_factory: Callable[[Path], RuntimeConfig] = RuntimeConfig.for_repo,
    configure_runtime_fn: Callable[[RuntimeConfig], Any] = configure_runtime,
    get_handoff_state_fn: Callable[..., dict[str, Any]] = get_handoff_state,
    list_review_findings_fn: Callable[..., dict[str, Any]] = list_review_findings,
) -> tuple[int, str]:
    relative_doc = _normalize_doc_path(repo_root, doc_path)
    try:
        configure_runtime_fn(runtime_factory(repo_root))
        resolved_task_ref = task_ref or _active_task_ref(get_handoff_state_fn(sections="identity", detail="summary"))
        kwargs: dict[str, Any] = {"review_mode": "planning", "limit": 500}
        if resolved_task_ref is not None:
            kwargs["task_ref"] = resolved_task_ref
        result = list_review_findings_fn(**kwargs)
    except Exception as exc:  # pragma: no cover - exercised via tests with stub failures
        return 1, f"plan-analyze gate: ERROR - {exc}"

    if not result.get("ok"):
        error = ((result.get("data") or {}).get("error")) if isinstance(result.get("data"), dict) else None
        return 1, f"plan-analyze gate: ERROR - {error or 'unable to query review findings'}"

    findings = ((result.get("data") or {}).get("findings")) if isinstance(result.get("data"), dict) else None
    matching = [f for f in (findings or []) if _is_plan_analyze_finding_for(f, relative_doc)]
    if matching:
        return 0, f"plan-analyze gate: PASS ({len(matching)} findings for {relative_doc})"
    return 2, f"plan-analyze gate: MISSING - run `make plan-analyze DOC={relative_doc}` before plan-review."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--doc", required=True, help="Planning document path to verify.")
    parser.add_argument("--task-ref", help="Optional task_ref to scope the findings lookup.")
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
