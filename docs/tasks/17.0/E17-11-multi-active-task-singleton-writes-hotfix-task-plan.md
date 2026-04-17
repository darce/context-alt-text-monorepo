# E17-11. Multi-active-task hot-fix: remove singleton `WHERE id = 1` writes

> Status: DRAFT (planning) — not yet reviewed
> Parent epic: E17 (Hoist Agentic System MVP)
> Created: 2026-04-17

## Objective

Remove the remaining singleton `WHERE id = 1` assumptions from `agent-handoff-mcp` so multiple feature branches can register active tasks in parallel without evicting one another. E17-7 Slice 2 introduced the task_ref-keyed schema and workspace-path read resolution; this hot-fix finishes the job on the write paths that still collapse to `id = 1`.

## Motivation

User report (2026-04-17): _"the multiple active task capability must be fixed even if it's a hot fix — it's holding back development of other branches in parallel"_.

Current observed behaviour:

- `switch_task` (`agent_handoff_mcp/import_export.py:949`) reads `WHERE id = 1`, archives that task, and writes the incoming task to `id = 1`. Net effect: switching from codex's active task to another agent's active task **evicts and archives** the first one, even though both should coexist.
- `_resolve_workspace_handoff_row` (`shared_primitives.py:342–417`) works for multi-row scans, but when the hook cannot derive a task_ref from tool input it falls through to the singleton fallback in `shared_write_context.py:451` (`SELECT ... FROM handoff_state WHERE id = 1`).
- An audit of the package surface lists ~15 additional `WHERE id = 1` read sites across context collectors, drift detectors, and dashboard renderers. Each must be re-examined for whether it should key by `task_ref` or by workspace path.

## Non-Goals

- Schema change. The table already supports multi-row via E17-7 Slice 2; this hot-fix only updates the code paths.
- Changing `DASHBOARD.txt` rendering (already cross-task).
- Refactoring `CURRENT_TASK.json` into per-task files (separate follow-up).

## Slices

### Slice 1 — Audit and catalogue every `WHERE id = 1` site

- Grep `packages/agent-handoff-mcp/src/agent_handoff_mcp/` for `id = 1`, `id=1`, and `handoff_state WHERE id`.
- Classify each hit: `read_for_active_task`, `read_for_specific_task`, `write_update`, `legacy_singleton`.
- Output: structured catalogue (markdown table) enumerating file/line, classification, and recommended fix (task_ref-keyed vs workspace-resolved vs delete).

### Slice 2 — Fix `switch_task` eviction

- Rewrite `switch_task` so it does not archive the previously active task. New semantics: "point the caller's working context at task X"; leave other rows in place.
- Tests covering: switch does not archive; two parallel tasks coexist; dashboard renders both.

### Slice 3 — Migrate read fallbacks to workspace-resolved lookups

- For each `read_for_active_task` hit where the caller has a cwd/branch, resolve via `_resolve_workspace_handoff_row` instead of `WHERE id = 1`.
- Drift hook fallback: when no task_ref can be extracted from tool input, walk the workspace path to find the matching row. Only use singleton as a last-resort fallback and log a warning.

### Slice 4 — Regression tests + docs update

- Multi-active end-to-end test: two handoff_state rows, two distinct `target_branch` values; writes from each worktree land on their own row; dashboard renders both; close check on one does not leak state of the other.
- Update `docs/agentic/maps/backend.md` to document the new semantics and reference `_resolve_workspace_handoff_row` as the preferred resolution path.

## Consolidated Checklist

- [ ] Slice 1: catalogue complete, reviewed, committed to `docs/tasks/17.0/E17-11-catalogue.md` (temp artifact).
- [ ] Slice 2: `switch_task` no longer archives; regression test added.
- [ ] Slice 3: all `read_for_active_task` callers resolved via workspace path; singleton fallback documented as last-resort only.
- [ ] Slice 4: multi-active e2e test green; docs updated.

## Risk / Rollback

Plan consumes a single feature branch. If regressions surface, revert the merge commit and the task can be re-planned. Archive/dashboard paths are high-impact — test coverage must gate each slice.

## References

- E17-7 Slice 2 introduced multi-active schema: `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`
- E17-8 S2 drift hook added workspace-resolved reads for the hook surface only
- User directive 2026-04-17 (session transcript): "multiple active task capability must be fixed even if it's a hot fix"

## Open Threads for Planning Review

- Does `switch_task` need a `archive_previous=False` kwarg for backward compat, or is breaking-change the right move (greenfield policy)?
- Should the singleton fallback in `shared_write_context.py:451` be removed outright or kept as an error path with telemetry?
- Does the drift hook need a new `target_worktree_path → task_ref` lookup helper, or does `_resolve_workspace_handoff_row` suffice?
