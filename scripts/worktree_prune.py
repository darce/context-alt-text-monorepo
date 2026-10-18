#!/usr/bin/env python3
"""Interactively delete orphan feature/codex branches discovered by worktree_audit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from worktree_audit import audit_orphans


def _repo_root() -> Path:
    out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True)
    return Path(out.strip()).resolve()


def _delete_branch(repo_root: Path, branch: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "branch", "-d", branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="delete all orphan branches without prompting")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview orphan branches that would be deleted without mutating git state",
    )
    args = parser.parse_args()

    repo_root = _repo_root()
    orphans = audit_orphans(repo_root)
    if not orphans:
        print("✓ worktree-prune: no orphan feature/codex branches to delete.")
        return 0

    deleted = 0
    skipped = 0
    failed = 0
    previewed = 0

    for orphan in orphans:
        print(f"Orphan branch: {orphan.branch}")
        print(f"  Reason: {orphan.reason}")
        if args.dry_run:
            previewed += 1
            print("  Dry run: would delete with `git branch -d`.")
            continue
        delete_branch = args.yes
        if not args.yes:
            try:
                answer = input("Delete this branch with `git branch -d`? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            delete_branch = answer in {"y", "yes"}
        if not delete_branch:
            skipped += 1
            print("  Skipped.")
            continue

        proc = _delete_branch(repo_root, orphan.branch)
        if proc.returncode == 0:
            deleted += 1
            print(f"  Deleted {orphan.branch}.")
            continue
        failed += 1
        message = proc.stderr.strip() or proc.stdout.strip() or "git branch -d failed"
        print(f"  Failed to delete {orphan.branch}: {message}", file=sys.stderr)

    if args.dry_run:
        print(f"worktree-prune summary: previewed={previewed} deleted=0 skipped=0 failed=0")
        return 0

    print(f"worktree-prune summary: deleted={deleted} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
