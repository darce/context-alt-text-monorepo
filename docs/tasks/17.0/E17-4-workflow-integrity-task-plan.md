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

5. **Startup cascade cancellation**: When an agent batches `make context` and `ToolSearch` in the same parallel message, `make context` exits non-zero (exit 2) on drift. The Claude Code runtime cancels all other parallel tool calls in the group. The agent loses MCP tool access and falls back to raw git — then fabricates SHA suffixes from abbreviated `git log` output, poisoning handoff decision provenance.

6. **Missing task plans for merged commits**: Commits tagged `feat(AHMCP-N):` or `feat(E17-N):` have landed on `main` with no corresponding task plan file (AHMCP-26, AHMCP-28 confirmed; AHMCP-29 unmerged but unregistered). `make check-all` and the pre-merge gate do not verify that a task plan exists before merge.

7. **MCP write branch enforcement absent**: `shared_write_context.py` detects actor branch / worktree drift and emits it as a non-fatal warning, but still completes the write. Decision #1701 (`cdx_slice_complete_E17-4_workflow_integrity_audits`) is durable proof: recorded with `branch=main` / `commit_sha=befbdce8` while the active task targets `feature/e17-4`. Warning-only drift detection is insufficient when the target is audit-trail integrity; an agent that ignores the warning silently corrupts provenance.

8. **Host-specific command surfaces drift**: `/branch-review` and `/planning-review` exist today as Claude-only wrappers in `.claude/commands/`. VS Code/Copilot has no matching workspace prompt files in `.github/prompts/`, and Codex has MCP attachment plus root instructions but no native command registry. The same workflow is therefore invoked three different ways: Claude gets slash discovery, VS Code relies on prose triggers, and Codex relies on instruction routing only. A portable workflow surface needs one canonical command definition and generated host adapters so command ids, argument names, and execution semantics stay uniform.

## Constraints

- `guard-main-branch.sh` hook changes must remain non-blocking for all permitted operations; the new check is a warning, not a hard block, for the initial rollout.
- AHMCP-31 (the MCP schema + tool additions) is a sub-task on a separate feature branch with its own tests. This task plan documents the dependency and the integration point; AHMCP-31 implements the MCP layer. (AHMCP-29 was reassigned — it implemented `archived_previous` in `switch_task`, merged at `befbdce8`.)
- `make worktree-audit` must run headlessly (no agent required) and exit non-zero on orphan detection.
- `make context` must remain fast (<1s) — worktree-audit output is printed only when dirty files exist; otherwise a one-line summary.
- No changes to the pre-merge gate logic or `handoff_close_check` behavior.
- Workflow command syntax must be defined once and rendered uniformly across Claude, VS Code/Copilot, and Codex. Host adapter files may differ, but command ids, argument names, and skill/make-target bindings must come from one canonical manifest.

## Workflow Principles

- The maintenance-task pattern is a first-class registration mechanism, not a hack. Any ad-hoc main-branch change gets a task ref before the first edit.
- Warnings before hard blocks: for the first rollout, the main-change guard warns rather than rejects. Hard enforcement can be tightened once the pattern is established.
- Handoff is the source of truth for what changed, not git. `git diff` remains available as a fallback but `load_session` + `get_touched_files` should be sufficient for any cold-start agent.
- Orphan detection is automatic and non-interactive. Cleanup is manual (operator confirms before `git branch -d`).
- Portable workflow commands are defined once and adapted per host. `.claude/commands/`, `.github/prompts/`, and Codex instruction routing are mirrors of the same manifest, not hand-maintained parallel sources.

## Terminology

- **Orphan branch**: a local branch matching `feature/*` or `codex/*` that has no corresponding active `handoff_state.target_branch` or archived task snapshot `target_branch` entry. Archive metadata fields such as `archived_branch` are not authoritative for feature-branch ownership.
- **Maintenance task**: a lightweight handoff registration (`set_handoff_state(task_ref='MAINT-<slug>', ...)`) used before ad-hoc main-branch patches that do not warrant a full feature branch.
- **File-touch tracking**: structured recording of `(task_ref, file_path, change_kind)` tuples in handoff DB, queryable via `get_touched_files` and included in `load_session` response.
- **Portable workflow surface**: the repo-owned set of workflow command ids (for example `/branch-review`, `/planning-review`) plus their argument schema, owning skill, and Makefile entry point. This is the canonical source that every host adapter renders.
- **Host adapter**: a harness-specific wrapper generated from the portable workflow surface, such as `.claude/commands/*.md` for Claude, `.github/prompts/*.prompt.md` for VS Code/Copilot, or the command-routing section in the root instruction surface for Codex.

## Current State Analysis

- `scripts/hooks/guard-main-branch.sh` checks file path against allowed-on-main patterns; does not check whether an active handoff task is registered.
- `scripts/_task_finish_inline.py` calls `update_task_status`, `archive_task_state`, `generate_current_task_md`, `generate_dashboard_md` — no post-archive branch-delete verification.
- `make context` calls `scripts/check-task-context.py` which verifies branch + worktree path against active handoff state and emits dirty-file warnings only on the active-task path (`_git_dirty_paths`, `_emit_integrity_warning_if_dirty`). On the no-active-task path it currently returns early with "No active handoff task. Nothing to check." and does not print the dirty file list, maintenance-task hint, or orphan-branch audit.
- `make check-all` runs lint, tests, hooks validation — no branch audit.
- Handoff DB has no `touched_files` table. `load_session` returns identity + open findings; no file-level change state.
- One orphan local branch currently confirmed: `feature/slr-003-suppress-cleanup`. The earlier `feature/ahmcp-8-verified-test-search-and-read-surfaces` orphan was already deleted; the cleanup requirement remains the same for any remaining or newly-detected orphan branches.
- `.claude/commands/branch-review.md` and `.claude/commands/planning-review.md` exist as Claude-only slash adapters. `.github/prompts/` is empty, so VS Code/Copilot has no workspace-native slash entry points for the same workflows.
- Codex currently discovers the repo via `CLAUDE.md` / `docs/agentic/instructions.md` and `.codex/config.toml`, but it has no generated command registry. `/branch-review` syntax is therefore only reliable if the root instruction surface manually routes it.

## Target Outcome

- `make worktree-audit` exits 0 on clean and non-zero with an orphan list otherwise; runs in `make check-all`.
- `make context` on a dirty main with no active task prints: modified files + the maintenance-task registration command.
- The PreToolUse hook warns before any file edit when no active task is registered.
- `make task-finish` warns if the feature branch still exists after archive.
- `development-workflow.md` and `CLAUDE.md` document the maintenance-task pattern and branch-delete invariant.
- AHMCP-31 (separate feature branch): `touched_files` table, `record_file_touch`, `get_touched_files`, `load_session` includes file-touch list. PostToolUse hook auto-calls `record_file_touch` after Edit/Write.
- `make context` exits 0 on drift; drift info remains in stdout. Cascade cancellation of parallel ToolSearch calls is eliminated.
- `agent-handoff-mcp` SHA validation already ships `InvalidCommitShaError` in `shared_write_context.py` — no new ticket needed.
- `make task-plan-audit` exits non-zero when a tagged commit on `main` has no corresponding plan file; integrated into `make check-all`.
- `/branch-review`, `/planning-review`, and the rest of the workflow command ids are defined once and exposed uniformly across Claude, VS Code/Copilot, and Codex.
- `make check-agent-workflows` fails when generated host adapters drift from the canonical workflow manifest.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md` § Invariant Close Sequence, § Branch Isolation
- Rules: `docs/agentic/rules/branch-review-guide.md`
- Contracts: `docs/agentic/contracts/` (no boundary changes expected)
- Code anchors: `scripts/hooks/guard-main-branch.sh`, `scripts/_task_finish_inline.py`, `scripts/check-task-context.py`, `Makefile`, `mk/handoff.mk`
- Handoff/MCP state: task ref `E17-4`, open findings after review passes

## Contract and Boundary Impact

| Boundary                       | Owner                                                           | Current Contract                                                                                          | Expected Change                                                                                                                            | Compatibility Needed?                             | Verification                                                                                  |
| ------------------------------ | --------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `agent-handoff-mcp` Python API | `packages/agent-handoff-mcp/`                                   | No `touched_files` table                                                                                  | AHMCP-31 adds table + 2 tools + `load_session` field                                                                                       | yes — additive; existing callers unaffected       | AHMCP-31 test suite                                                                           |
| PreToolUse hook                | `scripts/hooks/guard-main-branch.sh`                            | Blocks code on main; silent otherwise                                                                     | Adds warning when no active task                                                                                                           | non-breaking — warning only                       | Manual: run hook with no active task + Edit call                                              |
| `make context` output          | `scripts/check-task-context.py`                                 | Prints alignment status; dirty-file warning exists only on the active-task path today                     | On the no-active-task path, add both the dirty-file warning and the maintenance-task registration hint                                     | non-breaking — additive output                    | `make context` on dirty main with no active task                                              |
| Portable workflow surface      | `config/agent-workflows/portable_commands.json` + host adapters | Claude-only `.claude/commands/*`; no VS Code workspace prompts; Codex relies on prose instruction routing | Canonical manifest generates `.claude/commands/*` and `.github/prompts/*`, while root instructions route the same `/command` ids for Codex | yes — additive; existing `/command` ids preserved | `make check-agent-workflows`; smoke test `/branch-review` and `/planning-review` on each host |

## Proposed Solution

Eight slices deliver the workflow-integrity fixes without overloading a single change surface. Slices 1–3 are scripts/Makefile/docs work on `feature/e17-4`. Slice 4 is AHMCP-31 (separate feature branch, spawned from this plan). Slices 5–8 close the observed startup, plan-audit, branch-enforcement, and host-adapter portability gaps.

## Files and Surfaces to Change

| Surface                      | File                                                                       | Change                                                                                                                                  |
| ---------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| Makefile target              | `Makefile`                                                                 | Add `worktree-audit` target; add to `check-all`                                                                                         |
| Audit script                 | `scripts/worktree_audit.py`                                                | New: cross-reference git branches vs archived/current handoff state through MCP/Python API helpers (no raw sqlite3)                     |
| PreToolUse hook              | `scripts/hooks/guard-main-branch.sh`                                       | Extend: warn when no active handoff task on any Edit/Write                                                                              |
| Context check                | `scripts/check-task-context.py`                                            | Extend the no-active-task path to emit the dirty-file warning first, then add the maintenance-task registration hint when main is dirty |
| Task finish script           | `scripts/_task_finish_inline.py`                                           | Extend: after archive, check if target_branch still exists; warn                                                                        |
| Workflow doc                 | `docs/agentic/rules/development-workflow.md`                               | Add: maintenance-task pattern, branch-delete invariant                                                                                  |
| CLAUDE.md                    | `CLAUDE.md`                                                                | Add: maintenance-task pattern rule, orphan-audit note                                                                                   |
| MCP package (AHMCP-31)       | `packages/agent-handoff-mcp/`                                              | `touched_files` table, `record_file_touch`, `get_touched_files`, `load_session` extension                                               |
| Settings                     | `.claude/settings.json`                                                    | Add PostToolUse hook for `record_file_touch` after AHMCP-31 ships                                                                       |
| Context check                | `scripts/check-task-context.py`                                            | Change drift exit from `sys.exit(2)` to `sys.exit(0)` — drift is informational, not fatal                                               |
| Instructions                 | `CLAUDE.md` (Agent Startup Protocol)                                       | Add explicit no-parallel-batch rule: `make context` must run alone before any ToolSearch/MCP load                                       |
| MCP package (SHA validation) | `packages/agent-handoff-mcp/`                                              | Already shipped — `InvalidCommitShaError` + `_validate_and_expand_commit_sha` in `shared_write_context.py`                              |
| Audit script                 | `scripts/task_plan_audit.py`                                               | New: parse `git log main` for `feat(AHMCP-N):` / `feat(E17-N):` patterns; cross-reference against task plan directories; exit 1 on gap  |
| Makefile target              | `Makefile`                                                                 | Add `task-plan-audit` target; add to `check-all`                                                                                        |
| MCP write guard (AHMCP-32)   | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` | Promote context_drift from warning to optional hard block via `AGENT_HANDOFF_ENFORCE_BRANCH=1` env var; add `BranchMismatchError`       |
| Canonical workflow manifest  | `config/agent-workflows/portable_commands.json`                            | New: define stable `/command` ids, argument names, owning skills, Makefile entry points, and execution context once                     |
| Adapter generator            | `scripts/generate_agent_workflows.py`                                      | New: render Claude command files and VS Code prompt files from the canonical manifest; validate uniform syntax                          |
| Claude adapter surface       | `.claude/commands/*.md`                                                    | Generated mirrors; no hand-edited workflow semantics                                                                                    |
| VS Code adapter surface      | `.github/prompts/*.prompt.md`                                              | New generated workspace prompt files so Copilot Chat exposes the same `/command` ids                                                    |
| Codex router                 | `docs/agentic/instructions.md` + `CLAUDE.md`                               | Add portable command-routing section so the same `/command` ids are honored in Codex sessions without a native prompt registry          |
| Validation target            | `Makefile`                                                                 | Add `generate-agent-workflows` / `check-agent-workflows`; wire drift check into `make check-all` or `make check-skills`                 |

## Related Files

| File                                                      | Note                                                                                                         |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `scripts/check-task-context.py`                           | Context check — extend the no-active-task path to emit the dirty-file warning plus the maintenance-task hint |
| `scripts/_task_finish_inline.py`                          | Task close — extend for post-archive branch-existence check                                                  |
| `scripts/_task_start_inline.py`                           | Not changed; branch creation already correct                                                                 |
| `Makefile`                                                | Root Makefile; add `worktree-audit` target                                                                   |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | AHMCP-31 target; no changes in E17-4 scope                                                                   |
| `.claude/settings.json`                                   | PostToolUse hook added after AHMCP-31 ships                                                                  |
| `config/agent-workflows/portable_commands.json`           | Canonical host-agnostic workflow command contract                                                            |
| `.github/prompts/*.prompt.md`                             | VS Code/Copilot workspace-native slash surface generated from the canonical contract                         |

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

- New `scripts/worktree_audit.py`: uses `git branch --list` to enumerate `feature/*` and `codex/*` local branches; queries archived/current task state through the `agent_handoff_mcp` Python API (for example `get_handoff_state(... include_archived=True ...)` / archived-task helpers) rather than raw sqlite3; prints orphan list; exits 1 if any orphan found.
- New `make worktree-audit` target in root `Makefile`: `PYTHONPATH=... python scripts/worktree_audit.py`
- Delete any known orphan branches in the same commit as, or before, wiring `make worktree-audit` into `make check-all` so CI does not fail immediately on already-known local orphan state.
- `make check-all` extended to include `make worktree-audit`

Proof:

- `make worktree-audit` exits 1 with `feature/slr-003-suppress-cleanup` listed (plus any other real orphan detected at runtime)
- After deleting the remaining orphan branch(es): `make worktree-audit` exits 0

### Slice 2: Main-Change Guard and Context Improvement

**Goal**: Any Edit/Write with no active handoff task prints a warning; `make context` reports dirty-main state with registration hint.

Changes:

- `scripts/hooks/guard-main-branch.sh`: add check at end of allowed-edit path — if no active handoff task (query `get_handoff_state(sections='identity')` via Python), print warning block with the maintenance-task registration command. Non-blocking (exits 0 after warning).
- `scripts/check-task-context.py`: on the no-active-task path, call `_emit_integrity_warning_if_dirty()` before returning, then add a maintenance-task registration hint after that dirty warning when on main with no active task registered — print the `set_handoff_state(task_ref='MAINT-<slug>', ...)` command.
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

- `scripts/_task_finish_inline.py`: capture `target_branch` from `active_row` (already fetched via `get_handoff_state(sections="identity")`) before the archive call, then after `archive_task_state` run `git branch --list <target_branch>`; if branch still exists, print warning: "Branch `<target_branch>` still exists after archive. Delete it: `git branch -d <target_branch>`". No-op on the normal path (branch already deleted by Step 4 of `task-finish.sh`).
- `docs/agentic/rules/development-workflow.md § Invariant Close Sequence`: add note: "If `target_branch != main`, `make task-finish` verifies the branch is deleted after archive as a belt-and-suspenders check. Manual archive callers must delete the branch themselves."

Proof:

- Run `make task-finish` for a task whose branch was already deleted at Step 4 → no warning (normal path)
- Simulate failed Step 4 (branch present when `_task_finish_inline.py` runs) → warning printed with the delete command

### Slice 4: File-Touch Tracking (AHMCP-31)

**Goal**: Handoff DB tracks which files each task touched; `load_session` returns the list at cold start.

> **Dependency**: This slice is implemented as **AHMCP-31** on a separate feature branch. `feature/ahmcp-29` was reassigned — it implemented the `archived_previous` flag in `switch_task` (merged at `befbdce8`) and is unrelated to file-touch tracking. E17-4 is not complete until AHMCP-31 is merged. After AHMCP-31 ships, follow-up commits wire the PostToolUse hook into both `.claude/settings.json` and `.github/hooks/terminal-guard.json` so Claude Code and the VS Code/Copilot terminal surface record file touches consistently.

Changes (AHMCP-31 scope):

- New `touched_files` table: `(id, task_ref, file_path, change_kind CHECK('edit','add','delete'), session, commit_sha, touched_at)`
- New `record_file_touch(task_ref, file_path, change_kind, [session, commit_sha])` MCP tool
- New `get_touched_files(task_ref)` MCP query → returns `[{file_path, change_kind, touched_at}]`
- `load_session` response extended: `touched_files` key with list for active task
- Tests: `test_record_file_touch`, `test_get_touched_files`, `test_load_session_includes_touched_files`

Changes (E17-4 follow-up, after AHMCP-31 merges):

- `.claude/settings.json`: add PostToolUse hook that calls `record_file_touch` after Edit/Write. `Edit` events record `change_kind='edit'`; `Write` records `change_kind='add'` when the target path did not previously exist and `change_kind='edit'` otherwise.
- `.github/hooks/terminal-guard.json`: add the matching PostToolUse wiring for the VS Code/Copilot hook surface so the same edit events record file touches outside Claude Code sessions, using the same `Edit`/`Write` distinction. File deletion remains out of scope for this hook surface; `change_kind='delete'` is reserved for future manual or dedicated hook coverage.

Proof:

- AHMCP-31: `cd packages/agent-handoff-mcp && make test-handoff` — new tests pass
- E17-4 follow-up: edit a file on main with active task from either hook surface → `get_touched_files(task_ref)` returns the file
- E17-4 follow-up: create a new file through the `Write` path → `get_touched_files(task_ref)` records `change_kind='add'`
- Cold-start test: register a task, edit two files, archive, start new session → `load_session` returns `touched_files` with both files without any `git diff` call

### Slice 5: Startup Cascade Prevention

**Goal**: `make context` drift never cancels a parallel ToolSearch or MCP tool call; `agent-handoff-mcp` rejects fabricated SHAs before they corrupt decision provenance.

**Root cause**: `make context` exits 2 on drift. The Claude Code runtime cancels all parallel tool calls when any one errors. Agents that batch `make context` + `ToolSearch` in the same message lose MCP access, fall back to raw git, and type SHA suffixes from memory — producing fabricated 40-char hashes that the current validation path fails to reject.

Changes:

- `scripts/check-task-context.py`: change drift exit from `sys.exit(2)` to `sys.exit(0)`. Drift info is complete in stdout; no downstream script consumes the exit code for drift detection. **Breaking for any caller that relied on exit 2 to detect drift programmatically** — none identified at time of writing.
- `CLAUDE.md` Agent Startup Protocol: add rule: "Run `make context` in a standalone Bash call. Never batch it with ToolSearch or MCP tool loads in the same parallel message. Proceed to MCP load regardless of `make context` output."

> **SHA validation already shipped**: `shared_write_context.py` already implements `InvalidCommitShaError`, `_validate_and_expand_commit_sha`, and `_commit_sha_validation_enabled()` — wired into `decisions.py` and `review_findings.py` write paths. AHMCP-30 sub-ticket is not needed. The fabricated-SHA incidents in session history were caused by agents typing suffixes from memory before the validation layer was in place; new writes are rejected correctly.

Proof:

- `make context` in a drifted shell exits 0; stdout contains the full drift warning block
- Batch `Bash(make context)` + `ToolSearch(load_session)` in one parallel message on a drifted shell: ToolSearch completes; no cancellation
- SHA validation already verified: `record_event(actor={commit_sha: "<fabricated-40-char>"})` → `InvalidCommitShaError` (existing behaviour, no new work needed)

### Slice 6: Task-Plan Audit

**Goal**: `make task-plan-audit` detects commits on `main` that carry a structured task tag (`feat(AHMCP-N):`, `feat(E17-N):`, `fix(AHMCP-N):`, etc.) but have no corresponding plan file; integrated into `make check-all`.

**Root cause**: The pre-merge gate validates findings and test evidence but never checks for the existence of a task plan file. Agents can merge code under a task tag without ever writing a plan. This gap was previously confirmed for AHMCP-26 and AHMCP-28, and AHMCP-27 already demonstrated the need for retroactive backfill. As of this review pass, the AHMCP-26 and AHMCP-28 retroactive plans now exist in `packages/agent-handoff-mcp/docs/tasks/`; the audit still needs to prevent the next recurrence and should verify current history instead of hard-coding those tasks as open gaps.

Changes:

- `scripts/task_plan_audit.py`: new script. Parses `git log --format="%s" main` for subject lines matching `(feat|fix|docs|refactor|test)\((AHMCP|E\d+)-(\d+)\):`. For each unique task ID found, checks the canonical plan directory (`packages/agent-handoff-mcp/docs/tasks/` for AHMCP-N, `docs/tasks/` for E-N tasks) for any file matching `<PREFIX>-<N>-*.md`. Prints a gap list and exits 1 if any tagged task has no plan file. Exits 0 on clean. Uses only stdlib + subprocess for `git log`; no agent-handoff-mcp dependency.
- `make task-plan-audit` target in root `Makefile`.
- `make check-all` extended to include `make task-plan-audit`.
- Before wiring `make task-plan-audit` into `make check-all`, run the audit against current `main` history and either commit any newly-discovered retroactive plan files or narrow the audit scope if older legacy tags are intentionally exempted. The existing AHMCP-26 and AHMCP-28 plan files satisfy the currently-known backfill requirement.

Proof:

- `make task-plan-audit` exits 1 when a tagged task on `main` has no corresponding plan file
- With the current retroactive plan set committed (including AHMCP-26 and AHMCP-28): `make task-plan-audit` exits 0
- New tagged commit on main without a plan file → `make check-all` fails

### Slice 7: MCP Write Branch Enforcement (AHMCP-32)

**Goal**: `agent-handoff-mcp` blocks writes whose actor branch does not match the active task's `target_branch`, eliminating silent provenance corruption at the source.

**Root cause**: `_build_shared_write_context` in `shared_write_context.py` appends `context_drift` to the warnings list but still completes the write. An agent that ignores the warning (or doesn't read the response envelope) stores a durable, wrong branch attribution. Warning-only is insufficient; drift must be a gate when the task has an explicit non-main `target_branch`.

**Scope**: `agent-handoff-mcp` package change → implement as **AHMCP-32** on a separate feature branch. E17-4 follow-up (after AHMCP-32 ships): set `AGENT_HANDOFF_ENFORCE_BRANCH=1` in the Claude Code shell environment.

Changes (AHMCP-32 scope):

- `shared_write_context.py`: add `_branch_enforcement_enabled() → bool` reading env var `AGENT_HANDOFF_ENFORCE_BRANCH`. Add `BranchMismatchError(task_ref, expected_branch, actor_branch)` exception. In `_build_shared_write_context`, when drift is detected on a task whose `target_branch` is non-null and not in `{"main", "master"}` and enforcement is enabled: raise `BranchMismatchError` before any DB write. Default (enforcement off): current warning-only behaviour preserved.
- `__init__.py`: export `BranchMismatchError`.
- `tests/conftest.py`: set `AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT=1` alongside the existing `AGENT_HANDOFF_SKIP_SHA_VALIDATION=1` so existing tests are unaffected.
- Tests: `test_write_blocked_on_branch_mismatch` — set `AGENT_HANDOFF_ENFORCE_BRANCH=1`, attempt `record_decision` from wrong branch → `BranchMismatchError`; `test_write_warns_only_by_default` — default env → write succeeds with `context_drift` warning.

Changes (E17-4 follow-up, after AHMCP-32 ships):

- Shell / Claude Code session: `export AGENT_HANDOFF_ENFORCE_BRANCH=1` added to the dev environment. Document in `CLAUDE.md` alongside the SHA validation note: "MCP write operations are blocked when the actor branch does not match the active task's `target_branch`. Switch to the canonical worktree before recording decisions, findings, or test results."

Proof:

- AHMCP-32: `cd packages/agent-handoff-mcp && make test-handoff` — new tests pass, existing tests unaffected
- E17-4 follow-up: attempt `record_event` from a drifted shell with enforcement on → `BranchMismatchError` in response; write not stored; operator sees which branch/worktree is expected
- Correct worktree: `record_event` from `feature/e17-4` worktree → succeeds; no drift warning

### Slice 8: Portable Workflow Surface Across Claude, VS Code, and Codex

**Goal**: the same workflow command ids and argument syntax work across all supported agent harnesses; host-specific wrappers become generated adapters instead of hand-maintained sources.

**Root cause**: Phase 2 created `.claude/commands/*.md` and described them as the invocation surface, but that only covers Claude. VS Code/Copilot uses `.github/prompts/*.prompt.md` for workspace-native slash discovery and currently has no matching files. Codex has MCP attachment plus root instructions, but no native slash registry, so `/branch-review` only works when the root instruction prose happens to route it. The workflow ids are portable in theory, not in the checked-in host adapters. **Addendum (E17-12 Slice 2)**: `$skill` resolution is now delivered in Codex via generated `.codex/skills/<slug>` symlinks pointing at `.claude/skills/<slug>`, emitted by `scripts/generate_agent_workflows.py`; `/command` routing in Codex still relies on the generator-owned router block in `instructions.md` and `CLAUDE.md`.

Changes:

- New canonical manifest `config/agent-workflows/portable_commands.json`: one entry per portable workflow command (`branch-review`, `planning-review`, `plan-analyze`, `branch-lifecycle`, `handoff-lifecycle`, `tdd`, `incremental-implementation`, and any future additions). Each entry declares: `command_id`, `skill`, `makefile_target`, `description`, `argument_schema`, and `execution_context`.
- New generator `scripts/generate_agent_workflows.py`: reads the manifest and renders:
  - `.claude/commands/<command_id>.md`
  - `.github/prompts/<command_id>.prompt.md`
    Both outputs are generated mirrors of the same command contract; no host-specific workflow logic is allowed in the generated files.
- `docs/agentic/instructions.md` and `CLAUDE.md`: add a portable command-router section for hosts without a native prompt registry. Rule: if the user prompt begins with a registered `/command_id`, load the mapped skill and treat the remainder of the message using the manifest-defined argument names. This is the Codex adapter, preserving the same slash syntax even though Codex lacks `.github/prompts/` discovery.
- `Makefile`: add `generate-agent-workflows` (writes adapters) and `check-agent-workflows` (regenerates to a temp dir or dry-run diff and exits non-zero on drift). Wire `check-agent-workflows` into `make check-all` or `make check-skills` so adapter drift is caught before merge.
- `scripts/generate_agent_workflows.py`: validate `portable_commands.json` structurally at load time before rendering adapters. Invalid or incomplete manifest entries fail fast with a descriptive error before any generated file is written.
- Documentation cleanup: Phase 2 language that calls `.claude/commands/` the "agent-agnostic invocation surface" is corrected. The agent-agnostic surface becomes the canonical workflow manifest plus the stable `/command_id` syntax; `.claude/commands/` and `.github/prompts/` are host adapters.

Proof:

- Claude: `/branch-review` and `/planning-review` resolve through generated `.claude/commands/*.md` with no hand-edited divergence from the manifest.
- VS Code/Copilot: `/branch-review` and `/planning-review` appear in slash discovery from generated `.github/prompts/*.prompt.md` files and invoke the same skills with the same argument names.
- Codex: a prompt beginning with `/branch-review` or `/planning-review` is routed by the root instruction surface to the same skill and Makefile target mapping defined in the manifest; no Claude-only fallback path is required.
- `make check-agent-workflows` exits non-zero when any generated adapter drifts from `portable_commands.json`.
- Invalid `portable_commands.json` structure causes `scripts/generate_agent_workflows.py` to fail before any adapter output is written.

## Lane Decomposition (Multi-Agent)

Slices 1–3 are sequential single-lane work on `feature/e17-4`. Slice 4 (AHMCP-31) and Slice 7 (AHMCP-32) are parallel sub-tasks on their own feature branches, spawned after slice 1–3 work is merged or in review. `feature/ahmcp-29` was reassigned; its `archived_previous` work was merged at `befbdce8`.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded `development-workflow.md § Invariant Close Sequence` and `guard-main-branch.sh` before editing.
- [x] Confirmed AHMCP-31 is a separate sub-task; this plan documents the interface, not the implementation.
- [x] No boundary contract changes in slices 1–3; AHMCP-31 owns the MCP boundary change.

### Checklist for Slice 1: Orphan Branch Audit

- [x] `scripts/worktree_audit.py` written; queries handoff DB via RuntimeConfig; exits 1 on orphan
- [x] `make worktree-audit` target added to Makefile
- [x] `make check-all` includes `make worktree-audit`
- [x] Delete known orphan branches before or alongside the commit that wires `make worktree-audit` into `make check-all`
- [x] Proof: the currently known orphan branch(es) are detected; clean repo exits 0 after deletion

### Checklist for Slice 2: Main-Change Guard and Context Improvement

- [x] `guard-main-branch.sh` extended: warning block when no active task
- [x] `check-task-context.py` extended: maintenance-task hint added when main is dirty and no active task (dirty-file list already present)
- [x] `development-workflow.md § Maintenance-Task Pattern` added
- [x] `CLAUDE.md` Critical Rules updated with maintenance-task requirement
- [x] Proof: warning fires on unregistered edit; silent with registered task

### Checklist for Slice 3: Branch-Delete Verification at Task Finish

- [x] `_task_finish_inline.py` extended: post-archive branch-existence check (belt-and-suspenders; no-op on normal `make task-finish` path)
- [x] `development-workflow.md § Invariant Close Sequence` note added; manual archive scope limitation documented
- [x] Proof: no warning on normal path (branch deleted at Step 4); warning fires when branch persists after Step 4 failure

### Checklist for Slice 4: File-Touch Tracking (AHMCP-31)

- [x] AHMCP-31 task scoped and `set_handoff_state` registered
- [x] AHMCP-31 merged: `touched_files` table, `record_file_touch`, `get_touched_files`
- [x] AHMCP-31 merged: `load_session` includes `touched_files`
- [x] PostToolUse hook added to `.claude/settings.json` after AHMCP-31 ships
- [x] PostToolUse hook distinguishes `Edit` (`edit`) from new-file `Write` (`add`); `delete` remains explicitly out of scope for this hook surface
- [x] Cold-start test passes: `load_session` returns touched files without `git diff`

### Checklist for Slice 5: Startup Cascade Prevention

- [x] `check-task-context.py` drift exit changed from `sys.exit(2)` to `sys.exit(0)`; confirm no downstream script breaks
- [x] `CLAUDE.md` Agent Startup Protocol updated: explicit no-parallel-batch rule added
- [x] Proof: drifted-shell parallel batch (`make context` + `ToolSearch`) completes without cancellation
- [x] SHA validation already shipped: `InvalidCommitShaError` in `shared_write_context.py` — no new ticket needed

### Checklist for Slice 6: Task-Plan Audit

- [x] `scripts/task_plan_audit.py` written; parses git log; cross-references plan directories; exits 1 on gap
- [x] `make task-plan-audit` target added to Makefile
- [x] `make check-all` includes `make task-plan-audit`
- [x] `task-plan-audit` run against current `main` history; any newly-discovered legacy gaps backfilled or explicitly exempted before `check-all` integration
- [x] Proof: audit fails when a tagged task lacks a plan file and exits 0 with the current retroactive plan set committed

### Checklist for Slice 7: MCP Write Branch Enforcement (AHMCP-32)

- [x] AHMCP-32 task scoped and `set_handoff_state` registered
- [x] `BranchMismatchError` added to `shared_write_context.py` and exported from `__init__.py`
- [x] `_branch_enforcement_enabled()` reads `AGENT_HANDOFF_ENFORCE_BRANCH`; tests bypass via `AGENT_HANDOFF_SKIP_BRANCH_ENFORCEMENT=1`
- [x] AHMCP-32 merged: `test_write_blocked_on_branch_mismatch` and `test_write_warns_only_by_default` pass; existing test suite unaffected
- [x] E17-4 follow-up: `AGENT_HANDOFF_ENFORCE_BRANCH=1` documented in `CLAUDE.md`; dev shell configured
- [x] Proof: drifted write → `BranchMismatchError` response, nothing stored; correct-worktree write → succeeds

### Checklist for Slice 8: Portable Workflow Surface

- [x] `config/agent-workflows/portable_commands.json` created as the canonical workflow command manifest
- [x] `scripts/generate_agent_workflows.py` renders `.claude/commands/*.md` and `.github/prompts/*.prompt.md` from the manifest
- [x] `scripts/generate_agent_workflows.py` validates `portable_commands.json` structurally before rendering adapters
- [x] `docs/agentic/instructions.md` and `CLAUDE.md` route leading `/command_id` syntax for Codex using the same manifest-defined mapping
- [x] `Makefile` adds `generate-agent-workflows` and `check-agent-workflows`
- [x] `make check-agent-workflows` wired into repo validation so host adapters cannot drift silently
- [x] Proof: `/branch-review` and `/planning-review` resolve with uniform ids, argument names, and skill bindings across Claude, VS Code/Copilot, and Codex

## Review Readiness

- [x] Slice 1: `make worktree-audit` exits 0 on clean repo; CI does not break on `make check-all`
- [x] Slice 2: hook and context changes are non-breaking; no existing tests fail
- [x] Slice 3: `_task_finish_inline.py` change is backward-compatible when branch already deleted
- [x] AHMCP-31 has its own pre-merge gate; no E17-4 code depends on AHMCP-31 internals
- [x] Slice 5: `make context` exits 0 on drift; no existing caller that depended on exit 2 regresses silently
- [x] Slice 6: `task-plan-audit` passes on the current retroactive plan set and fails deterministically on a missing tagged-plan case
- [x] Slice 7: AHMCP-32 has its own pre-merge gate; no E17-4 code depends on AHMCP-32 internals
- [x] Slice 8: manifest validation and adapter generation are deterministic; `check-agent-workflows` catches drift without requiring manual adapter edits

## Stretch Goals

- [x] `make worktree-prune` interactive target: for each orphan branch, prompt before `git branch -d`
- [ ] `record_file_touch` backfill: parse existing slice decisions' `## Changes` sections and insert historical touch records

## Success Criteria

- [x] `make check-all` exits 0 on clean repo; exits 1 with orphan list when orphan branches exist
- [x] Any agent starting a session on dirty main sees the dirty-file list and maintenance-task hint without running `git diff`
- [x] `load_session` (post AHMCP-31) returns `touched_files` for the active task — no `git diff` needed at cold start
- [x] `development-workflow.md` and `CLAUDE.md` contain actionable, testable rules for the maintenance-task pattern and branch-delete invariant
- [x] `make context` + `ToolSearch` batched in one parallel message never cancels the ToolSearch, even on drift
- [x] `agent-handoff-mcp` rejects fabricated 40-char SHAs via `InvalidCommitShaError` in `shared_write_context.py` — already shipped
- [x] `make task-plan-audit` exits 0 on a repo where every tagged commit on `main` has a corresponding plan file; exits 1 and lists gaps otherwise
- [x] (post AHMCP-32) `record_event` / `review_findings` / `close_slice` from the wrong branch → `BranchMismatchError`; write not stored. Correct worktree → succeeds. Handoff audit trail contains no drifted branch attributions for new writes.
- [x] `/branch-review`, `/planning-review`, and other registered workflow commands resolve through one canonical manifest and uniform slash syntax across Claude, VS Code/Copilot, and Codex; generated host adapters stay in sync via `make check-agent-workflows`
