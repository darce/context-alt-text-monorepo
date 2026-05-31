#!/usr/bin/env python3
"""Audit local feature/codex branches against MCP-registered task state."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
import re
from pathlib import Path

from workstate_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    get_archived_task,
    list_active_tasks,
)

BRANCH_PREFIXES = ("feature/", "codex/")
TASK_REF_RE = re.compile(r"^([a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class AuditResult:
    branch: str
    reason: str


def _repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True)
    return Path(out.strip()).resolve()


def _local_branches(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    branches = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return sorted(branch for branch in branches if branch.startswith(BRANCH_PREFIXES))


def _derive_task_ref_candidates(branch: str) -> list[str]:
    """Return ordered candidate task_refs derived from a branch name.

    Used only for archived-task fallback lookups, where the DB is case-sensitive
    but naming conventions differ (epic refs uppercase like E17-10, MAINT-*
    refs use mixed case like MAINT-foo-20260424). Live-task matching uses
    list_active_tasks() and compares target_branch directly, so it does not
    depend on these candidates.
    """
    _, _, slug = branch.partition("/")
    match = TASK_REF_RE.match(slug)
    if not match:
        return []
    raw = match.group(1)
    candidates: list[str] = [raw]
    upper = raw.upper()
    if upper not in candidates:
        candidates.append(upper)
    # MAINT hybrid: "MAINT-<lowercase-rest>" — our live convention for
    # maintenance tasks on main.
    if raw.lower().startswith("maint-"):
        hybrid = "MAINT-" + raw[len("maint-"):].lower()
        if hybrid not in candidates:
            candidates.append(hybrid)
    return candidates


def _derive_task_ref(branch: str) -> str | None:
    candidates = _derive_task_ref_candidates(branch)
    return candidates[-1] if candidates else None


def _archived_snapshot_target_branch(task_ref: str) -> str | None:
    archived = get_archived_task(task_ref=task_ref, include_snapshot=True)
    if archived.get("ok") is not True:
        return None

    data = archived.get("data")
    if not isinstance(data, dict):
        return None
    snapshot = data.get("snapshot")
    if not isinstance(snapshot, dict):
        return None
    active = snapshot.get("active")
    if not isinstance(active, dict):
        return None
    target_branch = active.get("target_branch")
    return str(target_branch) if isinstance(target_branch, str) and target_branch else None


def _live_target_branches() -> set[str]:
    """Return the set of target_branch values across all live handoff_state rows."""
    rows = list_active_tasks()
    if not isinstance(rows, list):
        return set()
    branches: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        target_branch = row.get("target_branch")
        if isinstance(target_branch, str) and target_branch:
            branches.add(target_branch)
    return branches


def _branch_is_registered(branch: str, live_branches: set[str]) -> bool:
    if branch in live_branches:
        return True
    for task_ref in _derive_task_ref_candidates(branch):
        if _archived_snapshot_target_branch(task_ref) == branch:
            return True
    return False


def audit_orphans(repo_root: Path | None = None) -> list[AuditResult]:
    resolved_root = _repo_root() if repo_root is None else repo_root
    configure_runtime(RuntimeConfig.for_repo(resolved_root))

    live_branches = _live_target_branches()
    orphans: list[AuditResult] = []

    for branch in _local_branches(resolved_root):
        if _branch_is_registered(branch, live_branches):
            continue
        task_ref = _derive_task_ref(branch)
        if task_ref is None:
            reason = "task_ref could not be derived from branch naming convention"
        else:
            reason = f"no active target_branch or archived snapshot target_branch matches derived task {task_ref}"
        orphans.append(AuditResult(branch=branch, reason=reason))
    return orphans


def main() -> int:
    repo_root = _repo_root()
    orphans = audit_orphans(repo_root)

    if not orphans:
        print("✓ worktree-audit: no orphan feature/codex branches detected.")
        return 0

    print("✗ worktree-audit: orphan local branches detected:")
    for item in orphans:
        print(f"  - {item.branch}: {item.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
