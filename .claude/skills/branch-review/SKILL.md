---
name: branch-review
description: "Use when reviewing implementation changes on a feature branch. Triggers on `make review-run`, branch diff review requests, or pre-merge audit passes."
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
  - handoff_close_check
tdd_gate: false
disable-model-invocation: false
---

# Branch Review

## Overview

Use this skill for code and workflow diffs on feature branches. It runs the branch-review checklist, records findings before chat output, and closes with a durable review verdict.

## Trigger

Use this skill when:

- reviewing a feature branch diff before merge
- running `make review-run`
- auditing implementation changes under `apps/`, `packages/`, `scripts/`, or `mk/`

Do not use it for task plans, epics, ADRs, or other planning artifacts.

## Goal

Produce a branch-review verdict with MCP-recorded findings, a recorded review run, and clear evidence about whether the branch is genuinely merge-ready.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/rules/branch-review-guide.md](../../../docs/agentic/rules/branch-review-guide.md)

This skill owns branch-review execution order. The guide owns the detailed checklist.

## Core Process

1. Load the latest slice review packet when available. Fall back to branch diff only when no valid packet exists.
2. Pre-triage with `get_review_findings_summary` and `reconcile_review_findings` so old open findings are understood before new detection passes begin.
3. Check prior review history with `review_runs(operation="list", review_mode="branch", ...)`.
4. Run the branch-review checklist against the actual diff, touched contracts, and fresh verification evidence.
5. Record every finding with `review_findings`. Use `batch_record` for multi-finding passes.
6. Decide the verdict: `pass`, `pass_with_findings`, `conditional_pass`, or `fail`.
7. Record the verdict decision with `record_event(event_kind="decision", ...)`.
8. Record the review run with `review_runs(operation="record", review_mode="branch", ...)`.
9. Re-check whether open findings remain. If none remain and the branch claims readiness, `handoff_close_check` should be able to pass.

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
- If MCP is unavailable, stop and record a blocker instead of reporting untracked findings.
- If findings recur from a prior pass, update or reopen them rather than creating duplicates.

## Convergence Criteria

- Findings mentioned to the user are already recorded in MCP.
- A branch-mode review run exists for the pass.
- A verdict decision exists for the review.
- Merge-readiness claims are backed by fresh evidence, not assumption.

## See Also

- [../../../docs/agentic/rules/branch-review-guide.md](../../../docs/agentic/rules/branch-review-guide.md)
- [../planning-review/SKILL.md](../planning-review/SKILL.md)
