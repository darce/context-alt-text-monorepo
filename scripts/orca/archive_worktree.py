#!/usr/bin/env python3
"""Orca archive hook: refuse to let Orca remove a dirty linked worktree.

orca.yaml `scripts.archive` runs this before `orca worktree rm --run-hooks`
removes a worktree; a non-zero exit blocks the removal. Uncommitted edits in a
linked worktree exist nowhere else, so removing a dirty one destroys work
(constitution rg-017). The hook only reads `git status`: it never deletes,
moves, stashes, or writes anything, and closing the WorkBay task row stays with
`make task-finish`.

Environment (exported by Orca): ORCA_WORKTREE_PATH (required), ORCA_ROOT_PATH.
Exit codes: 0 clean, 1 dirty (paths listed on stderr), 2 failed precondition.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROG = "archive_worktree"
DIRTY_LIST_CAP = 50
TASK_BRANCH_PREFIX = "feature/"
TASK_REF_PLACEHOLDER = "<TASK-REF>"
# Inherited from a parent git process these would point `git -C WT` at another
# repository or index, and a dirty worktree would read as clean.
GIT_LOCATION_ENV: tuple[str, ...] = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _git(worktree: Path, *args: str, capture_stderr: bool = True) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in GIT_LOCATION_ENV}
    # Without this, `git status` refreshes stale stat data and rewrites the index.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", "-C", str(worktree), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if capture_stderr else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )


def _refuse(message: str) -> int:
    print(f"{PROG}: {message}", file=sys.stderr)
    return 2


def _current_branch(worktree: Path) -> str | None:
    branch = _git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    return branch or None


def _task_ref(branch: str | None) -> str:
    # Orca task branches are feature/<task-ref>; the setup hook started the task
    # as TASK=<task-ref upper>, so task-finish takes the same ref.
    if branch and branch.startswith(TASK_BRANCH_PREFIX) and len(branch) > len(TASK_BRANCH_PREFIX):
        return branch[len(TASK_BRANCH_PREFIX) :].upper()
    return TASK_REF_PLACEHOLDER


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args(argv)

    raw_worktree = os.environ.get("ORCA_WORKTREE_PATH", "")
    if not raw_worktree:
        return _refuse(
            "ORCA_WORKTREE_PATH is not set; Orca exports it when it runs orca.yaml scripts.archive. "
            "To check a worktree by hand, run ORCA_WORKTREE_PATH=<worktree> .venv/bin/python "
            "scripts/orca/archive_worktree.py from the primary checkout."
        )
    worktree = Path(raw_worktree)
    if not worktree.is_dir():
        return _refuse(
            f"ORCA_WORKTREE_PATH {worktree} is not a directory; nothing to protect here. "
            "Compare it with `git worktree list` in the primary checkout."
        )
    worktree = worktree.resolve()
    raw_root = os.environ.get("ORCA_ROOT_PATH", "")
    root = Path(raw_root).resolve() if raw_root else None

    try:
        located = _git(worktree, "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir")
    except OSError as exc:
        return _refuse(f"cannot run git ({exc}); put git on PATH for the Orca hook environment.")
    location = located.stdout.splitlines()
    if located.returncode != 0 or len(location) != 2:
        detail = (located.stderr or located.stdout or "no output").strip()
        return _refuse(
            f"ORCA_WORKTREE_PATH {worktree} is not inside a git worktree "
            f"(git rev-parse exit {located.returncode}: {detail}); point Orca at a linked worktree checkout."
        )
    toplevel = Path(location[0]).resolve()
    if root is not None and root in (worktree, toplevel):
        return _refuse(
            f"ORCA_WORKTREE_PATH {worktree} resolves to the primary checkout ORCA_ROOT_PATH {root}; "
            "refusing to archive the primary checkout. Orca may archive only linked worktrees."
        )
    primary = root if root is not None else Path(location[1]).parent

    # stderr is inherited so git's own warnings (for example an unreadable
    # directory that hides untracked files) reach the operator.
    status = _git(worktree, "status", "--porcelain=v1", "--untracked-files=all", capture_stderr=False)
    if status.returncode != 0:
        return _refuse(
            f"`git status` failed in {toplevel} (exit {status.returncode}); cannot prove the worktree is clean, "
            "so archive is refused. Repair the checkout (see git's message above) and retry."
        )
    # Porcelain v1 quotes paths containing newlines, so each line is one entry.
    dirty = [line for line in status.stdout.split("\n") if line]
    branch = _current_branch(worktree)
    finish = f"make task-finish TASK={_task_ref(branch)}"

    if dirty:
        print(
            f"{PROG}: refusing to archive {toplevel}: {len(dirty)} dirty path(s) "
            "from git status --porcelain=v1 --untracked-files=all:",
            file=sys.stderr,
        )
        for line in dirty[:DIRTY_LIST_CAP]:
            print(f"  {line}", file=sys.stderr)
        if len(dirty) > DIRTY_LIST_CAP:
            print(f"  ... and {len(dirty) - DIRTY_LIST_CAP} more", file=sys.stderr)
        on_branch = f" {branch}" if branch else ""
        print(
            f"{PROG}: removing a dirty worktree destroys uncommitted work (rg-017). "
            f"Commit task-owned changes on the branch{on_branch} or move them out of this worktree, "
            f"then close the task with `{finish}` from the primary checkout {primary}.",
            file=sys.stderr,
        )
        return 1

    print(
        f"{PROG}: {toplevel} is clean; Orca may archive it. Orca does not close the WorkBay task row: "
        f"run `{finish}` from the primary checkout {primary}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
