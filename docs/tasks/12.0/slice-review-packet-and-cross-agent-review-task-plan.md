# Slice Review Packet and Cross-Agent Review Automation

## Objective

Make "review the last implementation slice" a reliable, MCP-backed workflow instead of a git-diff heuristic. When this task is complete, agents should be able to ask for the latest completed slice review packet and route that packet through the correct review guide without manual cherry-picking or file guessing.

## Problem Statement

The repo already has durable slice-completion decisions and worker reports, but review still depends on branch-diff discovery at execution time. That works for "review this branch" but not for "review the last completed slice" once more work has landed, the tree is dirty, or multiple slices share a branch. The result is repeated manual cherry-picking of recent decisions, file lists reconstructed from memory, and review prompts that may not match the slice boundary actually handed off.

What is missing is one authoritative review packet for each completed slice: a stable MCP record that binds the slice label, changed files, verification evidence, contract touches, and intended review mode together. Without that packet, cross-agent review remains best-effort rather than deterministic.

## Constraints

- Additive changes only; existing branch-level review flows and `review_ready.py` must keep working.
- The review packet must be sourced from MCP/handoff state, not from ad hoc branch archaeology after the fact.
- Planning review and branch review stay separate workflows; the packet should route to the correct guide instead of collapsing them into one generic review prompt.
- Review findings remain the canonical MCP output; this task improves review intake and scoping, not the downstream finding lifecycle.

## Workflow Principles

- Slice boundaries must be recorded at slice completion, not inferred later from current git state.
- Review input should prefer structured MCP provenance over heuristics.
- The same slice should carry behavior, proof, and review scope in one durable handoff unit.
- Fallback branch-diff discovery may remain for legacy flows, but it must be explicitly lower trust than a recorded slice packet.

## Terminology

- **Slice review packet**: A durable MCP-backed bundle for one completed implementation slice containing the slice label, owning task/lane context, changed files, verification evidence, contract/doc touches, and recommended review guide.
- **Review scope source**: The mechanism used to determine review files. For this task, valid values are `slice_packet` and `branch_diff`.
- **Review kind**: The high-level review workflow to run for the packet: `branch` or `planning`.
- **Packet-backed review**: A review run whose changed files and proof surfaces come from a recorded slice packet rather than current branch diff output.

## Current State Analysis

- `record_decision` already standardizes slice completion through `decision="slice_complete_<short_label>"` and required rationale headings in [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md).
- `record_worker_report` already stores `changed_files`, `test_commands`, blockers, and merge-readiness in [core.py](/packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py).
- `get_lane_activity` already aggregates lane-level decisions, tests, findings, worker reports, and messages, including `format="archival"`.
- `review_runner.py` and `review_ready.py` still determine changed files from live git diff state in the worktree, not from a completed-slice packet.
- `branch-review-guide.md` and `planning-review-guide.md` already distinguish review intent, but no MCP helper currently resolves "the latest completed slice" into the correct file set and guide choice.
- This means the repo has most of the ingredients for packet-backed review, but not the one query/helper that binds them together into a single intake surface.

## Target Outcome

Each completed slice produces one review packet in MCP. A reviewing agent can request "the latest completed slice for task X" and receive a deterministic file list, proof bundle, and review guide recommendation without reconstructing the slice from chat, commits, or current branch state. Branch-diff review remains available as a fallback, but the preferred path for cross-agent handoff is packet-backed review.

## Context Loading

- Rules: [planning-review-guide.md](/docs/agentic/rules/planning-review-guide.md), [branch-review-guide.md](/docs/agentic/rules/branch-review-guide.md), [instructions.md](/docs/agentic/instructions.md)
- Contracts: [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: inspect current `slice_complete_*` decision conventions, `record_worker_report` payload shape, and recent review-readiness/tooling decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: MCP server/tool resource design patterns need current upstream confirmation beyond local repo guidance

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Slice-completion handoff | agentic-tooling | [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md) | Add canonical slice review packet requirements tied to slice completion | Yes; existing slice-completion decisions still valid while packet fields are additive | pytest + contract doc |
| Review intake/query surface | agentic-tooling | [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md) | Add MCP query/helper for latest slice review packet, implemented through a dedicated orchestration helper module rather than growing `core.py` further | Yes; existing branch-diff review flow remains supported | pytest + CLI/proof run |
| Review runner dispatch | agentic-tooling | [branch-review-guide.md](/docs/agentic/rules/branch-review-guide.md), [planning-review-guide.md](/docs/agentic/rules/planning-review-guide.md) | Route packet-backed review to the correct guide and trust recorded file scope first | Yes; branch-diff fallback retained | pytest + smoke run |

## Proposed Solution

Add a first-class slice review packet to MCP and make review tooling consume it. First, define the packet contract and the minimum packet fields that must exist when a slice is completed. Second, add a query/helper that resolves the latest eligible slice packet from MCP state by combining slice-completion decisions, worker reports, plan-cursor context, and recorded tests. Third, teach review tooling to prefer packet-backed file scope and guide routing, while keeping branch-diff review as an explicit fallback. Finally, sync the review guides and handoff guidance so agents know when to use packet-backed review and what evidence must be present before a slice is considered review-ready.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Define slice review packet fields, latest-packet query/helper, and packet-vs-branch-diff trust model |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py` | Add packet derivation/query helpers and review-kind classification logic in a dedicated module |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Add a thin MCP-facing wrapper that delegates latest-slice packet lookup to the dedicated helper module |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Export the new query/helper on the MCP surface |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py` | Prefer packet-backed review scope when requested; fall back to branch diff only when needed |
| tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py` | Surface latest-slice readiness context and trust source in output when packet-backed review is requested |
| docs | `docs/agentic/rules/branch-review-guide.md` | Add guidance for reviewing the latest implementation slice from MCP packet state |
| docs | `docs/agentic/rules/planning-review-guide.md` | Add guidance for reviewing the latest planning slice from MCP packet state |
| test | `packages/agent-handoff-mcp/tests/test_handoff_state.py` | Add packet derivation/query tests |
| test | `packages/agent-handoff-mcp/tests/test_review_ready.py` | Add review intake/readiness tests for packet-backed review |
| test | `packages/agent-handoff-mcp/tests/test_review_runner.py` | Add or extend review runner tests for packet-backed file selection and guide routing |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/backend_adapter.py` | Existing structured `changed_files` payload shape |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` | Future source for measuring packet-backed review adoption if desired |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py` | Preferred home for packet derivation to avoid adding more coordination logic directly to `core.py` |
| `docs/tasks/12.0/selective-memory-and-evaluation-metrics-task-plan.md` | Recent selective-memory and actor-normalization work this task should build on |
| `docs/epics/v0.3.0/agentic-development-process-hardening-epic.md` | Governing epic for MCP/tooling hardening; this plan is a Phase 4 follow-on that reopens packet-backed review intake as remaining work rather than a new unrelated epic |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" PYENV_VERSION=description-service python3 -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py packages/agent-handoff-mcp/tests/test_review_ready.py packages/agent-handoff-mcp/tests/test_review_runner.py -q`
- Runtime-parity / environment checks:
  - Run the review helper from a worktree with both a packet-backed slice and a branch-diff fallback path
- Contract/fixture verification:
  - Verify [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md) documents the packet fields, required slice-completion linkage, and fallback semantics
- Manual verification:
  - From a dirty branch with at least two completed slices, confirm "review latest slice" resolves only the last slice packet files rather than all branch changes

## Slice Delivery

### Slice 1: Packet Contract and Derivation Rules

**Goal**: Define the canonical slice review packet and make it derivable from existing MCP state.

Changes:

- Add the packet contract to [agent-handoff-mcp.md](/docs/agentic/contracts/agent-handoff-mcp.md), including:
  - `slice_label`
  - `task_ref`
  - `lane_id`
  - `decision_id` / `decision`
  - `plan_item_id` or `plan_cursor_id` when available
  - `changed_files`
  - `test_commands`
  - `contract_files`
  - `review_kind`
  - `review_guide_path`
  - `scope_source`
- Define `review_kind` derivation explicitly:
  - caller-provided `review_kind` wins when present
  - otherwise infer `planning` when every `changed_file` is under `docs/` and no file falls under `apps/`, `packages/agent-handoff-mcp/src/`, `packages/shared-contracts/`, or another code/config boundary
  - otherwise infer `branch`
  - mixed doc-plus-code slices resolve to `branch`
- Define derivation rules that prefer:
  1. latest `slice_complete_*` decision
  2. nearest matching `record_worker_report`
  3. related plan cursor context
  4. related recent tests and contract/doc co-change evidence
- Explicitly document what happens when one ingredient is missing, and when fallback to branch diff is allowed

Proof:

- Contract doc has a complete packet schema and derivation order
- Focused tests prove derivation logic on complete and partial MCP state

### Slice 2: Latest Slice Review Packet Query

**Goal**: Expose one MCP query/helper that returns the latest completed slice review packet.

Changes:

- Add a dedicated helper module (`orchestration/slice_review_packet.py`) for packet derivation and `review_kind` classification, with `core.py` providing only the MCP-facing wrapper/query
- Support selecting latest packet by `task_ref`, optional `lane_id`, and `review_kind`
- Return packet metadata plus a clear `scope_source` field so reviewers know whether they are using a recorded packet or a fallback branch diff
- Keep the response additive; do not break existing handoff queries

Proof:

- Focused pytest covers latest-packet lookup, lane filtering, planning-vs-branch routing, and empty-state behavior
- MCP contract doc includes example request/response

### Slice 3: Packet-Backed Review Dispatch

**Goal**: Let review tooling consume the latest slice packet directly.

Changes:

- Update `review_runner.py` so a reviewer can request latest-slice review and have file scope come from the packet rather than current worktree diff
- Route packet-backed review to:
  - [branch-review-guide.md](/docs/agentic/rules/branch-review-guide.md) for implementation slices
  - [planning-review-guide.md](/docs/agentic/rules/planning-review-guide.md) for planning/documentation slices
- Preserve the existing branch-diff path as explicit fallback when no valid packet exists
- Update `review_ready.py` output or helper behavior so packet-backed review readiness and `scope_source` are visible

Proof:

- Tests verify packet-backed file selection wins over branch diff when available
- Tests verify guide routing for branch vs planning review
- Manual smoke run confirms "review latest slice" on a dirty branch reviews only the last slice packet files

### Slice 4: Guidance and Completion Semantics

**Goal**: Make packet-backed review the documented default for cross-agent slice review.

Changes:

- Update [branch-review-guide.md](/docs/agentic/rules/branch-review-guide.md) so reviewing the latest implementation slice prefers MCP packet scope over branch diff
- Update [planning-review-guide.md](/docs/agentic/rules/planning-review-guide.md) with the same rule for planning slices
- Update [instructions.md](/docs/agentic/instructions.md) if needed so slice completion guidance explicitly requires enough worker-report evidence for packet derivation
- Document packet-backed review as the preferred cross-agent handoff path for post-slice review

Proof:

- String-search verification confirms both review guides mention packet-backed latest-slice review
- Handoff contract and instructions are aligned on required slice-completion evidence

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed whether external dependency context requires `ctx7`.
- [x] Recorded boundary ownership and compatibility expectations for the new review packet surface.

## Slice 1: Packet Contract and Derivation Rules

- [x] Defined the canonical slice review packet fields in the MCP contract doc.
- [x] Defined deterministic derivation order from slice decision, worker report, plan cursor, and tests.
- [x] Added focused derivation tests.

## Slice 2: Latest Slice Review Packet Query

- [x] Added the MCP query/helper for latest slice packet lookup.
- [x] Exposed the query on the public MCP API surface.
- [x] Added tests for lane filtering, review-kind routing, and empty-state behavior.

## Slice 3: Packet-Backed Review Dispatch

- [x] Updated review tooling to prefer packet-backed file scope when requested.
- [x] Preserved explicit branch-diff fallback behavior.
- [x] Verified the correct review guide is selected for planning vs implementation slices.

## Slice 4: Guidance and Completion Semantics

- [x] Updated branch review guidance to prefer packet-backed latest-slice review.
- [x] Updated planning review guidance to prefer packet-backed latest-slice review.
- [x] Aligned slice-completion instructions with the evidence required for packet derivation.

## Review Readiness

- [x] No packet-backed review path depends on reconstructing slice scope from chat or commit memory alone.
- [x] Packet-backed review can explain whether its file scope came from MCP packet state or branch-diff fallback.
- [x] Handoff decision records the contract and verification changes for this review-intake improvement.

## Stretch Goals

- [x] Add adoption metrics for packet-backed review vs branch-diff fallback in ACE metrics after the base workflow lands.

## Success Criteria

- [x] An agent can ask to review the latest completed implementation slice and receive the correct file set from MCP without manual cherry-picking.
- [x] An agent can ask to review the latest planning slice and be routed to the planning review guide with packet-backed scope.
- [x] Cross-agent review of the latest slice remains reliable even when the branch contains additional unrelated changes after the slice was completed.
