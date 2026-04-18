#!/usr/bin/env python3
"""PreToolUse hook: block code-file edits on main/master in the VS Code harness."""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

HELPER_DIR = Path(__file__).resolve().parents[2] / "scripts" / "hooks"
if str(HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(HELPER_DIR))

from _harness_protocol import (  # noqa: E402
    HarnessContractMissingError,
    load_branch_isolation_policy,
)
from _branch_isolation_guard import (  # noqa: E402
    check_file_edit as _check_file_edit,
    extract_candidate_paths as _extract_candidate_paths,
    find_dirty_protected_paths as _check_dirty_protected_paths,
)


_PROTECTED_BRANCHES = {"main", "master"}


def _run_git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _repo_root() -> str:
    return _run_git("rev-parse", "--show-toplevel")


def _current_branch() -> str:
    return _run_git("branch", "--show-current")


def _build_reason(branch: str, blocked_paths: list[str]) -> str:
    rendered_paths = "\n".join(f"  - {path}" for path in blocked_paths)
    return (
        "BLOCKED: Code file edits are not allowed on the main branch.\n\n"
        f"Branch: {branch}\n"
        "Files:\n"
        f"{rendered_paths}\n\n"
        "Create a feature branch first:\n"
        "  git checkout -b feature/<task-id>-<slug>\n\n"
        "If you already have dirty code changes on main, move them to a feature branch or stash them before continuing.\n\n"
        "Isolation options:\n"
        "  1. Feature branch for single-agent work\n"
        "  2. Worktree isolation for delegated subtasks\n"
        "  3. Lane orchestration for multi-agent parallel work\n\n"
        "Docs, markdown, and permitted planning surfaces remain allowed on main.\n"
        "See: docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory"
    )


def _build_dirty_reason(branch: str, dirty_paths: list[str]) -> str:
    rendered_paths = "\n".join(f"  - {path}" for path in dirty_paths)
    return (
        "BLOCKED: Protected code files are already dirty on the main branch.\n\n"
        f"Branch: {branch}\n"
        "Dirty files:\n"
        f"{rendered_paths}\n\n"
        "Move the work onto a feature branch or stash it before making more edits.\n\n"
        "Recommended recovery:\n"
        "  1. git checkout -b feature/<task-id>-<slug>\n"
        "  2. keep the dirty changes on that branch, or stash them intentionally\n"
        "  3. return to main only after the protected paths are clean again\n\n"
        "See: docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory"
    )


def _log_telemetry(tool_name: str, blocked_paths: list[str], branch: str, *, outcome: str) -> None:
    try:
        state_dir = Path(".task-state")
        state_dir.mkdir(exist_ok=True)
        record = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "tool": tool_name,
            "branch": branch,
            "outcome": outcome,
            "paths": blocked_paths,
        }
        with (state_dir / "branch_isolation_guard.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError:
        pass


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("toolName") or data.get("tool_name") or ""
    tool_input = data.get("toolInput") or data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        sys.exit(0)

    branch = _current_branch()
    repo_root = _repo_root()
    workspace_root = Path(repo_root or Path.cwd())
    try:
        policy = load_branch_isolation_policy(workspace_root)
    except HarnessContractMissingError as exc:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "block",
                        "permissionDecisionReason": str(exc),
                    }
                }
            )
        )
        sys.exit(0)

    result = _check_file_edit(
        tool_name,
        tool_input,
        branch=branch,
        repo_root=repo_root,
        policy=policy,
        protected_branches=_PROTECTED_BRANCHES,
    )
    if result is not None:
        resolved_branch, blocked_paths = result
        _log_telemetry(tool_name, blocked_paths, resolved_branch, outcome="attempted_protected_edit")
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "block",
                        "permissionDecisionReason": _build_reason(resolved_branch, blocked_paths),
                    }
                }
            )
        )
        sys.exit(0)

    dirty_result = _check_dirty_protected_paths(
        branch=branch,
        repo_root=repo_root,
        policy=policy,
        protected_branches=_PROTECTED_BRANCHES,
    )
    if dirty_result is None:
        sys.exit(0)

    resolved_branch, dirty_paths = dirty_result
    _log_telemetry(tool_name, dirty_paths, resolved_branch, outcome="dirty_protected_main_paths")
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "block",
                    "permissionDecisionReason": _build_dirty_reason(resolved_branch, dirty_paths),
                }
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
