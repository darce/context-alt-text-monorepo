# E17-11. Multi-active-task hot-fix: remove the singleton sentinel

> Status: DRAFT (planning) — planning-review in progress
> Parent epic: E17 (Hoist Agentic System MVP)
> Target Branch: `feature/e17-11`
> Target Worktree: `/Users/daniel/Development/context-alt-text-monorepo-e17-11`
> Created: 2026-04-17

## Objective

Remove the singleton sentinel (`handoff_state WHERE id = 1`) from `agent-handoff-mcp` so multiple feature branches can register active tasks in parallel without any row acting as "the active task". E17-7 Slice 2 introduced task_ref-keyed schema and workspace-path read resolution; this hot-fix deletes the remaining sentinel reads and writes, and redirects every downstream consumer to workspace- or task_ref-derived resolution.

## Greenfield Decision: Sentinel Removed

This plan explicitly resolves the "does the sentinel survive?" open thread (PLAN-01) as: **no**. Rationale:

- Greenfield policy — no production users, no existing data to preserve, forked projects start with a fresh DB.
- The sentinel has no legitimate role once `_resolve_workspace_handoff_row` can answer "which task is this worktree on?" from cwd/branch. Any surface that needs an "active task" answer will derive it from the caller's workspace or be passed an explicit `task_ref`.
- Keeping the sentinel as a compatibility shim costs clarity and perpetuates exactly the eviction pattern we're trying to remove.

Consequence: `task_ref` remains the real primary key (per [shared_schema.py:107](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py#L107)). The `id` column stays as an ignored nullable legacy column constrained by `CHECK (id IS NULL OR id = 1)` ([shared_schema.py:106](../../../packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py#L106)); no code may assume `id = 1` is "the active task" and no new row may set `id = 1`. All new rows insert with `id = NULL`, which the `UNIQUE`/`CHECK` constraint already permits without a schema change. `switch_task` no longer targets `id = 1` on either the read or the write side. This is code-only; no schema migration is needed and Non-Goals still hold.

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
- Dashboard layout redesign beyond removing sentinel-derived header state. Slice 2c removes the single-sentinel-derived header fields and switches any per-task rendering to iterate currently-active rows; no other layout, ordering, or visual changes are in scope.
- Refactoring `CURRENT_TASK.json` into per-task files (separate follow-up).

## Slices

### Slice 1 — Audit and catalogue every singleton site

Three catalogues required. The audit must cover *every* write or write-adjacent handler that implicitly derives task scope, not just the guard/resolve pairings (addresses PLAN-02):

- **A. Sentinel reads (everywhere).** Grep `packages/agent-handoff-mcp/src/agent_handoff_mcp/` for `id = 1`, `id=1`, `WHERE id=1`, `handoff_state WHERE id`. Classify each hit: `read_active_as_pointer` (sentinel semantics — must be removed), `read_specific_row_by_id` (legitimate row lookup — keep), `write_upsert` (eviction path — remove). Known hits to cover explicitly: `import_export.py:949/1036` (switch_task), `shared_write_context.py:451` (guard fallback), `current_task_rendering.py:148` (activity CTE), `dashboard_rendering.py:542` (dashboard header active row), `review_findings.py:1876` (record_review_run implicit-task fallback).
- **B. Implicit-task write handlers.** Grep for `collect_target_context_warnings(` **OR** `_resolve_task_ref(` **OR** `handoff_state WHERE id = 1` inside write handlers. Record every handler that derives `task_ref` implicitly (from the sentinel, from the guard's side effects, or from an undocumented fallback) rather than requiring it as a parameter. `record_review_run` is a confirmed example — it runs the guard then falls back to `WHERE id = 1` to pick a task_ref, even though no `_resolve_task_ref` call appears. Every such handler must be redesigned to require explicit `task_ref` or workspace-derived resolution.
- **C. Caller ordering.** For every handler that calls both `collect_target_context_warnings(` and `_resolve_task_ref(`, record whether the guard runs before or after `task_ref` is resolved. Any site that calls the guard first is a bug.
- Output: single markdown artifact `docs/tasks/17.0/E17-11-catalogue.md` with three tables (A, B, C), each row naming file/line, classification, and the remediation slice that owns it.

### Slice 2 — Remove the sentinel: rewrite `switch_task` + migrate sentinel readers

Per the Greenfield Decision above, `switch_task` does not retain a sentinel pointer. Deliverables:

- **2a. Rewrite `switch_task`** (`import_export.py:923`). New semantics: "ensure a row exists for `task_ref`". Insert if missing, no-op if present, no archiving of any other row. Replace the singleton `SELECT ... WHERE id = 1` read (`:949`) with a `SELECT ... WHERE task_ref = ?` lookup. Replace the `UPDATE ... WHERE id = 1` upsert (`:1036`) with an INSERT-or-UPDATE keyed on `task_ref`. Drop `archived_previous`, `previous_task_ref` code paths entirely — they service the eviction pattern we're removing.
- **2b. Migrate `current_task_rendering.py:148`** (activity-anchor CTE). The CTE includes `handoff_state.updated_at` as an activity anchor. Change the branch that reads `FROM handoff_state WHERE id = 1` to `FROM handoff_state WHERE task_ref = ?` (bound to the requested task_ref parameter already threaded through the caller).
- **2c. Migrate `dashboard_rendering.py:542`** (dashboard header). The dashboard currently reads the sentinel to pick a single "active task" for the header. Since there is no longer a single active task, the dashboard is already a cross-task observatory. Remove the sentinel read and the `active_task_ref` / `target_branch` / `target_worktree_path` header values derived from it. Renderer surfaces that need per-task context (lane integrity, epic decisions, test status) switch to iterating all currently-active rows and rendering per-row.
- **2d. Migrate `review_findings.py:1876`** (`record_review_run` implicit fallback). Remove the `WHERE id = 1` fallback. If `task_ref` is not passed in, require it (return an error naming the caller) — do not silently bind to any sentinel.
- **2e. Delete dead code.** Remove any helper that existed only to service the sentinel. Examples expected: `archived_previous` bookkeeping in switch_task, any `get_active_task_ref()` helper that reads the sentinel.

Tests: two tasks coexist through a `switch_task` call; dashboard renders both; archive-restore still works for genuinely archived tasks (archive path is unchanged); `record_review_run` without `task_ref` returns an explicit error.

### Slice 3 — Thread task_ref through every write caller before any guard runs

This is the bug that blocks E17-10-style fixes. Three coordinated changes:

**Canonical unresolved-context rule (load-bearing; applies to Slice 3a, 3c, and the drift hook):** resolution order is (1) explicit `task_ref` parameter, (2) workspace-path lookup via `_resolve_workspace_handoff_row`. On neither match, the write path raises `UnresolvedTaskContextError` with a message naming both env vars to set (`AGENT_HANDOFF_TASK_REF`) and the expected workspace invariant. **No sentinel fallback anywhere. No warning-only no-op.** This rule is the single contract for every call site below.

- **a. Callee: make the guard task_ref-aware at every call site.** `collect_target_context_warnings` already accepts `task_ref` (since an earlier slice). The singleton fallback at `shared_write_context.py:451` is removed outright; the guard applies the canonical rule above and raises `UnresolvedTaskContextError` when neither explicit task_ref nor workspace lookup resolves. No code path falls back to `handoff_state WHERE id = 1` under any condition, including bootstrap.
- **b. Caller ordering: resolve task_ref first.** Every write handler that today calls `collect_target_context_warnings(conn, ctx)` before `_resolve_task_ref(conn, task_ref)` must be re-ordered. Confirmed sites so far: `review_findings.py:852/881`, and per Slice 1 audit all analogous call sites in `record_event`, `close_slice`, `set_handoff_state`, `update_task_status`, `handoff_close_check`. Each must pass the resolved task_ref into the guard.
- **c. Drift hook fallback.** When no task_ref can be extracted from tool input, the hook performs workspace-path lookup via `_resolve_workspace_handoff_row`. If that also fails, the hook raises `UnresolvedTaskContextError` with the same contract used in 3a. No sentinel fallback; no warning-only no-op.

### Slice 4 — Regression tests + docs update

- **Caller-ordering regression test.** Create two active rows (E17-A on feature/a, E17-B on feature/b). From a cwd on feature/b with no `target_worktree_path` match to row A, call `review_findings(update, task_ref='E17-B', ...)`. The update must succeed without a branch-enforcement rejection derived from row A's target_branch. This is the exact failure shape the user reported against E17-10.
- **switch_task regression test.** Two rows coexist before and after `switch_task`; previously-active row is not archived; archive-restore of a genuinely archived task still works.
- **Workspace-resolved drift test.** From a third cwd that matches neither row, the drift hook logs a warning instead of incorrectly binding to whichever row occupies the sentinel slot.
- Update `docs/agentic/maps/backend.md` to document the new semantics and reference `_resolve_workspace_handoff_row` as the preferred resolution path; add a "Write caller ordering" subsection under `docs/agentic/rules/backend-python-guidelines.md` that names the caller-first-then-guard pattern and the failure mode it prevents.

## Consolidated Checklist

- [ ] Slice 1a: sentinel-read catalogue complete (every `WHERE id = 1` hit).
- [ ] Slice 1b: implicit-task-handler catalogue complete (every write handler that derives `task_ref` from the sentinel or guard side effects, including `record_review_run`).
- [ ] Slice 1c: caller-ordering catalogue complete (every `collect_target_context_warnings` → `_resolve_task_ref` inversion).
- [ ] Slice 2a: `switch_task` rewritten; no archiving; task_ref-keyed insert/update; regression test added.
- [ ] Slice 2b: `current_task_rendering.py` activity-anchor CTE migrated off sentinel.
- [ ] Slice 2c: `dashboard_rendering.py` header migrated off sentinel; renders all active rows.
- [ ] Slice 2d: `record_review_run` requires explicit `task_ref` (no sentinel fallback).
- [ ] Slice 2e: dead sentinel-only helpers removed.
- [ ] Slice 3a: guard callee `WHERE id = 1` fallback removed in favour of workspace-resolved or explicit error.
- [ ] Slice 3b: every write caller resolves task_ref BEFORE invoking the guard; caller-ordering regression test green.
- [ ] Slice 3c: drift hook fallback walks workspace path; no sentinel fallback.
- [ ] Slice 4: multi-active e2e test green; caller-ordering regression test green; `switch_task` regression test green; `record_review_run` no-task_ref error test green; docs updated; lint rule in `check_harness_sync.py` flags any new sentinel reads.

## Risk / Rollback

Plan consumes a single feature branch. If regressions surface, revert the merge commit and the task can be re-planned. Archive/dashboard paths are high-impact — test coverage must gate each slice.

## References

- E17-7 Slice 2 introduced multi-active schema: `docs/tasks/17.0/E17-7-handoff-evolution-and-portable-workflow-task-plan.md`
- E17-8 S2 drift hook added workspace-resolved reads for the hook surface only
- User directive 2026-04-17 (session transcript): "multiple active task capability must be fixed even if it's a hot fix"

## Open Threads for Planning Review

**Resolved (above):**
- ~~Does `switch_task` retain a sentinel pointer?~~ **Resolved: no.** Greenfield + fresh DB for forks, so the sentinel is removed outright. See Greenfield Decision section.
- ~~`archive_previous=False` kwarg for backward compat?~~ **Resolved: no.** Eviction is a bug, not a feature; no flag needed.
- ~~`shared_write_context.py:451` sentinel fallback — keep or remove?~~ **Resolved: remove.** Guard returns empty warnings when no task_ref and no workspace context can be derived; it does not silently bind to a sentinel.

**Resolved (r3):**
- ~~Canonical unresolved-context rule for Slice 3~~ **Resolved: explicit task_ref → workspace lookup → `UnresolvedTaskContextError`.** No sentinel fallback, no warning-only no-op. This is now stated at the head of Slice 3 and applied by 3a, 3b, and 3c uniformly.
- ~~Mechanical prevention of the caller-ordering bug~~ **Resolved: (a)+(c).** The guard raises `UnresolvedTaskContextError` at runtime when called without resolvable context, and `scripts/check_harness_sync.py` adds a lint rule that flags any `collect_target_context_warnings(` call appearing before `_resolve_task_ref(` in the same function body.

**Still open for review:**
- Does the drift hook need a new `target_worktree_path → task_ref` lookup helper, or does `_resolve_workspace_handoff_row` suffice?
- Does the dashboard need a concept of "default task for this worktree" for operator UX (e.g. a single active-task summary at the top of `DASHBOARD.txt`), and if so is that derived from the invoking worktree's cwd at render time rather than stored anywhere? (Any affirmative answer is out of scope for this hot-fix per the narrowed Non-Goals bullet and would become a follow-on task.)
