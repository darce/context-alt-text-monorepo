# AHMCP-8. Verified Test Search and Read Surfaces

> **Metadata**
>
> - **Date**: 2026-04-10 02:25 EST
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-8`
> - **Target Branch**: `feature/ahmcp-8-verified-test-search-and-read-surfaces`
> - **Review Coverage Target**: 2
> - **Expected Review Path**: ordinary branch review plus specialized review of handoff FTS/search semantics
> - **Spec**: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md`

---

## Objective

Implement `RIF-001` and `RIF-002` by making `verified_tests` searchable through `search_handoff` and by adding a dedicated `get_verified_tests` read surface. When this task is complete, handoff-only callers can discover and retrieve verification rows deterministically without reconstructing them from packet text or raw SQL.

## Problem Statement

`agent-handoff-mcp` already stores verified test rows, but the current read surface still treats them as write-only data from a cold-start review perspective. `search_handoff` only indexes decisions, findings, blockers, and actions, and no public tool lists verification rows directly. That leaves ADR-007's fallback flow under-specified in code: callers can find a slice-complete decision, but not the concrete verification rows that prove what passed on a given branch or commit.

## Constraints

- ADR-007 is binding: no compound `get_review_packet`-style tool may be added to handoff.
- No imports from `agent_orchestrator_mcp` are allowed in handoff implementation code.
- `verified_tests_fts` must use the same FTS5 tokenizer, trigger pattern, bootstrap checks, and backfill strategy as the existing handoff FTS tables.
- Contract documentation for the new read surface and record type must land in the same task as the code changes.
- In-monorepo package verification must use `cd packages/agent-handoff-mcp && make test-handoff`, not a direct `pytest` invocation.

## Workflow Principles

- Keep the preferred packet-first review path unchanged; this task adds only the handoff fallback primitives.
- Land search/index work before the new read tool so contract and tests can validate the primitive layering in sequence.
- Treat `verified_tests` as ledger-native evidence; do not derive or reassemble packet fields in handoff.

## Terminology

- **Verified test row**: A row in `verified_tests` written by `record_test_result` / `record_event(event_kind="test_result")`.
- **Fallback primitive**: A handoff-native read that supports review intake when orchestrator is unavailable.
- **FTS parity**: Matching tokenizer, trigger, bootstrap, and backfill behavior across all handoff FTS tables.

## Current State Analysis

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` already defines the `verified_tests` table, but no `verified_tests_fts` table or triggers exist.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` limits `search_handoff` to `decision`, `finding`, `blocker`, and `action` record types.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` exposes no public `get_verified_tests` read tool.
- `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py` already consumes `verified_tests` rows as part of packet fallback; this task must not copy that packet assembly logic into handoff.

## Target Outcome

The handoff package exposes two deterministic review-intake primitives: searchable verified tests and exact verified-test listing. A caller can locate the relevant slice decision with `search_handoff`, then retrieve the matching verification rows through `get_verified_tests` filtered by task, lane, branch, or commit SHA. The handoff contract documents both surfaces, and the proof suite covers search, filter, ordering, and bootstrap behavior.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Contracts:
  - `docs/agentic/contracts/agent-handoff-mcp.md`
  - `docs/agentic/contracts/agent-orchestrator-mcp.md`
- Handoff/MCP state: active findings for the planning task; ADR-007 boundary rules
- External docs via `ctx7` only if: FTS5 or FastMCP behavior proves ambiguous from the live codebase

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Handoff search surface | `agent-handoff-mcp` | `search_handoff` supports 4 record types | Add `verified_test` as a fifth searchable record type | Yes; preserve existing result shape and invalid-type behavior for all existing record types | `make test-handoff` plus search regression coverage |
| Handoff read surface | `agent-handoff-mcp` | No public read tool lists `verified_tests` rows | Add `get_verified_tests` with bounded filters and ordering | Yes; response must follow the v2 envelope and use existing stored columns only | `make test-handoff`, contract doc update |
| Review packet boundary | `agent-orchestrator-mcp` | `get_latest_slice_review_packet` remains the compound review surface | No change | Yes; handoff must not reimplement packet assembly | Code review against touched files and no orchestrator imports |

## Proposed Solution

Extend the handoff FTS/search layer first, then add the explicit verified-test read tool on top of the existing ledger table. The implementation stays package-local to `agent-handoff-mcp` plus its owning contract doc. Tests cover the new searchable record type, bootstrap/backfill behavior, and exact-list filtering so the later documentation task can describe a real public interface instead of a proposed one.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Schema bootstrap | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py` | Add `verified_tests_fts`, triggers, required-table checks, and backfill wiring |
| Search surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Extend record-type validation and FTS mapping for `verified_test` |
| Public tool registry | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Register `get_verified_tests` and document its parameters |
| Verified-test read path | `packages/agent-handoff-mcp/src/agent_handoff_mcp/` | Add the concrete query helper in the appropriate handoff-owned module |
| Search tests | `packages/agent-handoff-mcp/tests/test_search_handoff.py` | Add coverage for verified-test indexing, search, and invalid/valid type behavior |
| Read tests | `packages/agent-handoff-mcp/tests/` | Add or extend tests for `get_verified_tests` filtering and ordering |
| Contract docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Document `verified_test` and `get_verified_tests` |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/decisions.py` | Existing verified-test writer; query semantics must align with stored columns |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/slice_review_packet.py` | No edits expected; reference-only boundary check |
| `docs/agentic/adrs/ADR-007-review-intake-handoff-fallback-boundary.md` | Decision guardrails for this task |
| `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md` | Source of `RIF-001` and `RIF-002` |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && make test-handoff`
- Contract/fixture verification:
  - `cd packages/agent-handoff-mcp && make mypy-handoff`
  - `rg -n "verified_test|get_verified_tests" packages/agent-handoff-mcp/src docs/agentic/contracts/agent-handoff-mcp.md`
- Runtime-parity / environment checks:
  - none required for this ledger/read-only scope
- Manual verification:
  - Inspect one successful `search_handoff(... record_types=["verified_test"])` result and one `get_verified_tests(commit_sha=...)` result through the MCP surface after implementation

## Slice Delivery

### Slice 1: Searchable Verified Test Evidence

**Goal**: Implement `RIF-001` by giving `search_handoff` first-class access to verified test rows.

Changes:

- Add `verified_tests_fts` plus insert/update/delete triggers and bootstrap/backfill coverage.
- Extend `_VALID_RECORD_TYPES` and `_RECORD_TYPE_FTS_MAP` with `verified_test`; `verified_tests_fts` must follow the spec's `("verified_tests_fts", False)` mapping and remain status-less.
- Update search tests and schema/bootstrap tests in the same slice.
- Update the handoff contract to list `verified_test` as a supported search record type.

Proof:

- `cd packages/agent-handoff-mcp && make test-handoff`

### Slice 2: Exact Verified Test Listing

**Goal**: Implement `RIF-002` by adding `get_verified_tests` as a bounded public read.

Changes:

- Add the `get_verified_tests` query surface with task/lane/branch/commit/pass filters and bounded ordering.
- Add typed API registration and contract documentation in the same slice.
- Add regression tests for default active-task scope, filter combinations, and sort order.

Proof:

- `cd packages/agent-handoff-mcp && make test-handoff`
- `cd packages/agent-handoff-mcp && make mypy-handoff`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded ADR-007, the review-intake spec, and the handoff/orchestrator contracts before editing.
- [ ] Confirmed no orchestrator packet logic is reimplemented on handoff.
- [ ] Recorded the contract/doc touchpoints in the same slices as the behavior changes.

### Checklist for Slice 1: Searchable Verified Test Evidence

- [ ] Add `verified_tests_fts` with trigger and backfill coverage.
- [ ] Extend `search_handoff` to accept `verified_test`.
- [ ] Add search/schema regression coverage.
- [ ] Update the handoff contract doc for the new search record type.

### Checklist for Slice 2: Exact Verified Test Listing

- [ ] Add `get_verified_tests` with bounded filters and ordering.
- [ ] Register and document the new public tool.
- [ ] Add regression coverage for task/lane/branch/commit/pass filters.
- [ ] Capture `make test-handoff` and `make mypy-handoff` evidence.

## Review Readiness

- [ ] No compound review-packet behavior has been introduced on handoff.
- [ ] Contract and test updates land in the same slices as the implementation.
- [ ] Handoff decision records the search/read additions and the proof commands.

## Stretch Goals

- [ ] Add summary-field projection or detail modes to `get_verified_tests` if the baseline read proves too verbose during implementation.

## Success Criteria

- [ ] `search_handoff` can return `verified_test` hits backed by `verified_tests_fts`.
- [ ] `get_verified_tests` returns deterministic filtered rows without raw-SQL archaeology.
- [ ] The handoff contract documents both new primitives accurately.