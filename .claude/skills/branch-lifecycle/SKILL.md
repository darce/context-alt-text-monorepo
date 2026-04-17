---
name: branch-lifecycle
description: "Use when starting, advancing, reviewing, or finishing a task branch. Triggers on `make task-start`, `make review-ready`, `make handoff-close-check`, or `make task-finish`."
mode: execution
context_budget: 150
makefile_target: task-start
mcp_tools:
  - set_handoff_state
  - record_event
  - close_slice
  - handoff_close_check
  - update_task_status
  - render_handoff
  - manage_worktree_lane
  - switch_task
tdd_gate: true
disable-model-invocation: false
---

# Branch Lifecycle

## Overview

Use this skill for the branch-owned implementation loop from `make task-start` through `make task-finish`. It owns branch isolation, review-readiness, and the invariant close sequence that leaves the root worktree back on `main` with a clean archived task.

## Trigger

Use this skill when:

- starting implementation from an approved task plan
- preparing an active task branch for review
- checking merge readiness with `make review-ready` or `make handoff-close-check`
- finishing a task branch and tearing down its worktree

Do not use it for planning-only work on `main`, planning reviews, or within-slice RED -> GREEN loops.

## Goal

Move one task cleanly through branch start, slice execution, review, close check, merge, and teardown without leaving code on `main`, stale task state, or an unarchived worktree behind.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/rules/branch-review-guide.md](../../../docs/agentic/rules/branch-review-guide.md)

This skill owns the branch-scoped lifecycle. The `tdd` skill owns the failing-test gate inside a slice, and the review skills own review execution.

## Core Process

1. Start from a reviewed task plan on `main`. Create the branch/worktree with `make task-start TASK=<task-ref> OBJECTIVE="..."`, then run `make context` before editing.
2. Confirm the implementation shell is on the task's `target_branch` and `target_worktree_path`. If the task is wrong, use `switch_task` instead of carrying changes across tasks.
3. Run implementation through bounded TDD slices: `make slice-start` -> edit -> passing test evidence -> `make slice-commit`.
4. After each slice and before any lint or check pass, run `make format-all` (or the per-package variant in lane workers: `make format-handoff`, `make format-orchestrator`, `make format` from app dir). This auto-fixes the majority of lint violations. Do not manually fix lint errors without running the formatter first.
5. Before requesting review, run `make review-ready` and clear every NOT READY reason. Treat missing tests, open findings, and contract drift as blockers, not cleanup.
6. Run the appropriate review workflow and resolve findings. Do not move to close-check while findings remain open.
7. Run `make handoff-close-check` on the branch HEAD. The branch is not merge-ready until the enforced gate passes.
8. Merge the reviewed branch, return the root worktree to `main`, and delete the merged feature branch only after the branch work is actually landed.
9. Finish with the Worktree Status Integrity close sequence: `update_task_status(done)` -> `manage_worktree_lane(close)` when lanes exist -> archive the task state -> keep `DASHBOARD.txt` current, using `render_handoff(kind='current_task')` only if an explicit task-scoped snapshot is needed.
10. Run `make task-finish TASK=<task-ref>` so teardown, archive, and dashboard regeneration happen in the repo's canonical order.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "I'll just patch this on `main` and branch later." | Code on `main` breaks branch isolation and makes review provenance ambiguous. The hooks block it because the workflow is not trustworthy afterward. | Start or switch to the task branch before any code edit. |
| "The worktree is already merged, so close order doesn't matter." | A merged branch can still leave stale lane rows, unarchived task state, or a dashboard that says the task is still active. Close order is what keeps operator state honest. | Run the documented close sequence in order, even after the merge succeeds. |
| "I'll skip `handoff-close-check` this once because review already looked good." | Human review and gate evidence are different things. Missing close-check proof means stale tests, open findings, or missing slice decisions can still slip through. | Run the enforced gate on the final HEAD every time. |
| "I'll just fix these lint errors manually, it's only a few." | `make format-all` auto-fixes the majority of lint violations. Manual fixes waste time and risk introducing inconsistent style. | Run `make format-all` first. Only manually fix what the formatter cannot. |

## Red Flags

Each flag is a re-entry trigger. Stop and re-enter at the step shown.

| Flag | Re-entry point |
|---|---|
| Code edits appear on `main` | Step 1: stop, isolate the work onto the feature branch, then continue there. |
| `make context` reports branch or worktree drift | Step 2: fix the shell context before recording any more MCP state. |
| Lint errors encountered without running `make format-all` first | Step 4: run the formatter before any manual lint fixes. |
| Review-ready reports missing tests, open findings, or contract drift | Step 5: clear the blocking condition before asking for review. |
| `handoff-close-check` fails | Step 7: resolve the underlying missing evidence or open findings, then rerun the gate. |
| Worktree teardown attempted before task status is `done` | Step 9: restore the close sequence and archive only after the task is explicitly done. |

## Recovery

- If dirty code is inherited on `main`, stop and move it to the owning feature branch before starting new implementation.
- If the wrong task is active, switch task state first and rerun `make context`.
- If merge lands but archive/teardown does not, rerun the invariant close sequence instead of hand-editing `CURRENT_TASK.json` or `DASHBOARD.txt`.
- If lanes were opened, close them before archiving so the dashboard does not report ghost worker state.

## Convergence Criteria

- The task branch was created from an approved plan and stayed isolated from `main`.
- Slice work closed through recorded `close_slice` decisions.
- Review completed with zero open findings.
- `handoff_close_check(enforce=True)` passed on the final branch HEAD.
- The task ended with the invariant close sequence: `update_task_status(done)` -> lane close when needed -> archive -> `render_handoff(kind='dashboard')` when a non-atomic write path requires it.
- Root worktree is back on `main`, the feature branch is no longer active, and `DASHBOARD.txt` reflects the closed task with `CURRENT_TASK.json` available on demand.

## See Also

- [../tdd/SKILL.md](../tdd/SKILL.md)
- [../incremental-implementation/SKILL.md](../incremental-implementation/SKILL.md)
- [../../../docs/agentic/lifecycle-map.md](../../../docs/agentic/lifecycle-map.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
