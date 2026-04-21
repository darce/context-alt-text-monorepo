---
name: planning-review
description: "Use when reviewing task plans, epics, ADRs, or other planning documents. Triggers on `make plan-review` and planning review requests."
mode: execution
context_budget: 120
makefile_target: plan-review
mcp_tools:
  - review_findings
  - review_runs
  - record_event
  - search_handoff
tdd_gate: false
disable-model-invocation: false
---

# Planning Review

## Overview

Use this skill for durable review of planning artifacts. It applies the planning-review checklist, records findings in MCP, refreshes `DASHBOARD.txt`, and closes with a planning-mode review run plus verdict decision.

## Trigger

Use this skill when:

- reviewing a task plan, epic, ADR, roadmap, or assessment
- running `make plan-review DOC=<path>`
- validating that a planning artifact is ready for implementation

Do not use it for implementation diffs or pre-review triage of plan quality.

## Goal

Produce a planning-review verdict backed by recorded findings, printed handoff gap ids (`finding_id`), a refreshed `DASHBOARD.txt`, and a planning-mode review run, with the artifact either cleared for the next stage or blocked on concrete gaps.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
- [../../../docs/agentic/templates/TASK_PLAN.template.md](../../../docs/agentic/templates/TASK_PLAN.template.md) for task plans under `docs/tasks/`

This skill owns planning-review execution order. The guide owns the detailed checklist and severity model.

## Core Process

0. **Ensure task scope before any cwd-resolving MCP read.** `search_handoff`, `review_runs`, `review_findings` without `task_ref` all resolve from cwd. On cold start:
   - **Resumption:** work from the existing task's `target_worktree_path`; pass `task_ref` explicitly.
   - **Ad-hoc planning review on main:** register a maintenance task first — `set_handoff_state(task_ref="MAINT-<slug>-<YYYYMMDD>", objective="...", status="in_progress", target_branch="main")`.
   - **`Ambiguous active task` error:** run `make maint-archive-stale` (or `MAINT_ARCHIVE_ARGS="--yes"`), then re-run `make context`. `make context` exits `2` on this ambiguity.

1. Load the planning artifact, the minimum prerequisite packet, and the relevant code or contract anchors.
2. Check prior planning review history with `review_runs(operation="list", review_mode="planning", ...)`.
3. Execute the planning-review checklist: current-state accuracy, internal consistency, architecture ownership, contract realism, naming compliance, pipeline readiness, and testability.
4. If the artifact is a task plan under `docs/tasks/`, verify it still conforms to `docs/agentic/templates/TASK_PLAN.template.md`, including the `## Consolidated Checklist` structure and the required supporting sections.
5. Record every finding in MCP with `review_findings`.
6. Decide the planning verdict.
7. Record the verdict decision with `record_event(event_kind="decision", ...)`.
8. Record the planning review run with `review_runs(operation="record", review_mode="planning", ...)`.
9. Refresh `DASHBOARD.txt` with `render_handoff(kind='dashboard')` after the state-changing writes land.
10. Confirm whether open findings remain before declaring the artifact ready, and cite the stable handoff gap ids (`finding_id`) when reporting them.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "It's only a plan, so small inconsistencies can wait for implementation." | Planning drift becomes implementation churn. The cheapest fix is before code starts. | Record and resolve the inconsistency now. |
| "The artifact mostly looks right, so I don't need code anchors." | Plans fail on stale assumptions about the current repo state. | Check the actual code or contract surface. |
| "The analysis pass already looked at this." | `plan-analyze` is triage, not the required planning review gate. | Run the full planning review anyway. |

## Red Flags

| Flag | Re-entry point |
|---|---|
| Planning review starts without current code anchors | Step 1: load the missing anchor. |
| Findings are about to be reported without MCP ids | Step 4: record them first. |
| Artifact is being approved while open findings still exist | Step 8: block approval until statuses are resolved. |

## Recovery

- If the planning packet is incomplete, record the missing dependency as a finding instead of guessing.
- If no valid slice packet exists, state that the review is using fallback scope.
- If MCP is unavailable, stop and record a blocker when access returns.

## Convergence Criteria

- Planning findings are recorded in MCP before they are reported.
- Reported findings cite their stable handoff gap ids (`finding_id`).
- A planning-mode review run exists for the pass.
- A verdict decision exists for the artifact.
- `DASHBOARD.txt` is refreshed after the planning-review writes.
- The artifact is either cleared with zero open findings or blocked on explicit unresolved gaps.

## See Also

- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
- [../plan-analyze/SKILL.md](../plan-analyze/SKILL.md)
