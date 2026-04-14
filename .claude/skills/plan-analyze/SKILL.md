---
name: plan-analyze
description: "Use for pre-review triage of planning documents. Triggers on `make plan-analyze` and requests to scan a plan for ambiguity, duplication, or missing coverage before formal planning review."
mode: advisory
context_budget: 200
makefile_target: plan-analyze
mcp_tools:
  - review_findings
  - search_handoff
tdd_gate: false
disable-model-invocation: false
---

# Plan Analyze

## Overview

Use this skill as a pre-review planning triage step. It runs a focused analysis pass on one planning artifact, records analysis findings in MCP, and recommends whether the document is ready for formal `planning-review`.

## Trigger

Use this skill when:

- running `make plan-analyze DOC=<path>`
- triaging a task plan or epic before formal planning review
- checking a planning artifact for ambiguity, duplication, coverage gaps, or terminology drift

Do not use it as a substitute for `planning-review`, and do not use it for branch diffs.

## Goal

Surface likely planning problems early, record them as `review_mode="analysis"` findings, and hand the artifact off to `planning-review` only after the cheap gaps are understood.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/constitution.md](../../../docs/agentic/constitution.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)

This skill owns analysis-mode triage only. It does not record a review run and does not satisfy the formal planning review gate.

## Core Process

1. Load the planning artifact, the constitution, and only the minimum adjacent code or contract anchors needed to test the artifact's claims.
2. Run six analysis passes: duplication, ambiguity, underspecification, constitution alignment, coverage gaps, and terminology drift.
3. Turn concrete problems into MCP findings with `review_findings(..., review_mode="analysis")`.
4. Summarize whether the artifact should proceed directly to `planning-review` or be revised first.
5. Stop after recording findings and recommendation. Do not record a review-run entry from this skill.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "Analysis already found issues, so the formal review can be skipped." | Analysis is triage, not the planning gate. It does not produce the required review-run record. | Still run `planning-review`. |
| "I can just leave the issues in chat because this is only advisory." | Advisory findings still need durable ids so planners can fix or defer them. | Record them in MCP with `review_mode=\"analysis\"`. |
| "The document is short, so detailed passes are unnecessary." | Short plans can still hide stale assumptions or missing rollout details. | Run every analysis pass anyway. |

## Red Flags

| Flag | Re-entry point |
|---|---|
| Analysis is about to approve a document without touching the constitution or code anchors | Step 1: load the missing anchor. |
| Findings are being recorded without `review_mode="analysis"` | Step 3: correct the write mode before continuing. |
| A review run is about to be recorded from this skill | Stop at Step 5: `plan-analyze` does not own review-run writes. |

## Recovery

- If the artifact is too broad, narrow the pass to the next planning slice instead of loading half the repo.
- If adjacent contracts are missing, record that gap as a finding.
- If MCP is unavailable, stop and treat durable finding recording as a blocker before recommending implementation.

## Convergence Criteria

- Analysis findings are recorded in MCP with `review_mode="analysis"`.
- The recommendation clearly says either "revise first" or "proceed to planning-review."
- No review-run entry was recorded from this skill.

## See Also

- [../planning-review/SKILL.md](../planning-review/SKILL.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
