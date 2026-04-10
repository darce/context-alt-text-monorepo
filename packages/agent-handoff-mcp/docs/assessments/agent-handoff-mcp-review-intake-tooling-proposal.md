# Agent Handoff MCP Review Intake Cold-Start Assessment Report

> **Metadata**
>
> - **Date**: 2026-04-10
> - **Author**: GPT-5.4
> - **Scope**: `packages/agent-handoff-mcp` and `packages/agent-orchestrator-mcp` review-intake surfaces
> - **Status**: Draft
>
> **Purpose:** This assessment examines why cold-start review and merge-readiness work still requires too much archaeology across MCP tools, even after the slice-review-packet work landed. It inventories the remaining intake gaps against current code, narrows them to the actual missing surfaces, and recommends a spec direction without prescribing implementation details.
>
> **Pipeline position:** **Assessment** → Spec → [ADR] → Task Plan → Implementation.

Cold-start review is no longer blocked on the total absence of a review packet; `agent-orchestrator-mcp` already provides a deterministic latest-slice packet. The remaining problem is narrower and more operationally relevant: reviewers still need multiple extra reads to connect that packet to concrete verification rows, open findings, and handoff-only fallback paths. That gap is large enough to make merge-readiness checks and post-implementation review more laborious than they should be, but small enough that the next stage should be a focused spec rather than another broad proposal.

**Related docs:**

- `docs/agentic/contracts/agent-handoff-mcp.md`
- `docs/agentic/contracts/agent-orchestrator-mcp.md`
- `docs/agentic/rules/branch-review-guide.md`
- `docs/agentic/rules/planning-review-guide.md`
- `docs/agentic/rules/planning-pipeline.md`
- `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-tool-surface-context-budget.md`

## Executive Summary

The recent worktree merge session was more laborious than a cold-start review flow should be, but not because the repo lacks any slice-level review packet. The current codebase already has an orchestrator-owned `get_latest_slice_review_packet` surface that resolves the latest `slice_complete_*` decision into a deterministic packet with decision provenance, changed files, test commands, contract files, review kind, and rationale excerpt. That means the core problem is not packet absence.

The actual cold-start gap is the join between that packet and the ledger detail that reviewers still need to answer merge-readiness questions quickly. The handoff database persists verified test rows, review findings, archived task snapshots, and searchable decision/findings history, but the current handoff read surface still splits those concerns across `load_session`, `search_handoff`, and direct list calls. `search_handoff` cannot search `verified_tests` at all, and handoff-only callers do not have a deterministic packet fallback when the orchestrator surface is unavailable or intentionally not loaded.

This means the assessed gaps would help a cold-start review process, but only partially. They would reduce the archaeology portion of review and merge-readiness work by collapsing packet discovery, verification lookup, and finding lookup into fewer deterministic reads. They would not eliminate the actual git work of merging, pruning worktrees, or resolving non-review operational state. The next step should therefore be a spec that extends the existing orchestrator packet and the handoff primitives together, while preserving the current boundary that keeps compound review-summary tools in orchestrator and ledger-native primitives in handoff.

## Findings

### F1. A deterministic latest-slice review packet already exists on `agent-orchestrator-mcp`

The current codebase already ships the packet that the earlier proposal treated as missing. The orchestrator contract registers `get_latest_slice_review_packet` as a cross-task and review-summary query surface, and the implementation returns a deterministic packet for the latest `slice_complete_*` decision. The packet includes `decision_id`, `decision`, `session`, `branch`, `commit_sha`, `changed_files`, `test_commands`, `contract_files`, `review_kind`, `scope_source`, and a rationale excerpt.

Current examples:

- `docs/agentic/contracts/agent-orchestrator-mcp.md:56` — the orchestrator contract lists `get_latest_slice_review_packet` as the query that resolves the latest slice-complete decision into a deterministic review packet.
- `docs/agentic/contracts/agent-orchestrator-mcp.md:267` — the contract documents the packet fields, including `changed_files`, `test_commands`, `contract_files`, `review_kind`, and `scope_source="slice_packet"`.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py:791` — the exported tool delegates to `get_latest_slice_review_packet_data(...)` and returns the packet as a first-class MCP response.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:282` — `get_latest_slice_review_packet_data(...)` resolves the latest slice-complete decision and filters by `review_kind` when requested.

**Impact:** Any planning artifact or spec that starts from “no canonical review packet exists” will duplicate existing ownership, overstate the problem, and send implementation work toward parallel tool surfaces instead of finishing the missing joins.

### F2. Verified test evidence is persisted in handoff but not queryable through the current review-intake search surface

The handoff ledger already stores `verified_tests` rows with command, pass/fail state, result text, session, branch, and commit SHA, but `search_handoff` cannot query them. The current FTS-backed search surface only supports `decision`, `finding`, `blocker`, and `action` record types. As a result, a reviewer can often find the latest slice packet and the high-level test commands, but still cannot retrieve the actual verification rows through the same review-intake search path.

Current examples:

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py:162` — the shared schema creates the `verified_tests` table as a first-class ledger table.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py:338` — test verification writes are inserted into `verified_tests` with `task_ref`, `command`, `passed`, `result`, `session`, `branch`, and `commit_sha`.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py:132` — `_VALID_RECORD_TYPES` includes only `decision`, `finding`, `blocker`, and `action`.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py:256` — `search_handoff(...)` validates against those four record types and therefore cannot search `verified_tests`.

**Impact:** Cold-start reviewers still need extra tool calls or ad hoc ledger archaeology to connect “a test command existed” with “a specific verified test row passed on commit X,” which slows review and merge-readiness checks.

### F3. Handoff-only callers still lack a deterministic review-intake fallback path

The current handoff read surface is task-centric rather than slice-centric. `load_session` returns handoff state plus open findings, and `search_handoff` returns FTS snippets over four tables, but neither surface reconstructs a slice packet. At the same time, the contracts explicitly place cross-task and review-summary tools on orchestrator. That means callers who only load the handoff server still fall back to multiple reads when they need slice-level review context.

Current examples:

- `docs/agentic/contracts/agent-handoff-mcp.md:82` — `load_session` is documented as a compound session-start helper that combines `get_handoff_state` with open findings, not as a slice-level review packet.
- `docs/agentic/contracts/agent-handoff-mcp.md:89` — the handoff contract explicitly states that cross-task and review-summary tools, including `get_latest_slice_review_packet`, live on `agent-orchestrator-mcp`.
- `docs/agentic/contracts/agent-handoff-mcp.md:206` — the handoff contract documents `search_handoff` as FTS over canonical handoff records, not a deterministic slice reconstruction path.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py:73` — the handoff API description for `load_session` confirms it is a state + open-findings helper.

**Impact:** This is the part of the gap that would have helped the recent cold-start merge review. It would not have performed the merge or pruned worktrees, but it would have reduced the repeated evidence-gathering needed to answer “what exactly changed, what passed, what findings remain, and is this slice merge-ready?”

### F4. The ownership boundary for compound vs. primitive review-intake tools is already explicit

The current contracts already divide responsibilities between the two MCP packages: compound cross-task review-summary tools belong to orchestrator, while ledger-native primitives belong to handoff. Any future work that ignores this split will re-open the ownership confusion that the packaging work already resolved.

Current examples:

- `docs/agentic/contracts/agent-orchestrator-mcp.md:51` — the orchestrator contract groups `get_latest_slice_review_packet` under “Cross-task and Review-summary Tools.”
- `docs/agentic/contracts/agent-handoff-mcp.md:89` — the handoff contract points those cross-task and review-summary tools back to orchestrator.
- `packages/agent-handoff-mcp/docs/epics/agent-handoff-mcp-packaging-epic.md:58` — the packaging epic records that `get_latest_slice_review_packet` is owned by `agent-orchestrator-mcp`, not handoff.

**Impact:** The next stage must extend the existing boundary instead of moving it. Otherwise the resulting design will produce duplicate packet logic on handoff and orchestrator, increasing tool-surface and maintenance cost.

### F5. The existing slice packet already contains multi-source fallback logic that should not be reimplemented independently

The current packet implementation does more than read `changed_files_json` from a decision row. It falls back to worker reports and then to rationale parsing for changed files, and it falls back to `verified_tests` rows when worker report test commands are missing. This means any new review-intake surface that reconstructs the same packet independently risks drifting from the orchestrator packet semantics.

Current examples:

- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:69` — `_extract_changed_files_from_rationale(...)` derives changed files from the decision rationale when structured file lists are missing.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:140` — `_matching_worker_report(...)` selects the best matching worker report using commit and branch signals.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:182` — `_matching_test_commands(...)` derives test commands from `verified_tests` rows when worker-report data is absent.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py:219` — `_build_packet_for_decision(...)` assembles the packet from decision JSON, worker-report fallbacks, rationale fallbacks, and verified-test lookups.

**Impact:** A spec that introduces a second packet builder on handoff without explicitly reusing or delegating to this logic will create inconsistent changed-file and test-command results across two nominally equivalent review-intake paths.

## Recommendations

### 1. Extend the existing orchestrator packet instead of inventing a second compound packet on handoff

**Traces:** F1, F4, F5
**Priority:** P0

The next stage should treat `get_latest_slice_review_packet` as the canonical compound packet and define only the missing additions around it. In practice that means the spec should start from “what data is still missing from the existing packet?” rather than “what brand-new packet tool should exist?” This keeps compound review-summary ownership aligned with orchestrator and avoids reimplementing packet assembly logic.

### 2. Add handoff-side primitive reads for verification evidence and exact decision lookup

**Traces:** F2, F3, F4
**Priority:** P1

The handoff package should gain only the narrow primitive reads needed to support cold-start review without ad hoc archaeology. The assessment does not prescribe whether that becomes `verified_test` support in `search_handoff`, a separate exact lookup primitive, or both; it does establish that the ledger already stores the data and that current handoff search/read surfaces are insufficient for deterministic review intake.

### 3. Define a handoff-only fallback path explicitly in the next spec

**Traces:** F3, F4
**Priority:** P1

The remaining cold-start gap is most acute when the orchestrator surface is unavailable, not loaded, or intentionally out of scope for a caller. The next spec should make that fallback explicit instead of leaving agents to infer it from `load_session`, `search_handoff`, and review-findings list calls. Whether the fallback is packet-shaped or a documented multi-call sequence is a spec question; the missing boundary definition is the assessment-level problem.

### 4. Treat documentation work as adoption and fallback clarification, not as invention of packet-first review guidance

**Traces:** F1, F3
**Priority:** P2

The review guides already prefer packet-first latest-slice review. The remaining documentation work should therefore focus on clarifying the handoff-only fallback, examples that join packet data to verification rows and findings, and sequencing that lands guidance as soon as the new primitives exist. The next stage should not start from the assumption that the guides lack any packet-first intake guidance today.

## Code-Verified Critique

### What the assessment gets right

- The cold-start review gap is real, but it is narrower than “no review packet exists.” The code verifies that the missing joins are verification-row access and handoff-only fallback, not packet existence.
- `verified_tests` are already durable ledger rows, and the current review-intake search surface still cannot query them.
- The handoff/orchestrator boundary is already explicit in the contracts and packaging docs; the next stage must respect it.

### Where the assessment overstates the problem

- The earlier document overstated the packet gap. `get_latest_slice_review_packet` already exists and is explicitly documented in both contract and implementation paths (`docs/agentic/contracts/agent-orchestrator-mcp.md:56`, `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py:791`).
- The earlier document overstated the documentation gap. Both review guides already tell reviewers to prefer the latest-slice packet before diff archaeology (`docs/agentic/rules/branch-review-guide.md:61`, `docs/agentic/rules/planning-review-guide.md:80`).
- The recent worktree merge effort would not have become a one-call workflow even with the missing intake surfaces. Git merge, worktree prune, and task-lifecycle cleanup remain separate operational steps outside the review-intake packet problem.

### Recommendations the assessment is missing

- **R-MISS-1: Merge-readiness is adjacent to, but not identical with, review intake.** `handoff_close_check` already evaluates blockers, pending actions, open findings, and fresh-test evidence (`docs/agentic/contracts/agent-handoff-mcp.md:79`), but it is separate from slice packet intake. A future spec should decide whether review intake needs a direct bridge to close-check output or whether that remains a distinct post-review step.
- **R-MISS-2: Current guide guidance reduces the documentation scope.** Because the branch and planning guides already instruct packet-first review, the remaining doc work is primarily examples and fallback clarification, not the creation of a brand-new “preferred MCP intake” concept.

## Priority Ordering

| Priority | Change                                                                                               | Impact                                                                    | Effort | Trace      |
| -------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------ | ---------- |
| **P0**   | Extend the existing orchestrator slice packet instead of creating a parallel handoff compound packet | Prevents duplicate ownership and packet drift                             | Medium | F1, F4, F5 |
| **P1**   | Add handoff-side primitive access to verified test evidence and exact decision lookup                | Removes the main cold-start archaeology gap after packet lookup           | Medium | F2, F3     |
| **P1**   | Define a handoff-only review-intake fallback explicitly                                              | Improves cold-start review when orchestrator is unavailable or not loaded | Medium | F3, F4     |
| **P2**   | Add examples and fallback guidance to existing review docs                                           | Improves adoption without reworking already-correct review guidance       | Small  | F1, F3     |

## Deferred or Rejected Directions

- A second compound `get_review_packet` implemented independently inside `agent-handoff-mcp` is not recommended at this stage because it duplicates existing orchestrator ownership and packet assembly logic.
- A five-tool expansion of the intake surface is not recommended before a narrower spec proves that the missing cold-start joins cannot be closed by extending the current packet plus a small number of primitives.

## Suggested Spec Direction

Write a cross-package spec, not another proposal document. The spec should live at monorepo scope because the work spans `packages/agent-handoff-mcp` and `packages/agent-orchestrator-mcp`, and it should start from the existing orchestrator packet as the canonical compound surface. Tier 1 items should cover: packet extensions for findings and verification evidence, handoff primitive access to verified-test rows and exact decision lookup, and explicit fallback guidance. Any boundary-changing idea that moves compound review-summary ownership from orchestrator back into handoff should be treated as ADR-gated Tier 3 work.

## Next Step

- [x] ADR-007 written: `docs/adrs/ADR-007-review-intake-handoff-fallback-boundary.md` — resolves the design question of how handoff-only callers access review-intake data without reimplementing the orchestrator packet
- [x] ADR-007 remains the governing boundary decision for the follow-on work — Tier 1 and Tier 2 tasks implement within its guardrails; any future compound handoff packet idea remains ADR-gated
- [x] Write the package-local spec: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md` — translates F2/F3 plus ADR-007 into concrete Tier 1 and Tier 2 items
- [x] Create Tier 1 implementation task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-8-verified-test-search-and-read-surfaces-task-plan.md` — implements searchable verified tests and the `get_verified_tests` primitive read
- [x] Create Tier 2 adoption-docs task plan: `packages/agent-handoff-mcp/docs/tasks/AHMCP-9-review-intake-fallback-adoption-docs-task-plan.md` — lands contract/review-guide fallback guidance after Tier 1 ships

## References

- `docs/agentic/contracts/agent-handoff-mcp.md`
- `docs/agentic/contracts/agent-orchestrator-mcp.md`
- `docs/agentic/rules/branch-review-guide.md`
- `docs/agentic/rules/planning-review-guide.md`
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/lanes.py`
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py`
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py`
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`
