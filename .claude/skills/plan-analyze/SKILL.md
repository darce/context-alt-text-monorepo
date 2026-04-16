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

Use this skill as a pre-review planning triage step. It runs a focused analysis pass on one planning artifact, records planning-mode findings in MCP, and produces the session marker that `make plan-review` uses for its precheck.

## Trigger

Use this skill when:

- running `make plan-analyze DOC=<path>`
- triaging a task plan or epic before formal planning review
- checking a planning artifact for ambiguity, duplication, coverage gaps, or terminology drift

Do not use it as a substitute for `planning-review`, and do not use it for branch diffs.

## Goal

Surface likely planning problems early, record them as planning findings under a `plan-analyze-*` session, and hand the artifact off to `planning-review` only after the cheap gaps are understood.

## Canonical Policy

- [../../../docs/agentic/instructions.md](../../../docs/agentic/instructions.md)
- [../../../docs/agentic/constitution.md](../../../docs/agentic/constitution.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)

This skill owns triage only. It records planning-mode findings and a `review_runs(operation="record", review_mode="planning", ...)` entry with a `plan-analyze-*` session prefix so `make plan-review` can confirm the pre-review pass happened. It does not replace the formal planning-review run.

## Core Process

1. Load the planning artifact, the constitution, and only the minimum adjacent code or contract anchors needed to test the artifact's claims.
2. Run six analysis passes: duplication, ambiguity, underspecification, constitution alignment, coverage gaps, and terminology drift.
3. Turn concrete problems into MCP findings with `review_findings(..., review_mode="planning")`.
4. Record a planning-mode review run whose `session` starts with `plan-analyze-` so the downstream gate can distinguish triage from the formal review pass.
5. Summarize whether the artifact should proceed directly to `planning-review` or be revised first.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "Analysis already found issues, so the formal review can be skipped." | Analysis is triage, not the planning gate. It does not produce the required review-run record. | Still run `planning-review`. |
| "I can just leave the issues in chat because this is only advisory." | Advisory findings still need durable ids so planners can fix or defer them. | Record them in MCP with `review_mode=\"planning\"` under a `plan-analyze-*` session. |
| "The document is short, so detailed passes are unnecessary." | Short plans can still hide stale assumptions or missing rollout details. | Run every analysis pass anyway. |

## Red Flags

| Flag | Re-entry point |
|---|---|
| Analysis is about to approve a document without touching the constitution or code anchors | Step 1: load the missing anchor. |
| Findings are being recorded without `review_mode="planning"` | Step 3: correct the write mode before continuing. |
| The review run session does not start with `plan-analyze-` | Step 4: fix the session marker so the planning gate can detect the triage pass. |

## Recovery

- If the artifact is too broad, narrow the pass to the next planning slice instead of loading half the repo.
- If adjacent contracts are missing, record that gap as a finding.
- If MCP is unavailable, stop and treat durable finding recording as a blocker before recommending implementation.

## Convergence Criteria

- Analysis findings are recorded in MCP with `review_mode="planning"` under a `plan-analyze-*` session.
- A planning-mode review run exists for the triage pass and is distinguishable from the formal planning-review run by its `session` prefix.
- The recommendation clearly says either "revise first" or "proceed to planning-review."

## See Also

- [../planning-review/SKILL.md](../planning-review/SKILL.md)
- [../../../docs/agentic/rules/planning-review-guide.md](../../../docs/agentic/rules/planning-review-guide.md)
