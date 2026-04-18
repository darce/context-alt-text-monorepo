---
name: review-parallel
description: "Use when a branch review benefits from N independent parallel reviewers. Triggers on `/review-parallel`, explicit `reviewers_count>=2` requests, or review-coverage targets that require more than one pass over the same diff."
mode: execution
context_budget: 150
makefile_target: null
mcp_tools:
  - review_findings
  - review_runs
  - record_event
  - get_handoff_state
  - handoff_close_check
tdd_gate: false
disable-model-invocation: false
---

# Review Parallel

## Overview

Use this skill when one pass of `branch-review` is not enough. The coordinator stays in-process, fans out N ephemeral reviewers via the cheapest subagent primitive its harness exposes, scopes each reviewer to its own `task_ref`, then merges every reviewer's findings under the coordinator's `task_ref` via `review_findings(operation="merge")`. All three supported harnesses (Claude Code, Codex, Copilot) produce the same MCP state — only the fan-out primitive differs.

## Trigger

Use this skill when:

- a branch review's coverage target is 2 or more reviewers
- a diff is large or cross-cutting enough that independent passes de-risk bias
- the user explicitly invokes `/review-parallel`

Do not use it for single-reviewer passes (stay with `branch-review`), for planning artifacts (use `planning-review`), or for worker-daemon-backed continuous-polling orchestration (`dispatch_lane_work(start_worker=True)` is the right tool for multi-hour operator pipelines, not bounded reviews).

## Goal

Produce one merged finding set under the coordinator `task_ref` whose `merged_from` provenance names every source reviewer, with reviewer source rows preserved as an audit trail and a single branch-mode review run recorded for the combined pass.

## Canonical Policy

- [../../../docs/agentic/rules/branch-review-guide.md](../../../docs/agentic/rules/branch-review-guide.md)
- [../../../docs/agentic/rules/development-workflow.md](../../../docs/agentic/rules/development-workflow.md)
- [../../../docs/tasks/17.0/E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md](../../../docs/tasks/17.0/E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md)

This skill owns the coordinator protocol and the per-harness routing decision. The `branch-review` skill owns the checklist each reviewer runs.

## Harness Routing

The coordinator must call the **in-process** subagent primitive the current harness exposes. Shelling out to an external CLI from inside an active interactive session inverts the cost premise this skill is built on (the motivating assessment showed 1–2 orders of magnitude savings vs worker-daemon orchestration for bounded reviews).

| Harness detected | Primitive the coordinator uses | Notes |
| --- | --- | --- |
| Claude Code (coordinator is an in-process Claude agent) | `Agent` tool with `subagent_type` + scoped `task_ref` inside the prompt | In-process. **Must not** invoke the `ClaudeCodeAdapter` (CLI subprocess) from inside an active Claude Code session — that adapter is reserved for external orchestration and inverts the cost premise when used mid-session. |
| Codex (coordinator is a Codex agent) | `run_structured_turn` on `agent-orchestrator-mcp` | In-repo MCP tool. Each call is a bounded ephemeral turn with the reviewer prompt + scoped `task_ref`. |
| Copilot / VS Code | `run_structured_turn` on `agent-orchestrator-mcp` | Same MCP tool, reachable over MCP from the Copilot host. |
| External orchestrator (no interactive harness) | `backend_registry.get_adapter(<kind>)` + `BackendAdapter.execute(...)` | CLI/bridge path. Correct cost profile only when no interactive session exists. See [backend_adapter.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_adapter.py) and [backend_registry.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_registry.py) — exercised by the Slice 3 cross-vendor equivalence matrix. |

## Core Process

1. Confirm the coordinator has an active `task_ref`. `get_handoff_state(sections="identity")` is the bounded read. If there is no active task, abort with a clear precondition error; do not write anything.
2. Pick `N = reviewers_count` (default 2) and assign each reviewer a scoped `task_ref` following the convention `<coordinator-task-ref>-REV-<letter>`, using letters A, B, C, … in order. Record the coordinator/reviewer mapping as a decision: `record_event(event={"event_kind":"decision","decision":"<tag>_review_parallel_open_<coordinator>","rationale":"<mapping>"})`.
3. For each reviewer index, invoke the subagent primitive from the routing table above. The reviewer receives:
   - the reviewer prompt (default or the value of `reviewer_prompt_template` resolved under `config/agent-workflows/prompts/review-parallel/`),
   - the scoped `task_ref` it must write under,
   - the diff or slice packet under review.
4. Each reviewer records its findings via `review_findings(review={"operation":"batch_record", "task_ref":"<REV-X>", ...})` and returns a short summary to the coordinator. A reviewer must never write directly under the coordinator `task_ref` while another reviewer is still running.
5. After every reviewer returns, the coordinator merges: `review_findings(review={"operation":"merge","source_task_refs":[<REV-A>, <REV-B>, …],"target_task_ref":"<coordinator>"})`. This re-records each reviewer's findings under the coordinator `task_ref` with `merged_from` provenance pointing back at the source. Reviewer source rows remain intact — the merge is additive, not destructive.
6. Record the combined review run: `review_runs(operation="record", review_mode="branch", ...)` with `subject_path` pointing at the branch or slice artifact reviewed. Reviewer sub-runs remain under their own `task_ref`s as the audit trail.
7. Decide the combined verdict (`pass`, `pass_with_findings`, `conditional_pass`, `fail`) and record it as a decision tied to the coordinator `task_ref`.

## Common Rationalizations

| Rationalization | Why it fails | Required action |
|---|---|---|
| "I'll just have each reviewer write directly under the coordinator task_ref; simpler than merging." | Two reviewers racing on the same `task_ref` produces interleaved rows with no provenance; downstream reviewers cannot tell which finding came from which pass, and deduplication becomes guesswork. | Keep each reviewer's writes scoped to its own `task_ref`; merge at the end. |
| "The coordinator is already a Claude Code session, so I'll call the Claude CLI adapter for the reviewers." | Shelling out to `claude` from inside a running Claude Code session spins a full new harness per reviewer. That erases the in-process savings this skill is built on. | Use the in-process `Agent` tool from Claude Code. Reserve `ClaudeCodeAdapter` for external orchestration. |
| "We only need one reviewer this time; I'll still run `/review-parallel` with N=1." | A single reviewer does not benefit from the merge step and the extra coordinator overhead is pure waste. | Use `branch-review` directly when `reviewers_count <= 1`. |

## Red Flags

| Flag | Re-entry point |
|---|---|
| Two reviewers writing under the same `task_ref` | Step 2: assign scoped `<task>-REV-<letter>` task_refs before fan-out. |
| Coordinator shelling out to a CLI inside an interactive harness | Step 3: use the in-process primitive from the routing table. |
| Coordinator records findings before merge completes | Step 5: merge first, then record verdict/decision under the coordinator `task_ref`. |
| No combined `review_runs` row after fan-out | Step 6: record the branch-mode review run for the combined pass. |

## Recovery

- If a reviewer crashes mid-run, record a blocker under its scoped `task_ref` and exclude that reviewer from the merge. The merge step is additive; the remaining reviewers still produce a valid combined pass.
- If merge fails on an empty source list (validated error), at least one reviewer produced zero findings. Decide whether to retry that reviewer or proceed with the remaining source task_refs.
- If the coordinator cannot route the fan-out (harness primitive missing), fall back to sequential `branch-review` and record the degradation as a decision.

## Convergence Criteria

- Every reviewer finding is recorded under its scoped `task_ref` before merge.
- `review_findings(operation="merge")` has produced N × K rows under the coordinator `task_ref` with `merged_from` provenance on every row (N = reviewer count, K = per-reviewer finding count).
- Reviewer source rows remain intact (audit trail preserved).
- One branch-mode `review_runs` row records the combined pass under the coordinator `task_ref`.
- A verdict decision on the coordinator `task_ref` ties the review to its commit SHA.

## See Also

- [../branch-review/SKILL.md](../branch-review/SKILL.md)
- [../../../docs/agentic/rules/branch-review-guide.md](../../../docs/agentic/rules/branch-review-guide.md)
- [../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_adapter.py](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/backend_adapter.py)
