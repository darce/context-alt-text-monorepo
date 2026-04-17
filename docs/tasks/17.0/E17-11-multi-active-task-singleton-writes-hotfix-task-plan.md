# E17-11. Multi-active-task hot-fix: remove singleton `WHERE id = 1` writes

> Status: DRAFT (planning) — not yet reviewed
> Parent epic: E17 (Hoist Agentic System MVP)
> Created: 2026-04-17

## Objective

Remove the remaining singleton `WHERE id = 1` assumptions from `agent-handoff-mcp` so multiple feature branches can register active tasks in parallel without evicting one another. E17-7 Slice 2 introduced the task_ref-keyed schema and workspace-path read resolution; this hot-fix finishes the job on the write paths that still collapse to `id = 1`.

## Motivation

User report (2026-04-17): _"the multiple active task capability must be fixed even if it's a hot fix — it's holding back development of other branches in parallel"_.

Current observed behaviour (all three bugs must be fixed; fixing any one alone still leaves the others user-visible):

1. **switch_task singleton eviction.** `agent_handoff_mcp/import_export.py:949` reads `WHERE id = 1`, archives that task, and writes the incoming task to `id = 1` at `:1036`. Net effect: switching from one agent's active task to another **evicts and archives** the first one, even though both should coexist.
2. **Write-context guard defaults to singleton.** `shared_write_context.py:451` (`collect_target_context_warnings`) falls back to `WHERE id = 1` unless a `task_ref` kwarg is explicitly passed. It gained a task_ref-aware path (line 454) but nothing passes it in the hot paths.
3. **Caller-ordering bug: guard runs before `_resolve_task_ref`.** `review_findings.py:852` calls `collect_target_context_warnings(conn, ctx)` **without** `task_ref=`, **before** `_resolve_task_ref(conn, task_ref)` at `:881`. Even if the callee in bug #2 is fixed to prefer the passed task_ref, the caller never passes one here, so drift/branch-enforcement still binds to whatever occupies the sentinel row. This is the exact surface that blocked an E17-10-style fix. The same inversion exists in at least `record_event`, `close_slice`, `set_handoff_state`, and `handoff_close_check` — each call site must be audited.
4. `_resolve_workspace_handoff_row` (`shared_primitives.py:342–417`) works for multi-row scans on the read side, but offers no help to a write caller that has a `task_ref` in hand and simply fails to thread it through.

The read path ambiguity error (E17-8/E17-9 from the root worktree) confirms multi-row coexistence works; the remaining work is plumbing the known task_ref through every write caller before any guard runs, and killing `switch_task`'s singleton upsert.

## Non-Goals

- Schema change. The table already supports multi-row via E17-7 Slice 2; this hot-fix only updates the code paths.
- Changing `DASHBOARD.txt` rendering (already cross-task).
- Refactoring `CURRENT_TASK.json` into per-task files (separate follow-up).

## Slices

### Slice 1 — Audit and catalogue every singleton site

Two catalogues required — one for the write-guard callee, one for the caller ordering:

- **Callee audit.** Grep `packages/agent-handoff-mcp/src/agent_handoff_mcp/` for `id = 1`, `id=1`, and `handoff_state WHERE id`. Classify each hit: `read_for_active_task`, `read_for_specific_task`, `write_update`, `legacy_singleton`.
- **Caller audit.** Grep the same tree for `collect_target_context_warnings(` and `_resolve_task_ref(`. For every call site that invokes both, record the ordering: does the call site resolve `task_ref` before the guard, or does it call the guard with an implicit singleton binding? Any site that calls the guard first is a bug.
- Output: two markdown tables (callee catalogue + caller catalogue) committed as `docs/tasks/17.0/E17-11-catalogue.md` with recommended fix per hit.

### Slice 2 — Fix `switch_task` eviction

- Rewrite `switch_task` (`import_export.py:923`) so it does not archive the previously active task. Replace the singleton `SELECT ... WHERE id = 1` read (`:949`) and the `UPDATE ... WHERE id = 1` upsert (`:1036`) with a task_ref-keyed read and insert/update by `task_ref`. New semantics: "point the caller's working context at task X"; leave other rows in place.
- Decision for planning review: does `switch_task` retain a sentinel pointer concept at all, or is "which task is active from this worktree" now purely derived from cwd/branch via `_resolve_workspace_handoff_row`? (Greenfield policy permits the cleaner answer.)
- Tests covering: switch does not archive; two parallel tasks coexist; dashboard renders both; restoring an archived task still works.

### Slice 3 — Thread task_ref through every write caller before any guard runs

This is the bug that blocks E17-10-style fixes. Three coordinated changes:

- **a. Callee: make the guard task_ref-aware at every call site.** `collect_target_context_warnings` already accepts `task_ref` (since an earlier slice), but the `WHERE id = 1` fallback at `shared_write_context.py:451` must be replaced with either workspace-resolved lookup or an explicit error. The singleton fallback stays only as a last-resort for bootstrap callers that have neither task_ref nor workspace context.
- **b. Caller ordering: resolve task_ref first.** Every write handler that today calls `collect_target_context_warnings(conn, ctx)` before `_resolve_task_ref(conn, task_ref)` must be re-ordered. Confirmed sites so far: `review_findings.py:852/881`, and per Slice 1 audit all analogous call sites in `record_event`, `close_slice`, `set_handoff_state`, `update_task_status`, `handoff_close_check`. Each must pass the resolved task_ref into the guard.
- **c. Drift hook fallback.** When no task_ref can be extracted from tool input, walk the workspace path to find the matching row. Only use the sentinel as a last-resort fallback and log a warning.

### Slice 4 — Regression tests + docs update

- **Caller-ordering regression test.** Create two active rows (E17-A on feature/a, E17-B on feature/b). From a cwd on feature/b with no `target_worktree_path` match to row A, call `review_findings(update, task_ref='E17-B', ...)`. The update must succeed without a branch-enforcement rejection derived from row A's target_branch. This is the exact failure shape the user reported against E17-10.
- **switch_task regression test.** Two rows coexist before and after `switch_task`; previously-active row is not archived; archive-restore of a genuinely archived task still works.
- **Workspace-resolved drift test.** From a third cwd that matches neither row, the drift hook logs a warning instead of incorrectly binding to whichever row occupies the sentinel slot.
- Update `docs/agentic/maps/backend.md` to document the new semantics and reference `_resolve_workspace_handoff_row` as the preferred resolution path; add a "Write caller ordering" subsection under `docs/agentic/rules/backend-python-guidelines.md` that names the caller-first-then-guard pattern and the failure mode it prevents.

## Consolidated Checklist

- [ ] Slice 1a: callee catalogue complete (every `WHERE id = 1` hit).
- [ ] Slice 1b: caller catalogue complete (every `collect_target_context_warnings` → `_resolve_task_ref` inversion).
- [ ] Slice 2: `switch_task` no longer archives; task_ref-keyed read + upsert; regression test added.
- [ ] Slice 3a: guard callee `WHERE id = 1` fallback removed in favour of workspace-resolved or explicit error.
- [ ] Slice 3b: every write caller resolves task_ref BEFORE invoking the guard; caller-ordering regression test green.
- [ ] Slice 3c: drift hook fallback walks workspace path; sentinel is last-resort only.
- [ ] Slice 4: multi-active e2e test green; caller-ordering regression test green; `switch_task` regression test green; docs updated.

## Risk / Rollback

Plan consumes a single feature branch. If regressions surface, revert the merge commit and the task can be re-planned. Archive/dashboard paths are high-impact — test coverage must gate each slice.

## References

- E17-7 Slice 2 introduced multi-active schema: `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`
- E17-8 S2 drift hook added workspace-resolved reads for the hook surface only
- User directive 2026-04-17 (session transcript): "multiple active task capability must be fixed even if it's a hot fix"

## Open Threads for Planning Review

- Does `switch_task` need an `archive_previous=False` kwarg for backward compat, or is breaking-change the right move (greenfield policy)? Related: does "active task from this worktree" become a derived query (cwd/branch → row) instead of a sentinel pointer?
- Should the singleton fallback in `shared_write_context.py:451` be removed outright, kept as an error path with telemetry, or preserved as a bootstrap-only path for the very first row in a fresh DB?
- Does the drift hook need a new `target_worktree_path → task_ref` lookup helper, or does `_resolve_workspace_handoff_row` suffice?
- How do we mechanically prevent the caller-ordering bug from reappearing? Options: (a) make the guard refuse to run without an explicit task_ref or workspace context; (b) lint rule in `scripts/check_harness_sync.py` that flags any `collect_target_context_warnings(` call inside a function body that also calls `_resolve_task_ref(` with the guard appearing first; (c) both.
