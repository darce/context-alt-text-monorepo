from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_handoff_mcp import (
    get_handoff_state,
    get_review_findings_summary,
    handoff_close_check,
)
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.runtime import configure_runtime


BOUNDARY_PREFIXES = (
    "apps/",
    "packages/agent-handoff-mcp/src/",
    "packages/shared-contracts/schemas/",
)
CONTRACT_PREFIXES = (
    "docs/agentic/contracts/",
    "packages/shared-contracts/",
)
CONTRACT_CHECKLIST_PATH = "docs/agentic/rules/contract-change-checklist.md"


@dataclass(frozen=True)
class ReviewReadyResult:
    ready: bool
    task_ref: str
    base_ref: str
    base_sha: str
    open_findings: int
    open_blockers: int
    current_task_in_sync: bool
    tests_recent_count: int
    has_test_evidence: bool
    contract_violation: bool
    boundary_files: list[str]
    contract_files: list[str]
    reasons: list[str]


def _run_git(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _configure_runtime(orchestrator_root: Path) -> None:
    configure_runtime(
        RuntimeConfig.for_workspace(
            orchestrator_root,
            state_dir=orchestrator_root / ".task-state",
            current_task_path=orchestrator_root / "CURRENT_TASK.md",
            exports_dir=orchestrator_root / ".task-state" / "exports",
        )
    )


def _load_ok_payload(name: str, payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not data.get("ok"):
        error = data.get("error") or "unknown error"
        raise RuntimeError(f"MCP query failed: {name}: {error}")
    return data


def evaluate_review_ready(
    *,
    task_ref: str,
    base_ref: str,
    base_sha: str,
    changed_files: list[str],
    review: dict[str, Any],
    state: dict[str, Any],
    close: dict[str, Any],
) -> ReviewReadyResult:
    boundary_files = [path for path in changed_files if path.startswith(BOUNDARY_PREFIXES)]
    contract_files = [
        path
        for path in changed_files
        if path.startswith(CONTRACT_PREFIXES) or path == CONTRACT_CHECKLIST_PATH
    ]

    open_findings = int(review.get("counts", {}).get("status", {}).get("open", 0))
    open_blockers = int(close.get("checks", {}).get("open_blockers", {}).get("count", 0))
    current_task_in_sync = bool(
        close.get("checks", {}).get("current_task_sync", {}).get("is_in_sync")
    )
    tests_recent = state.get("tests_recent", []) or []
    has_test_evidence = len(tests_recent) > 0
    contract_violation = bool(boundary_files and not contract_files)

    reasons: list[str] = []
    if open_findings:
        reasons.append(f"{open_findings} open review finding(s)")
    if open_blockers:
        reasons.append(f"{open_blockers} open blocker(s)")
    if not current_task_in_sync:
        reasons.append("CURRENT_TASK.md is out of sync with handoff state")
    if not has_test_evidence:
        reasons.append("no recorded test evidence in handoff state")
    if contract_violation:
        reasons.append("boundary-touching files changed without contract/checklist co-change")

    return ReviewReadyResult(
        ready=not reasons,
        task_ref=state.get("task_ref") or review.get("task_ref") or task_ref,
        base_ref=base_ref,
        base_sha=base_sha,
        open_findings=open_findings,
        open_blockers=open_blockers,
        current_task_in_sync=current_task_in_sync,
        tests_recent_count=len(tests_recent),
        has_test_evidence=has_test_evidence,
        contract_violation=contract_violation,
        boundary_files=boundary_files,
        contract_files=contract_files,
        reasons=reasons,
    )


def render_review_ready(result: ReviewReadyResult) -> str:
    lines = [
        f"REVIEW READY: {'READY' if result.ready else 'NOT READY'}",
        f"Task: {result.task_ref}",
        f"Base ref: {result.base_ref} ({result.base_sha[:12]})",
        f"Open findings: {result.open_findings}",
        f"Open blockers: {result.open_blockers}",
        f"CURRENT_TASK sync: {'ok' if result.current_task_in_sync else 'stale'}",
        "Test evidence: "
        f"{'present' if result.has_test_evidence else 'missing'} "
        f"({result.tests_recent_count} recent record(s))",
        f"Contract co-change: {'ok' if not result.contract_violation else 'missing'}",
    ]
    if result.boundary_files:
        lines.append("Boundary files:")
        lines.extend(f"- {path}" for path in result.boundary_files)
    if result.contract_files:
        lines.append("Contract files:")
        lines.extend(f"- {path}" for path in result.contract_files)
    if result.reasons:
        lines.append("Reasons:")
        lines.extend(f"- {reason}" for reason in result.reasons)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orchestrator-root", required=True)
    parser.add_argument("--worktree-root", required=True)
    parser.add_argument("--task-ref", required=True)
    parser.add_argument("--review-base", required=True)
    args = parser.parse_args()

    orchestrator_root = Path(args.orchestrator_root).resolve()
    worktree_root = Path(args.worktree_root).resolve()

    _configure_runtime(orchestrator_root)

    try:
        base_sha = _run_git("merge-base", args.review_base, "HEAD", cwd=worktree_root)
    except subprocess.CalledProcessError:
        print(
            f"REVIEW_BASE '{args.review_base}' does not resolve to a merge-base from {worktree_root}.",
            file=sys.stderr,
        )
        return 1

    changed = _run_git("diff", "--name-only", f"{base_sha}..HEAD", cwd=worktree_root)
    changed_files = [line for line in changed.splitlines() if line.strip()]

    try:
        review = _load_ok_payload(
            "get_review_findings_summary",
            get_review_findings_summary(task_ref=args.task_ref),
        )
        state = _load_ok_payload(
            "get_handoff_state",
            get_handoff_state(task_ref=args.task_ref),
        )
        close = _load_ok_payload(
            "handoff_close_check",
            handoff_close_check(task_ref=args.task_ref),
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    result = evaluate_review_ready(
        task_ref=args.task_ref,
        base_ref=args.review_base,
        base_sha=base_sha,
        changed_files=changed_files,
        review=review,
        state=state,
        close=close,
    )
    print(render_review_ready(result))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
