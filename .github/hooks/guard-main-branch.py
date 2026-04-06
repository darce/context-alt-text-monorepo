#!/usr/bin/env python3
"""PreToolUse hook: block code-file edits on main/master in the VS Code harness."""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


_CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".php", ".sql", ".sh", ".css", ".scss"}
_PROTECTED_ROOTS = ("apps/", "packages/")
_EDIT_TOOLS = {"apply_patch", "create_file"}


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


def _to_repo_relative(path: str, repo_root: str) -> str:
    normalized_path = path.strip()
    if repo_root and normalized_path.startswith(repo_root + "/"):
        return normalized_path[len(repo_root) + 1 :]
    return normalized_path


def _extract_candidate_paths(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    if tool_name == "create_file":
        file_path = tool_input.get("filePath") or tool_input.get("file_path")
        return [str(file_path)] if isinstance(file_path, str) and file_path.strip() else []

    if tool_name != "apply_patch":
        return []

    patch_input = tool_input.get("input")
    if not isinstance(patch_input, str) or not patch_input.strip():
        return []

    paths: list[str] = []
    for line in patch_input.splitlines():
        if not line.startswith("*** ") or " File: " not in line:
            continue
        _, raw_path = line.split(" File: ", 1)
        parsed_path = raw_path.split(" -> ", 1)[0].strip()
        if parsed_path:
            paths.append(parsed_path)
    return paths


def _is_protected_code_path(path: str) -> bool:
    if not path.startswith(_PROTECTED_ROOTS):
        return False
    return Path(path).suffix in _CODE_EXTENSIONS


def _check_file_edit(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    branch: str,
    repo_root: str,
) -> tuple[str, list[str]] | None:
    if tool_name not in _EDIT_TOOLS:
        return None
    if branch not in {"main", "master"}:
        return None

    blocked_paths: list[str] = []
    for raw_path in _extract_candidate_paths(tool_name, tool_input):
        relative_path = _to_repo_relative(raw_path, repo_root)
        if _is_protected_code_path(relative_path):
            blocked_paths.append(relative_path)

    if not blocked_paths:
        return None
    return branch, blocked_paths


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
        "Docs, configs, markdown, settings, and Makefiles remain allowed on main.\n"
        "See: docs/agentic/rules/development-workflow.md#branch-isolation-protocol-mandatory"
    )


def _log_telemetry(tool_name: str, blocked_paths: list[str], branch: str) -> None:
    try:
        state_dir = Path(".task-state")
        state_dir.mkdir(exist_ok=True)
        record = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "tool": tool_name,
            "branch": branch,
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
    result = _check_file_edit(tool_name, tool_input, branch=branch, repo_root=repo_root)
    if result is None:
        sys.exit(0)

    resolved_branch, blocked_paths = result
    _log_telemetry(tool_name, blocked_paths, resolved_branch)
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


if __name__ == "__main__":
    main()