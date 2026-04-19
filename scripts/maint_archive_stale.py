#!/usr/bin/env python3
"""Archive stale ``MAINT-*`` handoff rows.

Ad-hoc maintenance tasks live on ``main`` and register themselves via
``set_handoff_state(task_ref='MAINT-<slug>-<YYYYMMDD>', ...)``. Their
``target_worktree_path`` defaults to the repo root, so two live
``MAINT-*`` rows cause ``get_handoff_state`` cwd-resolution to return
``Ambiguous active task`` — which bricks cold-start ``/branch-review``
and similar skills that read the active task before writing one.

This script archives every live ``MAINT-*`` row whose status is already
terminal (``done`` or ``review``). Non-``MAINT`` tasks (feature/epic
work) are left untouched — those are archived by ``make task-finish``.
Rows still in ``in_progress``/``blocked`` stay put.

Exit codes: 0 on success (including "nothing to archive"); 1 on runtime
error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDOFF_SRC = REPO_ROOT / "packages" / "agent-handoff-mcp" / "src"
if str(HANDOFF_SRC) not in sys.path:
    sys.path.insert(0, str(HANDOFF_SRC))


STALE_STATUSES = frozenset({"done", "review"})
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


def collect_stale_maint() -> list[dict[str, Any]]:
    """Return every live ``MAINT-*`` row whose status is terminal."""
    from agent_handoff_mcp import list_active_tasks  # noqa: PLC0415

    _ensure_runtime_configured()
    stale: list[dict[str, Any]] = []
    for row in list_active_tasks():
        task_ref = row.get("task_ref") or ""
        status = (row.get("status") or "").strip().lower()
        if not task_ref.startswith(MAINT_PREFIX):
            continue
        if status not in STALE_STATUSES:
            continue
        stale.append(row)
    return stale


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
        header = (
            f"Stale MAINT row: {task_ref}  status={status}  updated_at={updated_at}"
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
