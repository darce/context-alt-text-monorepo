#!/usr/bin/env python3
"""PreToolUse(Bash) hook: block destructive shell edits to protected paths on main.

Covers the BR-17 bypass where `sed -i`, `echo > file`, `tee`, `rm`, `python -c
"open(..., 'w')"`, `git restore`, etc. ran via the Bash tool and were never
scanned by the editor-tool-only main-branch guard.

Contract (Claude Code + VS Code harnesses):
    stdin  : JSON payload with tool_name and tool_input.command
    args   : none
    stdout : BLOCKED message when a write to a protected path is detected
    exit 0 : allow
    exit 2 : block
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Path.cwd()
    if proc.returncode != 0:
        return Path.cwd()
    return Path(proc.stdout.strip() or ".")


def _current_branch(repo_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _load_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _extract_command(payload: dict) -> str:
    tool_input = payload.get("toolInput") or payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    if not isinstance(command, str):
        return ""
    return command


def main() -> int:
    repo_root = _repo_root()
    branch = _current_branch(repo_root)
    if branch not in {"main", "master"}:
        return 0

    payload = _load_payload()
    tool_name = payload.get("toolName") or payload.get("tool_name") or ""
    if tool_name != "Bash":
        return 0

    command = _extract_command(payload)
    if not command:
        return 0

    sys.path.insert(0, str(repo_root / "scripts" / "hooks"))
    try:
        from _bash_isolation_guard import scan_bash_command
        from _harness_protocol import HarnessContractMissingError, load_branch_isolation_policy
    except ImportError as exc:
        print(f"guard-bash-main-branch: import failed — {exc}", file=sys.stderr)
        return 0

    try:
        policy = load_branch_isolation_policy(repo_root)
    except HarnessContractMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    blocked = scan_bash_command(command, repo_root, policy)
    if not blocked:
        return 0

    rendered = "\n".join(f"  - {path}" for path in blocked)
    print(
        "BLOCKED: Bash command appears to write to or delete protected paths on main.\n\n"
        f"Branch: {branch}\n"
        f"Protected paths touched by this command:\n{rendered}\n\n"
        "Use the Edit/Write tool (which has proper path semantics) or move the change\n"
        "onto a feature branch first:\n"
        "  git checkout -b feature/<task-id>-<slug>\n\n"
        "If the detection is a false positive (e.g. scanning, not writing), run the\n"
        "command outside the main worktree or set ALT_ALLOW_BASH_MAIN_WRITE=1 in the\n"
        "shell — env-bypass is logged to .task-state/branch_isolation_guard.jsonl.\n\n"
        "See: docs/agentic/rules/development-workflow.md"
        "#branch-isolation-protocol-mandatory",
        file=sys.stderr,
    )
    import os as _os
    if _os.environ.get("ALT_ALLOW_BASH_MAIN_WRITE") == "1":
        print(
            "(bypass) ALT_ALLOW_BASH_MAIN_WRITE=1 — allowing but logging",
            file=sys.stderr,
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
