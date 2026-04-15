#!/usr/bin/env python3
"""Audit tagged main-branch commits for matching task-plan files."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK_TAG_RE = re.compile(r"^(?:feat|fix|docs|refactor|test)\(((?:AHMCP|E\d+)-\d+)\):\s+", re.IGNORECASE)
PLAN_DIRS = (
    Path("docs") / "tasks",
    Path("packages") / "agent-handoff-mcp" / "docs" / "tasks",
)


def _repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(proc.stdout.strip()).resolve()


def _tagged_task_refs(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for subject in proc.stdout.splitlines():
        match = TASK_TAG_RE.match(subject.strip())
        if not match:
            continue
        task_ref = match.group(1).upper()
        if task_ref in seen:
            continue
        seen.add(task_ref)
        ordered.append(task_ref)
    return ordered


def _has_task_plan(repo_root: Path, task_ref: str) -> bool:
    task_prefix = f"{task_ref}-"
    for plan_dir in PLAN_DIRS:
        root = repo_root / plan_dir
        if not root.exists():
            continue
        for path in root.rglob("*-task-plan.md"):
            if path.name.upper().startswith(task_prefix):
                return True
    return False


def main() -> int:
    repo_root = _repo_root()
    missing = [task_ref for task_ref in _tagged_task_refs(repo_root) if not _has_task_plan(repo_root, task_ref)]

    if not missing:
        print("✓ task-plan-audit: all tagged main-branch task refs have plan files.")
        return 0

    print("✗ task-plan-audit: missing task-plan files for tagged main-branch task refs:")
    for task_ref in missing:
        print(f"  - {task_ref}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
