# AHMCP-28. Dashboard Path Fix and Task-Start Archive

> **Metadata**:
>
> - **Date**: 2026-04-14
> - **Author**: Claude Sonnet 4.6 (retroactive)
> - **Project**: agent-handoff-mcp
> - **Task ID**: AHMCP-28
> - **Target Branch**: `feature/ahmcp-28`
> - **Merged**: `f33a9c10` + `b6ec8371` on `main`

---

## Objective

Fix two coupled bugs: (1) `generate_dashboard_md` writes to the wrong path when called from a feature worktree, and (2) `task-start.sh` does not archive the outgoing active task, leaving its status permanently stale on the dashboard.

## Problem Statement

**Bug 1 — Wrong dashboard write path**: `generate_dashboard_md` derived the write path as `cfg.current_task_path.parent / "DASHBOARD.md"`. When called from a feature worktree, `current_task_path` resolves inside the linked worktree directory, so `DASHBOARD.md` is written there instead of the operator-facing location in the main worktree root. The operator never sees the update. <!-- lint-dashboard-txt: allow -->

**Bug 2 — Outgoing task not archived on task-start**: `scripts/_task_start_inline.py` activated the new task without archiving the outgoing one. The outgoing task's row remained as the non-active default, but its status was not captured in a snapshot. The dashboard rendered the outgoing task with a stale or default status rather than its real `in_progress` state at handoff time.

The two bugs are coupled: fixing the dashboard path without fixing the archive means the corrected dashboard still shows wrong status for the previous task.

## Constraints

- `switch_task` was already implemented in `core.py` but not exported through `api.py` or `__init__.py`; the fix must expose it without duplicating logic.
- Dashboard path must come from `cfg.dashboard_path` (a dedicated `RuntimeConfig` field), not derived from `current_task_path`.
- Existing tests must not regress.

## Proposed Solution

**Fix 1 — Use `cfg.dashboard_path`**: Replace `cfg.current_task_path.parent / "DASHBOARD.md"` with `cfg.dashboard_path` in `generate_dashboard_md`. `RuntimeConfig` already carries a `dashboard_path` field pointing to the main-worktree root; callers that do not set it get the same default as before. <!-- lint-dashboard-txt: allow -->

**Fix 2 — Call `switch_task` from `_task_start_inline.py`**: Before activating the new task, call `switch_task(task_ref=new_task_ref)` which atomically archives the outgoing task with its current status snapshot, then activates the target. Export `switch_task` through `api.py` and `__init__.py` so `_task_start_inline.py` can import it from the package surface.

## Files Changed

| File | Change |
|---|---|
| `src/agent_handoff_mcp/dashboard_rendering.py` | Use `cfg.dashboard_path` instead of `cfg.current_task_path.parent / "DASHBOARD.md"` | <!-- lint-dashboard-txt: allow -->
| `src/agent_handoff_mcp/api.py` | Export `switch_task = core.switch_task` |
| `src/agent_handoff_mcp/__init__.py` | Add `switch_task` to imports and `__all__` |
| `scripts/_task_start_inline.py` | Call `switch_task(task_ref=...)` to archive outgoing task before activation |
| `tests/test_dashboard_rendering.py` | Regression: split-root dashboard path writes to configured `dashboard_path`, not feature worktree |
| `tests/test_lifecycle_scripts.py` | Regression: task-start archives prior task; dashboard shows correct `in_progress` status |

## Verification

- `cd packages/agent-handoff-mcp && make test-handoff` — new tests pass:
  - `test_generate_dashboard_md_uses_runtime_dashboard_path`: asserts write goes to `RuntimeConfig.dashboard_path`, not feature worktree sibling
  - `test_task_start_archives_previous_task_for_dashboard_status`: asserts outgoing task appears as `in_progress` in dashboard after second task-start
- Manual: run `make task-start TASK=T2 OBJECTIVE="..."` when `T1` is active → `T1` archived; `DASHBOARD.md` in main worktree root updated with correct `T1` status <!-- lint-dashboard-txt: allow -->
