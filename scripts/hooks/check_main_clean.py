#!/usr/bin/env python3
"""Detect dirty protected paths on the main branch (BR-16 / BR-22).

Invoked from:
  - git hooks (post-checkout, post-commit, post-merge, post-rewrite) as a WARNING scanner
  - git pre-push hook as a HARD BLOCK when pushing main
  - `make check-main-clean` as an on-demand operator/agent check

Reads no stdin. Exit 0 when clean or when not on a protected branch. Exit 2
when dirty protected paths exist and `--block` is passed (pre-push mode).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--block",
        action="store_true",
        help="Exit 2 instead of 0 when dirty protected paths are found.",
    )
    parser.add_argument(
        "--trigger",
        default="manual",
        help="Source hook/op that fired this scan (post-checkout, post-commit, "
        "post-merge, post-rewrite, pre-push, manual). Shown in the output header.",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    branch = _current_branch(repo_root)
    if branch not in {"main", "master"}:
        return 0

    sys.path.insert(0, str(repo_root / "scripts" / "hooks"))
    try:
        from _branch_isolation_guard import find_dirty_protected_paths
        from _harness_protocol import HarnessContractMissingError, load_branch_isolation_policy
    except ImportError as exc:
        print(f"check_main_clean: import failed — {exc}", file=sys.stderr)
        return 0

    try:
        policy = load_branch_isolation_policy(repo_root)
    except HarnessContractMissingError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    result = find_dirty_protected_paths(
        branch=branch,
        repo_root=str(repo_root),
        policy=policy,
        protected_branches={"main", "master"},
    )
    if result is None:
        if args.trigger != "manual":
            # Silent on hook triggers when clean.
            return 0
        print(f"check-main-clean: OK ({branch}, no dirty protected paths)")
        return 0

    resolved_branch, dirty_paths = result
    rendered = "\n".join(f"  - {path}" for path in dirty_paths)
    severity = "BLOCKED" if args.block else "WARNING"
    trigger = args.trigger
    print(
        f"\n{severity} (check-main-clean / trigger={trigger}): "
        f"protected paths are dirty on {resolved_branch}.\n"
        f"Dirty files:\n{rendered}\n\n"
        "How this likely happened:\n"
        "  - git stash apply/pop reapplied a patch onto main (no native hook)\n"
        "  - git checkout/merge/rebase reintroduced a protected-path change\n"
        "  - a Bash command wrote to the path (covered by guard-bash-main-branch.py)\n"
        "  - an IDE buffer flushed stale state after a branch switch\n\n"
        "Remediation:\n"
        "  1. Review each file (git diff) before acting.\n"
        "  2. Move task-owned changes to a feature branch:\n"
        "       git checkout -b feature/<task>-<slug>\n"
        "       git add <files> && git commit\n"
        "  3. For carryover you want to preserve but not land:\n"
        "       git stash push -m 'carryover-<date>' -- <files>\n"
        "  4. For safe resets of files you're sure are redundant:\n"
        "       git restore <file>  # only when confirmed redundant vs main\n\n"
        "See: docs/agentic/rules/development-workflow.md"
        "#branch-isolation-protocol-mandatory\n",
        file=sys.stderr,
    )
    return 2 if args.block else 0


if __name__ == "__main__":
    raise SystemExit(main())
