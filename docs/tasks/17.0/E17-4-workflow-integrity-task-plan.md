# E17-4. Workflow Integrity and Session Continuity

- **Date**: 2026-04-14 08:00 EST
- **Author**: Claude Sonnet 4.6
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-4`
- **Review Coverage Target**: 2

---

## E17-4. Workflow Integrity and Session Continuity

## Objective

Close four failure classes that cause agent workflow discipline to degrade across sessions: orphan branches accumulate undetected, ad-hoc main-branch edits happen without handoff registration, cold-start agents reconstruct change state via raw git commands instead of querying handoff, and `make task-finish` has no post-archive branch-existence verification. When this task is complete, the workflow enforces logging at every edit, the handoff DB is the source of truth for what changed, and orphan detection is automated. Note: failure class #4 fix scope is limited to a post-archive warning in `make task-finish`; manual `archive_task_state` callers are out of scope.

## Problem Statement

Four failure classes confirmed in practice (investigation 2026-04-14):

1. **Orphan branches**: `feature/ahmcp-8-verified-test-search-and-read-surfaces` and `feature/slr-003-suppress-cleanup` exist locally with no active worktree and tasks archived from a different branch. `make context` and `make check-all` do not detect them. The convention is clear but enforcement is absent.

2. **Ad-hoc main edits without handoff**: The branch-isolation guard blocks code files on `main` but does not require an active handoff task before any edit. Docs, Makefiles, and configs accumulate uncommitted with no provenance. At investigation time: 8 files dirty on main with no active task.

3. **File-touch state gap**: Cold-start agents run `git diff --name-only` or `git log --name-only` to reconstruct what was changed. The handoff DB stores changed-file lists as free text inside `## Changes` sections of slice decisions — readable but not queryable as data. `load_session` returns no file-level change state.

4. **Branch-delete not part of invariant close**: `make task-finish` deletes the feature branch, but manually-triggered archives (called from main after a manual merge) leave `target_branch` dangling. No post-archive check enforces cleanup.

## Constraints

- `guard-main-branch.sh` hook changes must remain non-blocking for all permitted operations; the new check is a warning, not a hard block, for the initial rollout.
- AHMCP-29 (the MCP schema + tool additions) is a sub-task on a separate feature branch with its own tests. This task plan documents the dependency and the integration point; AHMCP-29 implements the MCP layer.
- `make worktree-audit` must run headlessly (no agent required) and exit non-zero on orphan detection.
- `make context` must remain fast (<1s) — worktree-audit output is printed only when dirty files exist; otherwise a one-line summary.
- No changes to the pre-merge gate logic or `handoff_close_check` behavior.

## Workflow Principles

- The maintenance-task pattern is a first-class registration mechanism, not a hack. Any ad-hoc main-branch change gets a task ref before the first edit.
- Warnings before hard blocks: for the first rollout, the main-change guard warns rather than rejects. Hard enforcement can be tightened once the pattern is established.
- Handoff is the source of truth for what changed, not git. `git diff` remains available as a fallback but `load_session` + `get_touched_files` should be sufficient for any cold-start agent.
- Orphan detection is automatic and non-interactive. Cleanup is manual (operator confirms before `git branch -d`).

## Terminology

- **Orphan branch**: a local branch matching `feature/*` or `codex/*` that has no corresponding `task_archives.archived_branch` or `handoff_state.target_branch` entry.
- **Maintenance task**: a lightweight handoff registration (`set_handoff_state(task_ref='MAINT-<slug>', ...)`) used before ad-hoc main-branch patches that do not warrant a full feature branch.
- **File-touch tracking**: structured recording of `(task_ref, file_path, change_kind)` tuples in handoff DB, queryable via `get_touched_files` and included in `load_session` response.

## Current State Analysis

- `scripts/hooks/guard-main-branch.sh` checks file path against allowed-on-main patterns; does not check whether an active handoff task is registered.
- `scripts/_task_finish_inline.py` calls `update_task_status`, `archive_task_state`, `generate_current_task_md`, `generate_dashboard_md` — no post-archive branch-delete verification.
- `make context` calls `scripts/check-task-context.py` which verifies branch + worktree path against active handoff state and already emits dirty-file warnings (`_git_dirty_paths`, `_emit_integrity_warning_if_dirty`) but does not output a maintenance-task registration hint when no active task is registered, and does not check for orphan branches.
- `make check-all` runs lint, tests, hooks validation — no branch audit.
- Handoff DB has no `touched_files` table. `load_session` returns identity + open findings; no file-level change state.
- Two orphan local branches confirmed: `feature/ahmcp-8-verified-test-search-and-read-surfaces`, `feature/slr-003-suppress-cleanup`.

## Target Outcome

- `make worktree-audit` exits 0 on clean and non-zero with an orphan list otherwise; runs in `make check-all`.
- `make context` on a dirty main with no active task prints: modified files + the maintenance-task registration command.
- The PreToolUse hook warns before any file edit when no active task is registered.
- `make task-finish` warns if the feature branch still exists after archive.
- `development-workflow.md` and `CLAUDE.md` document the maintenance-task pattern and branch-delete invariant.
- AHMCP-29 (separate feature branch): `touched_files` table, `record_file_touch`, `get_touched_files`, `load_session` includes file-touch list. PostToolUse hook auto-calls `record_file_touch` after Edit/Write.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md` § Invariant Close Sequence, § Branch Isolation
- Rules: `docs/agentic/rules/branch-review-guide.md`
- Contracts: `docs/agentic/contracts/` (no boundary changes expected)
- Code anchors: `scripts/hooks/guard-main-branch.sh`, `scripts/_task_finish_inline.py`, `scripts/check-task-context.py`, `Makefile`, `mk/handoff.mk`
- Handoff/MCP state: task ref `E17-4`, open findings after review passes

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
|---|---|---|---|---|---|
| `agent-handoff-mcp` Python API | `packages/agent-handoff-mcp/` | No `touched_files` table | AHMCP-29 adds table + 2 tools + `load_session` field | yes — additive; existing callers unaffected | AHMCP-29 test suite |
| PreToolUse hook | `scripts/hooks/guard-main-branch.sh` | Blocks code on main; silent otherwise | Adds warning when no active task | non-breaking — warning only | Manual: run hook with no active task + Edit call |
| `make context` output | `scripts/check-task-context.py` | Prints alignment status + dirty-file warning (already present) | Adds maintenance-task registration hint when no active task | non-breaking — additive output | `make context` on dirty main with no active task |

## Proposed Solution

Four slices delivering the four failure-class fixes independently. Slices 1–3 are scripts/Makefile/docs work on `feature/e17-4`. Slice 4 is AHMCP-29 (separate feature branch, spawned from this plan).

## Files and Surfaces to Change

| Surface | File | Change |
|---|---|---|
| Makefile target | `Makefile` | Add `worktree-audit` target; add to `check-all` |
| Audit script | `scripts/worktree_audit.py` | New: cross-reference git branches vs task_archives |
| PreToolUse hook | `scripts/hooks/guard-main-branch.sh` | Extend: warn when no active handoff task on any Edit/Write |
| Context check | `scripts/check-task-context.py` | Extend: add maintenance-task registration hint when main is dirty and no active task (dirty detection already present) |
| Task finish script | `scripts/_task_finish_inline.py` | Extend: after archive, check if target_branch still exists; warn |
| Workflow doc | `docs/agentic/rules/development-workflow.md` | Add: maintenance-task pattern, branch-delete invariant |
| CLAUDE.md | `CLAUDE.md` | Add: maintenance-task pattern rule, orphan-audit note |
| MCP package (AHMCP-29) | `packages/agent-handoff-mcp/` | `touched_files` table, `record_file_touch`, `get_touched_files`, `load_session` extension |
| Settings | `.claude/settings.json` | Add PostToolUse hook for `record_file_touch` after AHMCP-29 ships |

## Related Files

| File | Note |
|---|---|
| `scripts/check-task-context.py` | Context check — extend to add maintenance-task hint (dirty detection already exists) |
| `scripts/_task_finish_inline.py` | Task close — extend for post-archive branch-existence check |
| `scripts/_task_start_inline.py` | Not changed; branch creation already correct |
| `Makefile` | Root Makefile; add `worktree-audit` target |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | AHMCP-29 target; no changes in E17-4 scope |
| `.claude/settings.json` | PostToolUse hook added after AHMCP-29 ships |

## Verification Strategy

- Deterministic tests:
  - `python scripts/worktree_audit.py` exits 1 with orphan list when orphans present; exits 0 on clean
  - `make worktree-audit` exits non-zero; included in `make check-all`
  - `scripts/hooks/guard-main-branch.sh` called with no active task + simulated Edit event → prints warning
- Runtime-parity checks:
  - `make context` on dirty main with no active task → prints dirty file list + maintenance-task command
  - `make task-finish` after manual branch deletion already done → no warning; after archive without deletion → warning printed
- Manual verification:
  - Register `MAINT-test-1` task, edit a doc file on main, verify hook is silent; delete task, re-edit, verify warning
  - Run `make worktree-audit` on repo with known orphan branches; verify non-zero exit + list printed

## Slice Delivery

### Slice 1: Orphan Branch Audit

**Goal**: `make worktree-audit` detects and reports branches with no handoff registration; included in `make check-all`.

Changes:

- New `scripts/worktree_audit.py`: uses `git branch --list` to enumerate `feature/*` and `codex/*` local branches; queries `task_archives` and `handoff_state` via `agent_handoff_mcp.RuntimeConfig`; prints orphan list; exits 1 if any orphan found.
- New `make worktree-audit` target in root `Makefile`: `PYTHONPATH=... python scripts/worktree_audit.py`
- `make check-all` extended to include `make worktree-audit`

Proof:

- `make worktree-audit` exits 1 with `feature/ahmcp-8-verified-test-search-and-read-surfaces` listed
- After `git branch -d feature/ahmcp-8-verified-test-search-and-read-surfaces` and `git branch -d feature/slr-003-suppress-cleanup`: `make worktree-audit` exits 0

### Slice 2: Main-Change Guard and Context Improvement

**Goal**: Any Edit/Write with no active handoff task prints a warning; `make context` reports dirty-main state with registration hint.

Changes:

- `scripts/hooks/guard-main-branch.sh`: add check at end of allowed-edit path — if no active handoff task (query `get_handoff_state(sections='identity')` via Python), print warning block with the maintenance-task registration command. Non-blocking (exits 0 after warning).
- `scripts/check-task-context.py`: existing dirty-file warning already prints modified files; add a maintenance-task registration hint after the dirty warning when on main with no active task registered — print the `set_handoff_state(task_ref='MAINT-<slug>', ...)` command.
- `docs/agentic/rules/development-workflow.md`: add `§ Maintenance-Task Pattern` explaining the pattern and required invocation.
- `CLAUDE.md`: add under Critical Rules: "Before ANY file edit on `main` (including docs, Makefile, scripts), verify an active handoff task is registered. For ad-hoc patches use the maintenance-task pattern: `set_handoff_state(task_ref='MAINT-<slug>', objective='...')`. Unregistered edits will trigger a hook warning."

Proof:

- `make context` with no active task and dirty main prints: file list + maintenance-task hint
- Simulate Edit call with no active task: hook prints warning block; edit still proceeds
- `set_handoff_state(task_ref='MAINT-test')` then same Edit: hook is silent

### Slice 3: Branch-Delete Verification at Task Finish

**Goal**: `make task-finish` verifies the feature branch is gone after the full sequence completes; warns if it persists.

**Scope note**: `scripts/task-finish.sh` Step 4 deletes the feature branch (`git branch -d "$BRANCH"`) before Step 5 invokes `_task_finish_inline.py`. The check added here runs after archive and catches edge cases where Step 4's branch delete failed silently (e.g. unmerged commits preventing delete). Manual callers of `archive_task_state` that bypass `make task-finish` entirely are out of scope — they receive no warning regardless of branch state.

Changes:

- `scripts/_task_finish_inline.py`: after `archive_task_state` call, read `target_branch` from the now-archived task state; run `git branch --list <target_branch>`; if branch still exists, print warning: "Branch `<target_branch>` still exists after archive. Delete it: `git branch -d <target_branch>`". No-op on the normal path (branch already deleted by Step 4 of `task-finish.sh`).
- `docs/agentic/rules/development-workflow.md § Invariant Close Sequence`: add note: "If `target_branch != main`, `make task-finish` verifies the branch is deleted after archive as a belt-and-suspenders check. Manual archive callers must delete the branch themselves."

Proof:

- Run `make task-finish` for a task whose branch was already deleted at Step 4 → no warning (normal path)
- Simulate failed Step 4 (branch present when `_task_finish_inline.py` runs) → warning printed with the delete command

### Slice 4: File-Touch Tracking (AHMCP-29)

**Goal**: Handoff DB tracks which files each task touched; `load_session` returns the list at cold start.

> **Dependency**: This slice is implemented as **AHMCP-29** on a separate feature branch (`feature/ahmcp-29`). E17-4 is not complete until AHMCP-29 is merged. After AHMCP-29 ships, a follow-up commit on main adds the PostToolUse hook to `.claude/settings.json`.

Changes (AHMCP-29 scope):

- New `touched_files` table: `(id, task_ref, file_path, change_kind CHECK('edit','add','delete'), session, commit_sha, touched_at)`
- New `record_file_touch(task_ref, file_path, change_kind, [session, commit_sha])` MCP tool
- New `get_touched_files(task_ref)` MCP query → returns `[{file_path, change_kind, touched_at}]`
- `load_session` response extended: `touched_files` key with list for active task
- Tests: `test_record_file_touch`, `test_get_touched_files`, `test_load_session_includes_touched_files`

Changes (E17-4 follow-up, after AHMCP-29 merges):

- `.claude/settings.json`: add PostToolUse hook that calls `record_file_touch` after Edit/Write with the edited file path and `change_kind='edit'`

Proof:

- AHMCP-29: `cd packages/agent-handoff-mcp && make test-handoff` — new tests pass
- E17-4 follow-up: edit a file on main with active task → `get_touched_files(task_ref)` returns the file
- Cold-start test: register a task, edit two files, archive, start new session → `load_session` returns `touched_files` with both files without any `git diff` call

## Lane Decomposition (Multi-Agent)

Slices 1–3 are sequential single-lane work on `feature/e17-4`. Slice 4 (AHMCP-29) is a parallel sub-task on `feature/ahmcp-29` once the slice 1–3 work is merged or in review.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded `development-workflow.md § Invariant Close Sequence` and `guard-main-branch.sh` before editing.
- [ ] Confirmed AHMCP-29 is a separate sub-task; this plan documents the interface, not the implementation.
- [ ] No boundary contract changes in slices 1–3; AHMCP-29 owns the MCP boundary change.

### Checklist for Slice 1: Orphan Branch Audit

- [ ] `scripts/worktree_audit.py` written; queries handoff DB via RuntimeConfig; exits 1 on orphan
- [ ] `make worktree-audit` target added to Makefile
- [ ] `make check-all` includes `make worktree-audit`
- [ ] Proof: both known orphan branches detected; clean repo exits 0

### Checklist for Slice 2: Main-Change Guard and Context Improvement

- [ ] `guard-main-branch.sh` extended: warning block when no active task
- [ ] `check-task-context.py` extended: maintenance-task hint added when main is dirty and no active task (dirty-file list already present)
- [ ] `development-workflow.md § Maintenance-Task Pattern` added
- [ ] `CLAUDE.md` Critical Rules updated with maintenance-task requirement
- [ ] Proof: warning fires on unregistered edit; silent with registered task

### Checklist for Slice 3: Branch-Delete Verification at Task Finish

- [ ] `_task_finish_inline.py` extended: post-archive branch-existence check (belt-and-suspenders; no-op on normal `make task-finish` path)
- [ ] `development-workflow.md § Invariant Close Sequence` note added; manual archive scope limitation documented
- [ ] Proof: no warning on normal path (branch deleted at Step 4); warning fires when branch persists after Step 4 failure

### Checklist for Slice 4: File-Touch Tracking (AHMCP-29)

- [ ] AHMCP-29 task scoped and `set_handoff_state` registered
- [ ] AHMCP-29 merged: `touched_files` table, `record_file_touch`, `get_touched_files`
- [ ] AHMCP-29 merged: `load_session` includes `touched_files`
- [ ] PostToolUse hook added to `.claude/settings.json` after AHMCP-29 ships
- [ ] Cold-start test passes: `load_session` returns touched files without `git diff`

## Review Readiness

- [ ] Slice 1: `make worktree-audit` exits 0 on clean repo; CI does not break on `make check-all`
- [ ] Slice 2: hook and context changes are non-breaking; no existing tests fail
- [ ] Slice 3: `_task_finish_inline.py` change is backward-compatible when branch already deleted
- [ ] AHMCP-29 has its own pre-merge gate; no E17-4 code depends on AHMCP-29 internals

## Stretch Goals

- [ ] `make worktree-prune` interactive target: for each orphan branch, prompt before `git branch -d`
- [ ] `record_file_touch` backfill: parse existing slice decisions' `## Changes` sections and insert historical touch records

## Success Criteria

- [ ] `make check-all` exits 0 on clean repo; exits 1 with orphan list when orphan branches exist
- [ ] Any agent starting a session on dirty main sees the dirty-file list and maintenance-task hint without running `git diff`
- [ ] `load_session` (post AHMCP-29) returns `touched_files` for the active task — no `git diff` needed at cold start
- [ ] `development-workflow.md` and `CLAUDE.md` contain actionable, testable rules for the maintenance-task pattern and branch-delete invariant
