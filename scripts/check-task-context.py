#!/usr/bin/env python3
"""check-task-context.py — fail-fast worktree/branch alignment check.

Reads the active task from agent-handoff-mcp via the identity-only `sections`
projection and compares its `target_worktree_path` and `target_branch` against
the current process working directory and current git branch. Exits 0 when
aligned, 2 when drift is detected, 1 on infrastructure errors.

Run via `make context` at the start of every session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_INFRA_ERROR = 1
EXIT_DRIFT = 2


def _print_aligned(emoji: str, label: str, value: str) -> None:
    print(f"{emoji} {label:18s} {value}")


def _detect_branch() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return out.decode("utf-8").strip()


def _configure_runtime() -> bool:
    """Configure agent_handoff_mcp runtime for the current repo. Returns False on failure."""
    try:
        from agent_handoff_mcp import RuntimeConfig, configure_runtime  # type: ignore
    except ImportError:
        return False
    try:
        repo_root = Path(
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            .decode("utf-8")
            .strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False
    state_dir = repo_root / ".task-state"
    runtime = RuntimeConfig.for_workspace(
        repo_root,
        state_dir=state_dir,
        current_task_path=repo_root / "CURRENT_TASK.md",
        exports_dir=state_dir / "exports",
    )
    configure_runtime(runtime)
    return True


def _load_active_state() -> dict | None:
    try:
        from agent_handoff_mcp import get_handoff_state  # type: ignore
    except ImportError:
        print("⚠ agent_handoff_mcp not importable from this Python; skipping context check.", file=sys.stderr)
        return None
    if not _configure_runtime():
        print("⚠ failed to configure agent_handoff_mcp runtime; skipping context check.", file=sys.stderr)
        return None
    try:
        raw = get_handoff_state(sections="identity")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"⚠ get_handoff_state(sections='identity') failed: {exc}", file=sys.stderr)
        return None
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        print(f"⚠ get_handoff_state returned non-JSON payload: {exc}", file=sys.stderr)
        return None
    data = parsed.get("data") if isinstance(parsed, dict) else None
    if isinstance(data, dict) and "active" in data:
        return data
    if isinstance(parsed, dict) and "active" in parsed:
        return parsed
    return None


def main() -> int:
    state = _load_active_state()
    if state is None:
        return EXIT_INFRA_ERROR
    active = state.get("active") if isinstance(state, dict) else None
    if not active:
        print("ℹ No active handoff task. Nothing to check.")
        return EXIT_OK

    task_ref = active.get("task_ref") or "(unknown)"
    target_branch = active.get("target_branch")
    target_worktree_path = active.get("target_worktree_path")
    actual_path = os.path.abspath(os.getcwd())
    actual_branch = _detect_branch()

    print(f"Active task: {task_ref}  status={active.get('status', '?')}  rev={active.get('revision', '?')}")
    print()

    drift = False

    if target_worktree_path:
        canonical = os.path.abspath(target_worktree_path)
        if canonical == actual_path:
            _print_aligned("✓", "worktree path", actual_path)
        else:
            _print_aligned("✗", "worktree path", actual_path)
            print(f"                   expected: {canonical}")
            drift = True
    else:
        _print_aligned("…", "worktree path", "(not set on task — recommend setting target_worktree_path)")

    if target_branch:
        if actual_branch == target_branch:
            _print_aligned("✓", "branch", actual_branch or "(unknown)")
        else:
            _print_aligned("✗", "branch", actual_branch or "(unknown)")
            print(f"                   expected: {target_branch}")
            drift = True
    else:
        _print_aligned("…", "branch", actual_branch or "(unknown — no target_branch on task)")

    if drift:
        print()
        if target_worktree_path:
            print(f"  cd {target_worktree_path}")
        if target_branch:
            print(f"  git checkout {target_branch}")
        print()
        print("Drift detected. Switch to the canonical context above before recording further events.")
        return EXIT_DRIFT

    print()
    print("Context aligned ✓")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
