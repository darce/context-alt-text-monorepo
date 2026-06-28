---
name: branch-review
scope: harness
description: Use when reviewing implementation changes on a feature branch. Triggers
  on `make review-run` for lane/local working-tree review, branch diff review requests,
  or pre-merge audit passes.
mode: execution
context_budget: 150
makefile_target: review-run
mcp_tools:
- get_latest_slice_review_packet
- get_review_findings_summary
- reconcile_review_findings
- review_findings
- review_runs
- record_event
- integrity_check
tdd_gate: false
---

# Branch Review

## Overview

<!-- context-alt-text customization: always check alt-text fixtures under tests/fixtures/alt_text/ when reviewing generator changes. -->

Use this skill for code and workflow diffs on feature branches. It runs the branch-review checklist, records findings before chat output, and closes with a durable review verdict.

## Trigger

Use this skill when:

- reviewing a feature branch diff before merge
- running `make review-run` for lane/local working-tree review
- auditing implementation changes under `apps/`, `packages/`, `scripts/`, or `mk/`

Do not use it for task plans, epics, ADRs, or other planning artifacts.

## Goal

Produce a branch-review verdict with MCP-recorded findings, a recorded review run, and clear evidence about whether the branch is genuinely merge-ready.

## Canonical Policy

- [../../../docs/workbay/instructions.md](../../../docs/workbay/instructions.md)
- [../../../docs/workbay/rules/development-workflow.md](../../../docs/workbay/rules/development-workflow.md)
- [../../../docs/workbay/rules/branch-review-guide.md](../../../docs/workbay/rules/branch-review-guide.md)

This skill owns branch-review execution order. The guide owns the detailed checklist.

## Core Process

0. **Ensure task scope before any cwd-resolving MCP read.** Every other step calls `load_session`, `search_handoff`, `review_findings`, etc. — these resolve the active task from cwd unless `task_ref` is passed explicitly. On cold start:
   - Run `make status LIFECYCLE_ARGS=--json` from the target worktree first so branch/worktree alignment and the active task surface are confirmed through the public facade.
   - If more than one task may be active, run `make tasks LIFECYCLE_ARGS=--json` before any MCP read so you can pick the correct `task_ref` without spelunking handoff state directly.
   - **Resumption:** work from the existing task's `target_worktree_path`; pass `task_ref` explicitly to all subsequent MCP calls.
   - **Ad-hoc on main (e.g. reviewing a merged commit):** register a maintenance task first — `set_handoff_state(task_ref="MAINT-<slug>-<YYYYMMDD>", objective="...", status="in_progress", target_branch="main")` — and pass that `task_ref` forward.
   - **`Ambiguous active task` error:** archive stale MAINT-* rows in one shot with `make maint-archive-stale` (or `MAINT_ARCHIVE_ARGS="--yes"` non-interactively), then re-run `make context`. `make context` exits `2` (not `1`) specifically on this ambiguity.

1. Start with a real review scope. `make review-run` is for lane/local working-tree review because `review_runner.py` only inspects local changed files. For committed feature-branch diff review, load the latest slice review packet when available or review `git diff main...HEAD` scope directly. If `workbay-orchestrator-mcp` is unavailable, use the handoff-only fallback from `branch-review-guide.md`: `load_session` -> `search_handoff(queries=["slice_complete"], record_types=["decision"], limit=1)` -> `get_verified_tests` -> `review_findings(list)` and review against branch-diff scope.
2. Pre-triage with `get_review_findings_summary` and `reconcile_review_findings` so old open findings are understood before new detection passes begin. When orchestrator is unavailable, state that the pass is using `branch_diff` fallback scope instead of `slice_packet`.
3. Check prior review history with `review_runs(operation="list", review_mode="branch", ...)`.
4. Run the branch-review checklist against the actual diff, touched contracts, and fresh verification evidence.
5. Record every finding with `review_findings`. Use `batch_record` for multi-finding passes.
6. Decide the verdict: `pass`, `pass_with_findings`, `conditional_pass`, or `fail`.
7. Record the verdict decision with `record_event(event_kind="decision", ...)`.
8. Record the review run with `review_runs(operation="record", review_mode="branch", subject_kind="branch", subject_path="<base>...<head>", ...)`. `branch_diff` is only the honest review-scope label; it is not a valid persisted `subject_kind`.
9. Re-check whether open findings remain. If none remain and the branch claims readiness, `integrity_check(payload={"kind":"close","enforce":true})` should be able to pass.

When MCP tools are unavailable but the CLI wrapper is available, use the CLI wrapper as the fallback MCP surface (`mcp-workbay-handoff --workspace-root <repo> review-findings ...`, `review-runs ...`, `event ...`). Do not write directly to `.task-state/handoff.db`; raw SQL bypasses validation, dashboard/event hooks, and future server-owned side effects. If neither MCP tools nor the CLI wrapper are available, stop and report the blocker instead of emitting untracked findings.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "The diff is small, so a quick skim is enough." | Small diffs still break contracts, test freshness, and branch isolation. | Run the full checklist. |
| "I'll mention the issue first and record it later." | Unrecorded findings do not exist to the gate or the next reviewer. | Record findings before reporting them. |
| "Prior open findings are probably stale anyway." | Re-reviewing without reconciliation creates duplicates or misses still-open regressions. | Pre-triage existing findings first. |

## Red Flags

| Flag | Re-entry point |
|---|---|
| Review starts without a clear diff or slice packet | Step 1: fix scope before continuing. |
| Existing open findings were ignored | Step 2: reconcile before new detection passes. |
| Verdict is about to be reported without a review run | Step 8: record the run first. |

## Recovery

- If the slice packet is missing, state that the review is branch-diff fallback scope.
- If `workbay-orchestrator-mcp` is not loaded, switch to the documented handoff-only fallback path instead of stopping at the missing slice-packet call.
- If MCP is unavailable, stop and record a blocker instead of reporting untracked findings.
- If findings recur from a prior pass, update or reopen them rather than creating duplicates.

## Convergence Criteria

- Findings mentioned to the user are already recorded in MCP.
- A branch-mode review run exists for the pass.
- A verdict decision exists for the review.
- The final response prints the MCP write receipt with row ids, e.g. `MCP writes: 4 findings batch-recorded; verdict decision id 2538 (branch_review_...); review_run id 414. DASHBOARD.txt refreshed. Handoff updated: decision branch_review_... recorded.`
- The review scope is identified honestly as `slice_packet` when packet-backed or `branch_diff` when running fallback scope.
- Merge-readiness claims are backed by fresh evidence, not assumption.

## See Also

- [../../../docs/workbay/rules/branch-review-guide.md](../../../docs/workbay/rules/branch-review-guide.md)
- [../planning-review/SKILL.md](../planning-review/SKILL.md)
