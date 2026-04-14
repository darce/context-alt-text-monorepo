---
name: planning-review
description: "Use when reviewing task plans, epics, ADRs, or other planning documents. Triggers on `make plan-review` and planning review requests."
mode: execution
context_budget: 120
makefile_target: plan-review
mcp_tools:
  - get_latest_slice_review_packet
  - review_findings
  - review_runs
  - record_event
  - search_handoff
tdd_gate: false
disable-model-invocation: false
---

# Planning Review

## Overview

Use this skill for durable review of planning artifacts. It applies the planning-review checklist, records findings in MCP, and closes with a planning-mode review run plus verdict decision.

## Trigger

Use this skill when:

- reviewing a task plan, epic, ADR, roadmap, or assessment
- running `make plan-review DOC=<path>`
- validating that a planning artifact is ready for implementation

Do not use it for implementation diffs or pre-review triage of plan quality.

## Goal

Produce a planning-review verdict backed by recorded findings and a planning-mode review run, with the artifact either cleared for the next stage or blocked on concrete gaps.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)

This skill owns planning-review execution order. The guide owns the detailed checklist and severity model.

## Core Process

1. Load the planning artifact, the minimum prerequisite packet, and the relevant code or contract anchors.
2. Check prior planning review history with `review_runs(operation="list", review_mode="planning", ...)`.
3. Execute the planning-review checklist: current-state accuracy, internal consistency, architecture ownership, contract realism, naming compliance, pipeline readiness, and testability.
4. Record every finding in MCP with `review_findings`.
5. Decide the planning verdict.
6. Record the verdict decision with `record_event(event_kind="decision", ...)`.
7. Record the planning review run with `review_runs(operation="record", review_mode="planning", ...)`.
8. Confirm whether open findings remain before declaring the artifact ready.

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
- A planning-mode review run exists for the pass.
- A verdict decision exists for the artifact.
- The artifact is either cleared with zero open findings or blocked on explicit unresolved gaps.

## See Also

- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
- [../plan-analyze/SKILL.md](../plan-analyze/SKILL.md)
