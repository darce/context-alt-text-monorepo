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

# Statuses that indicate the active task has reached a terminal state and the
# agent should start a new task before recording further work. `done` is the
# canonical "task complete, archive pending" status; `blocked` and `review`
# stay surfaced because they represent open holds rather than completion.
TERMINAL_STATUSES = frozenset({"done"})


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


def _git_dirty_paths() -> list[str] | None:
    """Return the relative paths of tracked-but-modified files (vs HEAD).

    Uses ``git diff --name-only HEAD`` so only tracked content that
    diverges from HEAD is reported. Untracked files are intentionally
    excluded — they are either the user's in-progress working files or
    build artifacts, neither of which is the kind of silent file revert
    or stale-buffer overwrite this integrity check exists to catch.
    Aligned with the bash-side check in ``scripts/task-finish.sh`` so
    the two surfaces report the same set of paths.

    Returns ``None`` when git is unavailable.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _load_dirty_allowlist(state_dir: Path) -> set[str]:
    """Read ``.task-state/dirty-allowlist`` and return the set of allowed paths.

    The allowlist file is a plain newline-delimited list of repo-relative
    paths that are expected to be dirty (e.g. work that pre-dates the active
    task, or files the user is intentionally editing in parallel). Comments
    starting with ``#`` and blank lines are ignored. Missing file is treated
    as an empty allowlist.

    Anchoring at ``state_dir`` (which is the **primary** worktree's
    ``.task-state`` thanks to ``RuntimeConfig.for_repo``) means a single
    allowlist applies across all linked worktrees of the same physical
    repository.
    """
    allowlist_path = state_dir / "dirty-allowlist"
    if not allowlist_path.exists():
        return set()
    allowed: set[str] = set()
    try:
        for raw in allowlist_path.read_text().splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            allowed.add(stripped)
    except OSError:
        return set()
    return allowed


def _configure_runtime() -> bool:
    """Configure agent_handoff_mcp runtime for the current repo. Returns False on failure.

    Resolves the workspace root via ``RuntimeConfig.for_repo`` so that running
    this script from a linked worktree still binds to the primary worktree's
    ``.task-state/handoff.db``. Without this, every linked worktree would
    start with an empty per-worktree DB and ``make context`` would report
    "No active handoff task" even when the MCP server (configured against
    the primary worktree) sees a different active task. AHMCP-16 closes
    this divergence loop.
    """
    try:
        from agent_handoff_mcp import RuntimeConfig, configure_runtime  # type: ignore
    except ImportError:
        return False
    runtime = RuntimeConfig.for_repo(Path.cwd())
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
        # AHMCP-18 (item A): the working-tree integrity check is an
        # independent class of problem from worktree drift, so we run it
        # even on the drift path. A user who is in the wrong worktree
        # AND has unexpected dirty files needs to see both warnings.
        _emit_integrity_warning_if_dirty()
        return EXIT_DRIFT

    print()
    print("Context aligned ✓")

    # AHMCP-16: surface a loud warning when the active task has already
    # reached a terminal status. Without this, agents who run `make context`
    # at the start of a session see "Context aligned" for a `done` task and
    # may start editing code under the impression they are still under that
    # task's umbrella, only to be blocked by the branch-isolation hook on
    # the first edit. Telling them up-front to start a new task is cheaper
    # than discovering it via the hook later.
    status = (active.get("status") or "").strip().lower()
    if status in TERMINAL_STATUSES:
        print()
        print(f"⚠ Active task `{task_ref}` is in status `{status}`.")
        print("  Start a new task before recording further work:")
        print("    make task-start TASK=<id> OBJECTIVE=\"...\"")
        print("  or switch to an existing task with switch_task.")

    # AHMCP-18 (item A): working-tree integrity check.
    #
    # Compare `git status --porcelain` against `.task-state/dirty-allowlist`
    # and warn loudly when files outside the allowlist are dirty. This
    # catches the "session bleed" failure mode where a long-lived editor
    # buffer (or any out-of-band write) leaves the working tree in a
    # surprising state at the start of the next session — for example
    # the silent api.py revert that bit AHMCP-15-BR-FIXES on merge.
    #
    # The allowlist file is anchored at the primary worktree's .task-state
    # so a single allowlist applies across all linked worktrees of the
    # same physical repository.
    _emit_integrity_warning_if_dirty()

    return EXIT_OK


def _emit_integrity_warning_if_dirty() -> None:
    """Print a warning if any unexpected paths are dirty.

    Reads ``.task-state/dirty-allowlist`` from the primary worktree (via
    ``RuntimeConfig.for_repo``) and compares it against the current
    ``git status --porcelain`` output. Files in the allowlist are
    considered intentional drift; everything else is surfaced.
    """
    try:
        from agent_handoff_mcp import RuntimeConfig  # type: ignore
    except ImportError:
        return
    runtime = RuntimeConfig.for_repo(Path.cwd())
    dirty = _git_dirty_paths()
    if dirty is None:
        return
    if not dirty:
        return
    allowed = _load_dirty_allowlist(runtime.state_dir)
    unexpected = sorted(p for p in dirty if p not in allowed)
    if not unexpected:
        return
    print()
    print(f"⚠ Working-tree integrity: {len(unexpected)} unexpected dirty path(s).")
    print("  These files differ from HEAD or are untracked but are not in")
    print(f"  {runtime.state_dir / 'dirty-allowlist'}:")
    for path in unexpected[:10]:
        print(f"    - {path}")
    if len(unexpected) > 10:
        print(f"    ... and {len(unexpected) - 10} more")
    print()
    print("  If these are intentional, add them to dirty-allowlist (one path per")
    print("  line). If they are not, investigate before recording handoff state —")
    print("  silent file reverts and stale editor buffers cause merge regressions.")


if __name__ == "__main__":
    sys.exit(main())
