#!/usr/bin/env python3
"""Audit local feature/codex branches against MCP-registered task state."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
import re
from pathlib import Path

from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_archived_task, get_handoff_state

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


def _derive_task_ref(branch: str) -> str | None:
    _, _, slug = branch.partition("/")
    match = TASK_REF_RE.match(slug)
    if not match:
        return None
    return match.group(1).upper()


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


def _active_target_branch() -> str | None:
    identity = get_handoff_state(sections="identity")
    data = identity.get("data", {}) if isinstance(identity, dict) else {}
    active = data.get("active") if isinstance(data, dict) else None
    if not isinstance(active, dict):
        return None
    target_branch = active.get("target_branch")
    return str(target_branch) if isinstance(target_branch, str) and target_branch else None


def _branch_is_registered(branch: str, active_target_branch: str | None) -> bool:
    if active_target_branch == branch:
        return True

    task_ref = _derive_task_ref(branch)
    if task_ref is None:
        return False

    return _archived_snapshot_target_branch(task_ref) == branch


def audit_orphans(repo_root: Path | None = None) -> list[AuditResult]:
    resolved_root = _repo_root() if repo_root is None else repo_root
    configure_runtime(RuntimeConfig.for_repo(resolved_root))

    active_target_branch = _active_target_branch()
    orphans: list[AuditResult] = []

    for branch in _local_branches(resolved_root):
        if _branch_is_registered(branch, active_target_branch):
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
