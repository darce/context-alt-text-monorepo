#!/usr/bin/env python3
"""Archive stale ``MAINT-*`` handoff rows.

Ad-hoc maintenance tasks live on ``main`` and register themselves via
``set_handoff_state(task_ref='MAINT-<slug>-<YYYYMMDD>', ...)``. Two or
more live ``MAINT-*`` rows resolvable from the repo root cause
``get_handoff_state`` cwd-resolution to return ``Ambiguous active task``,
which bricks cold-start ``/branch-review`` and similar skills that read
the active task before writing one.

A row is **stale** in either of two cases:

1. **Terminal status** — ``status`` is ``done`` or ``review``. The owner
   already finished it; only the archive call is missing.
2. **Missing worktree** — ``status`` is ``in_progress``/``blocked`` but
   the row's ``target_worktree_path`` is set, distinct from the repo
   root, and no longer exists on disk. The linked worktree was removed
   without first running ``archive_task_state``, leaving the row
   unrecoverable. This is the dominant leak source — see
   MAINT-archive-orphan-maint-rows-20260512 for the precipitating
   incident.

Non-``MAINT`` tasks (feature/epic work) are left untouched — those are
archived by ``make task-finish``. ``in_progress`` MAINT rows whose
worktree still exists also stay put (the task may still be live).

When the script archives a missing-worktree row, ``archive_task_state``
itself requires the target worktree to exist so it can resolve write
provenance. The script handles this by scaffolding a temporary worktree
(branch recreated off ``main`` HEAD if absent) under
``$TMPDIR/maint-archive-scaffold-<pid>/``, performing the archive, and
then tearing the scaffold down. The scaffolding is per-row and
short-lived.

Exit codes: 0 on success (including "nothing to archive"); 1 on runtime
error.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


STALE_STATUSES = frozenset({"done", "review"})
LIVE_STATUSES = frozenset({"in_progress", "blocked"})
MAINT_PREFIX = "MAINT-"


def _ensure_runtime_configured() -> None:
    """Idempotently configure the handoff runtime against the repo root.

    Tests configure their own runtime via the ``isolated_runtime``
    fixture; we must not clobber that. Real invocations (CLI, make
    target) get a repo-rooted runtime.
    """
    from agent_handoff_mcp import RuntimeConfig, configure_runtime, get_runtime_config  # noqa: PLC0415

    try:
        get_runtime_config()
        return  # already configured
    except Exception:  # pragma: no cover - defensive
        pass
    configure_runtime(RuntimeConfig.for_repo(REPO_ROOT))


def _runtime_repo_root() -> Path:
    """Return the configured runtime's repo root (resolved).

    Falls back to the script's repo root if the runtime cannot resolve.
    Tests point this at ``tmp_path`` via ``configure_runtime``.
    """
    try:
        from agent_handoff_mcp import get_runtime_config  # noqa: PLC0415

        cfg = get_runtime_config()
        root = getattr(cfg, "workspace_root", None) or getattr(cfg, "repo_root", None)
        if root is not None:
            return Path(root).resolve()
    except Exception:  # pragma: no cover - defensive
        pass
    return REPO_ROOT.resolve()


def _is_missing_worktree(row: dict[str, Any]) -> bool:
    """Return True iff the row's worktree path is set, distinct from the repo root, and absent on disk.

    A missing-worktree MAINT row is unrecoverable: its linked git
    worktree was removed without first archiving the row.
    """
    target = (row.get("target_worktree_path") or "").strip()
    if not target:
        return False
    target_path = Path(target).resolve()
    if target_path == _runtime_repo_root():
        return False
    return not target_path.exists()


def collect_stale_maint() -> list[dict[str, Any]]:
    """Return every live ``MAINT-*`` row that qualifies as stale.

    Stale = terminal status (``done``/``review``) OR ``in_progress``/
    ``blocked`` with a missing target worktree on disk.
    """
    from agent_handoff_mcp import list_active_tasks  # noqa: PLC0415

    _ensure_runtime_configured()
    stale: list[dict[str, Any]] = []
    for row in list_active_tasks():
        task_ref = row.get("task_ref") or ""
        status = (row.get("status") or "").strip().lower()
        if not task_ref.startswith(MAINT_PREFIX):
            continue
        if status in STALE_STATUSES:
            stale.append(row)
            continue
        if status in LIVE_STATUSES and _is_missing_worktree(row):
            stale.append(row)
    return stale


def _scaffold_worktree(branch: str, repo_root: Path) -> Path | None:
    """Create a temporary worktree for ``branch`` so archive_task_state can resolve provenance.

    Recreates the branch off ``main`` HEAD if it no longer exists. Returns
    the scaffold path on success, ``None`` on failure (with stderr noise).
    """
    main_sha_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if main_sha_proc.returncode != 0:
        print(
            f"  ✗ scaffold: could not resolve main HEAD: {main_sha_proc.stderr.strip()}",
            file=sys.stderr,
        )
        return None
    main_sha = main_sha_proc.stdout.strip()

    branch_exists = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", branch],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    if not branch_exists:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "branch", branch, main_sha],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            print(
                f"  ✗ scaffold: could not create branch {branch}: {proc.stderr.strip()}",
                file=sys.stderr,
            )
            return None

    scaffold_dir = Path(tempfile.mkdtemp(prefix=f"maint-archive-scaffold-{os.getpid()}-"))
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", str(scaffold_dir), branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print(
            f"  ✗ scaffold: git worktree add failed: {proc.stderr.strip()}",
            file=sys.stderr,
        )
        shutil.rmtree(scaffold_dir, ignore_errors=True)
        return None
    return scaffold_dir


def _teardown_scaffold(
    scaffold_dir: Path, branch: str, repo_root: Path, *, delete_branch: bool
) -> None:
    """Remove the scaffold worktree and (optionally) its branch."""
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(scaffold_dir)],
        capture_output=True,
        check=False,
    )
    shutil.rmtree(scaffold_dir, ignore_errors=True)
    if delete_branch:
        subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", branch],
            capture_output=True,
            check=False,
        )


def _archive_with_scaffold(row: dict[str, Any]) -> bool:
    """Archive a missing-worktree row by scaffolding its branch on demand."""
    from agent_handoff_mcp import archive_task_state  # noqa: PLC0415

    branch = (row.get("target_branch") or "").strip()
    task_ref = row["task_ref"]
    repo_root = _runtime_repo_root()
    if not branch:
        print(
            f"  ✗ archive_task_state failed: row {task_ref} has no target_branch; cannot scaffold.",
            file=sys.stderr,
        )
        return False

    branch_pre_existed = (
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", branch],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )

    scaffold = _scaffold_worktree(branch, repo_root)
    if scaffold is None:
        return False
    try:
        result = archive_task_state(task_ref=task_ref)
        if isinstance(result, dict) and result.get("ok") is False:
            err = (
                result.get("data", {}).get("error")
                if isinstance(result.get("data"), dict)
                else None
            )
            print(f"  ✗ archive_task_state failed: {err or result}", file=sys.stderr)
            return False
        return True
    finally:
        _teardown_scaffold(
            scaffold, branch, repo_root, delete_branch=not branch_pre_existed
        )


def archive_stale_maint(
    yes: bool = False, dry_run: bool = False
) -> list[dict[str, Any]]:
    """Archive every stale ``MAINT-*`` row.

    Returns the list of rows that were archived (or would be archived,
    in ``dry_run`` mode). ``yes=False`` prompts interactively per row.
    """
    from agent_handoff_mcp import archive_task_state  # noqa: PLC0415

    _ensure_runtime_configured()
    stale = collect_stale_maint()
    if not stale:
        return []

    processed: list[dict[str, Any]] = []
    for row in stale:
        task_ref = row["task_ref"]
        status = row.get("status")
        updated_at = row.get("updated_at")
        reason = (
            "missing worktree" if _is_missing_worktree(row) else f"status={status}"
        )
        header = (
            f"Stale MAINT row: {task_ref}  ({reason})  updated_at={updated_at}"
        )
        print(header)

        if dry_run:
            print("  Dry run: would archive.")
            processed.append(row)
            continue

        if not yes:
            try:
                answer = input("Archive this row? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer not in {"y", "yes"}:
                print("  Skipped.")
                continue

        if _is_missing_worktree(row):
            if not _archive_with_scaffold(row):
                continue
        else:
            result = archive_task_state(task_ref=task_ref)
            if isinstance(result, dict) and result.get("ok") is False:
                err = (
                    result.get("data", {}).get("error")
                    if isinstance(result.get("data"), dict)
                    else None
                )
                print(f"  ✗ archive_task_state failed: {err or result}", file=sys.stderr)
                continue
        print("  ✓ archived.")
        processed.append(row)

    return processed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="archive every stale row without prompting"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview rows that would be archived; do not mutate state",
    )
    args = parser.parse_args(argv)

    processed = archive_stale_maint(yes=args.yes, dry_run=args.dry_run)
    if not processed:
        print("✓ maint-archive-stale: no stale MAINT-* rows to archive.")
        return 0

    verb = "would archive" if args.dry_run else "archived"
    print(f"maint-archive-stale summary: {verb} {len(processed)} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
