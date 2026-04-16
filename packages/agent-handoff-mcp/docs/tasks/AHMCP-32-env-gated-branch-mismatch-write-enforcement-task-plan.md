# AHMCP-32. Env-Gated Branch-Mismatch Write Enforcement

> **Metadata**
>
> - **Date**: 2026-04-14
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-32`
> - **Target Branch**: `feature/ahmcp-32-branch-enforcement`
> - **Review Coverage Target**: 2

---

## Objective

Add optional write-time branch enforcement to `agent-handoff-mcp` so mutation calls can fail fast when `actor.branch` does not match the active task's `target_branch`, while preserving the current warning-only behavior unless enforcement is explicitly enabled.

## Problem Statement

`agent-handoff-mcp` already knows the active task's `target_branch`, and write paths already compare that target against the resolved actor branch. But `collect_target_context_warnings()` in `shared_write_context.py` only appends a `context_drift` warning and lets the write proceed. In practice, that means decisions, test results, findings, or state updates can still be recorded against the wrong branch when an agent ignores the warning or never surfaces it to the operator. The audit trail then contains durable but incorrect provenance. Warning-only drift detection is useful for gentle guidance, but it is not sufficient when a task declares an explicit feature branch and the operator wants hard enforcement.

## Constraints

- Keep this task package-local; do not combine it with shell exports, repo hook changes, or broader rollout work.
- Preserve the existing default behavior when enforcement is off; current callers should continue to receive warning-only drift responses.
- Enforce only branch mismatch in this task; current cwd / worktree-path drift remains warning-only.
- Only gate writes when the active task has a meaningful non-main target branch; `main` and `master` should remain non-blocking.
- Existing test suites must remain stable and deterministic; any test-only bypass must be explicit.

## Current State Analysis

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` compares `ctx.branch` against the active task's `target_branch` and emits a `context_drift` warning when they differ, but the helper is intentionally non-fatal today.
- The same module also emits a warning when the current working directory differs from `target_worktree_path`; that broader worktree discipline is already valuable and should remain non-fatal in this task.
- `docs/agentic/contracts/agent-handoff-mcp.md` documents the current behavior as warning-only drift detection for `set_handoff_state` and decision writes.
- `packages/agent-handoff-mcp/tests/test_handoff_state.py` already contains `test_set_handoff_state_emits_context_drift_warning_on_branch_mismatch`, which proves the current warning path.
- `packages/agent-handoff-mcp/tests/conftest.py` already sets `AGENT_HANDOFF_SKIP_SHA_VALIDATION=1` to stabilize tests around synthetic SHAs; branch enforcement needs an equally explicit test-time story if it becomes env-gated.

## Target Outcome

When `AGENT_HANDOFF_ENFORCE_BRANCH=1` is set, write operations that would otherwise emit a branch `context_drift` warning fail before any DB mutation occurs, and the failure clearly identifies the expected branch and the actor branch. When the env var is unset, current warning-only behavior remains unchanged. This gives operators a package-level gate without forcing repo-wide rollout in the same task.

## Context Loading

- Rules: `docs/agentic/instructions.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Parent task dependency: `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md` Slice 7
- Scope intake: `docs/scopes/ahmcp-31-32-scope-note.md`
- Recorded intake decision: `1726` (`scope_intake_AHMCP-32_package_only_mvp`)

## Contract and Boundary Impact

| Boundary               | Owner        | Current Contract                                           | Expected Change                                                                                                                                           | Compatibility Needed?                 | Verification                |
| ---------------------- | ------------ | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | --------------------------- |
| Shared write context   | handoff core | Branch drift emits non-fatal warnings                      | Add env-gated `BranchMismatchError` before DB writes when enforcement is on                                                                               | Yes; default remains warning-only     | write-path regression tests |
| Python package surface | handoff core | No public branch-mismatch exception type                   | Export `BranchMismatchError` from package root                                                                                                            | Yes; additive                         | import smoke coverage       |
| Test harness           | handoff core | Only SHA-validation bypass exists                          | Add explicit branch-enforcement bypass for deterministic tests if needed                                                                                  | Yes; existing suites must stay stable | package suite               |
| MCP failure surface    | handoff core | Write-path validation failures return `ok=false` envelopes | `BranchMismatchError` caught and wrapped into `ok=false` envelope with `expected_branch`/`actual_branch` details, same pattern as `InvalidCommitShaError` | Yes; envelope schema unchanged        | write-path regression tests |
| Contract docs          | repo docs    | Drift documented as warning-only                           | Document warning-only default plus optional enforcement mode                                                                                              | Yes; default semantics unchanged      | contract doc review         |

## Proposed Solution

Add a narrow, env-gated enforcement layer at the shared write-context boundary.

1. Introduce a `BranchMismatchError` exception that carries the task ref, expected branch, and actor branch.
2. Add `_branch_enforcement_enabled()` and a test-time skip path mirroring the existing SHA-validation guard style.
3. Integrate the enforcement check into `collect_target_context_warnings()` so it raises `BranchMismatchError` when the env gate is on. Then wire that helper into every write surface that currently calls `_resolve_write_actor()` but skips context warnings. Today only `set_handoff_state` (`handoff_state.py:157`) and `record_decision` (`decisions.py:94`) invoke `collect_target_context_warnings()`; the remaining write surfaces — `update_next_actions`, `record_test_result`, `report_blocker` (all in `decisions.py`), `record_review_finding`, `batch_record_review_findings`, `record_review_run` (all in `review_findings.py`) — call `_resolve_write_actor()` but never check branch drift. Add the `collect_target_context_warnings()` call to each so all mutation paths share the same enforcement gate.
4. Surface `BranchMismatchError` to MCP callers as an `ok=false` envelope with `expected_branch` and `actual_branch` details in `data.error`, following the established `InvalidCommitShaError` catch-and-wrap pattern already used in `decisions.py` and `review_findings.py`. Python API callers receive the raw exception; MCP tool handlers adapt it into the envelope.
5. Leave cwd / worktree-path drift as warning-only, and leave the default env-off behavior unchanged.
6. Update tests and contract docs so both the blocking and warning-only paths are explicit and verified.

## Files and Surfaces to Change

| Surface                          | File                                                                       | Change                                                                                                                                                               |
| -------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shared write-context enforcement | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` | Add env-gated branch mismatch enforcement and `BranchMismatchError`                                                                                                  |
| Decision write surfaces          | `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py`            | Wire `collect_target_context_warnings()` into `update_next_actions`, `record_test_result`, `report_blocker`; add `BranchMismatchError` catch-and-wrap                |
| Review-finding write surfaces    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`      | Wire `collect_target_context_warnings()` into `record_review_finding`, `batch_record_review_findings`, `record_review_run`; add `BranchMismatchError` catch-and-wrap |
| Package exports                  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py`             | Export `BranchMismatchError`                                                                                                                                         |
| Package docs                     | `packages/agent-handoff-mcp/README.md`                                     | Document optional branch-enforcement behavior for Python/MCP callers                                                                                                 |
| Contract docs                    | `docs/agentic/contracts/agent-handoff-mcp.md`                              | Document warning-only default plus env-gated enforcement mode                                                                                                        |
| Test bootstrap                   | `packages/agent-handoff-mcp/tests/conftest.py`                             | Add explicit branch-enforcement test bypass if required                                                                                                              |
| Write-path regression tests      | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                   | Keep default warning coverage and add enforcement-on failure coverage                                                                                                |
| Decision/write regression tests  | `packages/agent-handoff-mcp/tests/test_review_findings.py`                 | Add at least one non-`set_handoff_state` write-path test proving enforcement blocks before mutation                                                                  |

## Related Files

| File                                                                | Note                                                                                                               |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Existing write path already feeds branch context into shared write-context resolution                              |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`          | Compound writes such as `close_slice` should inherit the shared enforcement path rather than adding bespoke checks |
| `docs/tasks/17.0/E17-4-workflow-integrity-task-plan.md`             | Parent task owns the later shell-export / rollout step after package support exists                                |

## Verification Strategy

- Primary package verification:
  - `cd packages/agent-handoff-mcp && make test-handoff`
- Deterministic assertions to add:
  - Default env-off behavior still succeeds and emits `context_drift` warnings on branch mismatch
  - `AGENT_HANDOFF_ENFORCE_BRANCH=1` blocks mismatched writes before any mutation is stored
  - Matching branch writes continue to succeed when enforcement is on
  - Cwd / worktree mismatch remains warning-only in this task
- Manual package-level sanity check:
  - Set `AGENT_HANDOFF_ENFORCE_BRANCH=1`, initialize a task with `target_branch="feature/foo"`, attempt a write from `actor.branch="main"`; the call should fail with `BranchMismatchError` details and leave no new row behind

## Slice Delivery

### Slice 1: Add the Branch Enforcement Primitive and Wire All Write Surfaces

**Goal**: The shared write-context layer can optionally reject branch-mismatched writes before any DB mutation occurs, and every write surface that calls `_resolve_write_actor()` inherits the enforcement.

Changes:

- Add `BranchMismatchError` to `shared_write_context.py` and export from `__init__.py`
- Add env-gated enforcement helpers and any explicit test bypass required
- Extend `collect_target_context_warnings()` to raise `BranchMismatchError` when enforcement is enabled and branch mismatches
- Wire `collect_target_context_warnings()` into the 6 write surfaces that currently skip it: `update_next_actions`, `record_test_result`, `report_blocker` (in `decisions.py`), `record_review_finding`, `batch_record_review_findings`, `record_review_run` (in `review_findings.py`)
- Add `BranchMismatchError` catch-and-wrap to return `ok=false` envelopes with `expected_branch`/`actual_branch` details, following the `InvalidCommitShaError` pattern
- Gate mismatched writes only when the target branch is meaningful and enforcement is enabled
- Keep cwd drift warning-only

Proof:

- `make test-handoff` passes with new enforcement coverage
- Matching-branch writes still succeed under enforcement
- At least one non-`set_handoff_state` write surface proves enforcement blocks before mutation

### Slice 2: Verify Multi-Surface Coverage and Regression Safety

**Goal**: Deterministic tests prove that enforcement blocks mutations across multiple write surfaces and that the warning-only default does not regress.

Changes:

- Preserve the existing warning-only regression for `set_handoff_state`
- Add enforcement-on tests for at least two distinct write-surface families (e.g., `record_test_result` in `decisions.py` and `record_review_finding` in `review_findings.py`) to prove the Slice 1 wiring is effective beyond just `set_handoff_state`
- Confirm compound writes (e.g., `close_slice`) inherit the same shared guard through the existing write-context path
- Ensure failed writes do not partially mutate the ledger

Proof:

- Enforcement-on mismatch tests fail before persistence on multiple write surfaces
- Default env-off coverage remains green

### Slice 3: Document the Opt-In Behavior Without Rolling It Out Repo-Wide

**Goal**: Package callers can discover the feature, but repo-level enablement remains a separate follow-up.

Changes:

- Update README and contract docs with the env-gated behavior
- Explicitly document that rollout via shell exports or repo instructions is out of scope here
- Keep the task package-only and avoid `.claude/settings.json`, `CLAUDE.md`, or root hook changes in this branch

Proof:

- Docs describe the default warning path and the opt-in enforcement path accurately
- No repo-level rollout/config files change in this task

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the relevant rules, contracts, and parent-task dependency before implementation starts.
- [x] Kept rollout work out of this package task.
- [x] Preserved current warning-only behavior when enforcement is disabled.

### Checklist: Slice 1

- [x] `BranchMismatchError` exists and is exported from the package root.
- [x] Shared write-context code can detect enforcement-on branch mismatch before mutation.
- [x] All write surfaces that call `_resolve_write_actor()` also invoke `collect_target_context_warnings()`.
- [x] `BranchMismatchError` is caught and wrapped into `ok=false` envelopes with `expected_branch`/`actual_branch` details at each write surface.
- [x] Enforcement ignores `main` / `master` targets and continues to allow env-off writes.
- [x] Any required test-only bypass is explicit and documented.

### Checklist: Slice 2

- [x] Existing branch-drift warning coverage still passes by default.
- [x] Enforcement-on mismatch coverage proves no write is stored.
- [x] At least one additional write surface beyond `set_handoff_state` is covered.
- [x] Cwd / worktree-path drift remains warning-only.

### Checklist: Slice 3

- [x] README documents opt-in branch enforcement.
- [x] Contract docs document default warning-only behavior plus the env-gated enforcement mode.
- [x] No shell exports, `.claude/settings.json`, or `.github/hooks/terminal-guard.json` changes land in this task.

## Review Readiness

- [x] Blocking behavior is covered by deterministic tests, not only manual reproduction.
- [x] Warning-only compatibility remains covered by regression tests.
- [x] Failure responses clearly surface expected vs actual branch context.
- [x] The handoff decision records the implementation scope and verification evidence.

## Success Criteria

- [x] `agent-handoff-mcp` can optionally reject writes whose `actor.branch` mismatches the active task's `target_branch`.
- [x] Default behavior remains warning-only when enforcement is not enabled.
- [x] The feature ships without repo-wide rollout work in the same branch.
- [x] `cd packages/agent-handoff-mcp && make test-handoff` passes on the task branch.
