#!/usr/bin/env python3
"""PostToolUse hook: record file touches after Edit/Write tool calls.

Reads the Claude Code PostToolUse JSON payload from stdin, extracts the
file path, determines the change kind (edit vs add), and calls
record_file_touch via the Python API.

Edit events always record change_kind='edit'. Write events check whether
the file was already tracked by git: tracked files record 'edit',
untracked files record 'add'. File deletion is out of scope for this
hook surface.

Best-effort: exits 0 on any error so file-touch recording never blocks
the user's editing flow.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _git_repo_root() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return os.environ.get("CLAUDE_PROJECT_DIR", "")


def _to_monorepo_relative(abs_path: str, repo_root: str) -> str:
    if not repo_root or not abs_path:
        return ""
    try:
        return os.path.relpath(abs_path, repo_root)
    except ValueError:
        return ""


def _is_tracked_by_git(abs_path: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--error-unmatch", abs_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0
    except Exception:
        return True


def _determine_change_kind(tool_name: str, abs_path: str) -> str:
    if tool_name == "Edit":
        return "edit"
    if _is_tracked_by_git(abs_path):
        return "edit"
    return "add"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        return 0

    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    repo_root = _git_repo_root()
    rel_path = _to_monorepo_relative(file_path, repo_root)
    if not rel_path or rel_path.startswith(".."):
        return 0

    change_kind = _determine_change_kind(tool_name, file_path)

    try:
        env = os.environ.copy()
        src_path = os.path.join(repo_root, "packages", "agent-handoff-mcp", "src")
        env["PYTHONPATH"] = src_path + (os.pathsep + env.get("PYTHONPATH", ""))
        subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_file_touch; "
                    f"configure_runtime(RuntimeConfig.for_repo(Path({repo_root!r}))); "
                    f"record_file_touch(file_path={rel_path!r}, change_kind={change_kind!r})"
                ),
            ],
            capture_output=True,
            timeout=10,
            env=env,
        )
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
