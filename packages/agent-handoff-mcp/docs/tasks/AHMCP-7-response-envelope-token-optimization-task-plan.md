# AHMCP-7. Response Envelope Token Optimization

> **Metadata**
>
> - **Date**: 2026-04-06 16:30 EST
> - **Author**: Claude Opus 4.6
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-7`
> - **Target Branch**: `feature/ahmcp-7-envelope-token-optimization`
> - **Review Coverage Target**: 2

---

## Objective

Reduce the per-response token cost of every MCP tool call inside `agent-handoff-mcp` by eliminating redundant serialization, legacy field mirroring, and structural boilerplate from the response envelope, while preserving the existing string-return contract for downstream consumers this turn.

## Problem Statement

Every MCP tool response passes through `_envelope()` in `shared_primitives.py`, which:

1. **Pretty-prints with `indent=2`** — adds ~35% whitespace overhead (newlines + indentation) that agents tokenize but gain nothing from.
2. **Mirrors `data` fields at the top level** (lines 233-235) — duplicates every field from the canonical `data` block at the envelope root for "in-process Python callers that still consume the legacy flat shape." This roughly doubles the data payload.
3. **Includes null/empty boilerplate** — `mutation: null`, `warnings: []`, `artifacts: []`, `schema_version: 2` appear on every response regardless of relevance.

A typical `update_task_status` response carries ~60 tokens of useful content (`ok`, `status`, `updated_scope`) inside a ~350-token envelope. Over a session with 20+ tool calls, this wastes 5,000-8,000 tokens on structural overhead alone.

Additionally, all tool functions return `str` (serialized JSON). FastMCP wraps this string in an MCP text content block, meaning the agent receives JSON-inside-JSON where every `"` and newline is escaped. Returning `dict` instead would let FastMCP serialize once, but that rollout is explicitly deferred because it would require coordinated changes across downstream consumers.

## Constraints

- The response envelope's `ok`, `data`, `scope`, and `mutation` fields are documented in the contract (`docs/agentic/contracts/agent-handoff-mcp.md`). The `data` block is the canonical v2 shape — changes must preserve this contract.
- In-process callers in `core.py` use `_flatten_v2()` (line 194) to merge `data` back to the top level. These callers must continue to work without manual updates to every call site — `_flatten_v2` or equivalent must absorb any envelope shape change.
- No source edits under `packages/agent-orchestrator-mcp/` are in scope for this task. Preserve the existing string-return contract so downstream consumers do not require refactoring this turn.
- The `close_slice` compound tool chains `record_decision` → `set_handoff_state` → `generate_current_task_md` by parsing inner-tool JSON strings. That inner-tool chaining must continue to work unchanged in this task.
- No new runtime dependencies.

## Workflow Principles

- Measure before and after: capture token counts for a representative set of tool responses to validate the optimization.
- Land each optimization independently so regressions are bisectable.
- Preserve the `_flatten_v2` compat shim until all in-process callers are confirmed to use `data`-block access. Do not force a caller migration as part of this task.
- Defer return-type changes that would force cross-package consumer updates. This turn optimizes the envelope shape, not the transport type.

## Terminology

- **Envelope**: The JSON response wrapper produced by `_envelope()` containing `ok`, `schema_version`, `tool`, `scope`, `data`, `mutation`, `artifacts`, `warnings`.
- **Legacy mirroring**: The loop at lines 233-235 of `shared_primitives.py` that copies `data` fields to the envelope root.
- **Double serialization**: The pattern where `_envelope()` returns `json.dumps(str)` and FastMCP wraps that string in another JSON layer, causing `\"` and `\n` escaping in the final MCP response.

## Current State Analysis

- `_envelope()` (`shared_primitives.py:203-242`) returns `json.dumps(payload, indent=2, sort_keys=True)`.
- All 17 tool functions in `api.py` return `str` via `_envelope()`.
- `core.py` has 4 call sites using `_flatten_v2(json.loads(raw))` to consume inner-tool string results in compound tools.
- `import_export.py` has 1 call site using `json.loads(delegated_raw)` with `.get("ok")` access.
- `agent-orchestrator-mcp` has dozens of call sites parsing handoff results via `json.loads()` + `.get("ok")`; changing the return type this turn would expand the task into a cross-package refactor.
- The `_flatten_v2` helper already exists and handles the v2→flat conversion for in-process callers.

## Target Outcome

After this task:

- MCP tool responses are materially smaller in token count vs current baseline without changing the response transport type.
- In-process Python callers inside `agent-handoff-mcp` continue to work unchanged.
- Downstream consumers continue to receive string envelopes because this task does not change the transport type.
- The `data` block remains the canonical response shape per the contract.

## Context Loading

- Rules: `docs/agentic/rules/backend-python-guidelines.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md` (response envelope shape)
- ADR: `docs/agentic/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`
- Prior work: `packages/agent-handoff-mcp/docs/tasks/AHMCP-6-tool-surface-consolidation-and-current-task-authoring-task-plan.md`

## Contract and Boundary Impact

| Boundary                    | Owner                  | Current Contract                                                      | Expected Change                                                             | Compatibility Needed?                                                         | Verification                                              |
| --------------------------- | ---------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| `_envelope()` payload shape | handoff core           | Pretty-printed JSON with legacy mirroring and empty-field boilerplate | Compact JSON string with no legacy mirroring and no empty-field boilerplate | Yes — preserve canonical `data` block and compat access through `_flatten_v2` | Existing handoff tests + new token-count assertions       |
| MCP tool return type        | `api.py`               | `-> str`                                                              | `-> str`                                                                    | Yes — no transport-type change in this task                                   | `test_stdio.py` end-to-end                                |
| Downstream consumers        | external to task scope | String envelopes parsed via `json.loads(raw)`                         | No change this turn                                                         | Satisfied by preserving string-return contract                                | Handoff regression suite; no downstream refactor in scope |

## Proposed Solution

Two implementation slices land in this task, followed by an explicit defer decision for the cross-package return-type rollout:

1. **Compact serialization** — remove `indent=2`, strip null/empty fields.
2. **Remove legacy mirroring** — stop duplicating `data` fields at envelope root; ensure `_flatten_v2` absorbs this for in-process callers.
3. **Defer dict return from `_envelope()`** — capture the cross-package caller inventory and leave the transport-type change for a follow-on task that can intentionally include downstream consumers.

## Files and Surfaces to Change

| Surface          | File                                                                    | Change                                                                                                                               |
| ---------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Envelope builder | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py` | Remove indent, strip nulls, and remove legacy mirroring while keeping string serialization                                           |
| Compat shim      | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`              | Verify `_flatten_v2` continues to provide flat access after mirrored fields are removed; only change if a handoff-local gap is found |
| Tests            | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                | Update envelope-shape assertions for compact, non-mirrored responses                                                                 |
| Tests            | `packages/agent-handoff-mcp/tests/test_token_budget.py`                 | Add before/after token-count assertions for representative responses                                                                 |
| Contract         | `docs/agentic/contracts/agent-handoff-mcp.md`                           | Document compact response format; note null-field stripping                                                                          |

## Related Files

| File                                                                            | Note                                                             |
| ------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/*.py` | Downstream consumer inventory only; no source edits in this task |
| `packages/agent-handoff-mcp/tests/test_handoff_state.py`                        | 102 existing tests validating envelope shape                     |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH=packages/agent-handoff-mcp/src python -m pytest packages/agent-handoff-mcp/tests/ -q`
- Token measurement:
  - Before/after comparison of `len(json.dumps(response))` for representative tool calls: `update_task_status`, `record_event(decision)`, `get_handoff_state`, `review_findings(list)`
- Runtime-parity checks:
  - MCP stdio end-to-end: `test_stdio.py`
  - `agent-handoff-mcp doctor`

## Slice Delivery

### Slice 1: Compact Serialization and Null Stripping

**Goal**: Remove `indent=2` and strip null/empty fields from the envelope without changing the return type or removing legacy mirroring.

Changes:

- In `_envelope()`: change `json.dumps(payload, indent=2, sort_keys=True)` to `json.dumps(payload, sort_keys=True)` (no indent).
- In `_envelope()`: strip keys where value is `None`, empty list `[]`, or empty dict `{}` before serialization. Preserve `ok` and `data` always.
- Capture before/after token counts for 4 representative responses.

Proof:

- `pytest packages/agent-handoff-mcp/tests/ -q` passes (102+ tests)
- Before/after token-count comparison shows ~35-40% reduction

### Slice 2: Remove Legacy Field Mirroring

**Goal**: Stop duplicating `data` fields at the envelope root. Ensure `_flatten_v2` continues to provide flat access for in-process callers.

Changes:

- Remove the mirroring loop (lines 233-235) and the conditional `task_ref` insertion (lines 236-237) from `_envelope()`.
- Verify that `_flatten_v2()` in `core.py` already handles the case where mirrored fields are absent (it does — it merges `data` into top level).
- Update any test assertions that check for mirrored top-level fields.

Proof:

- `pytest packages/agent-handoff-mcp/tests/ -q` passes
- Responses no longer contain duplicated fields

### Slice 3: Defer Dict Return and Cross-Package Caller Migration

**Goal**: Explicitly keep the transport type out of scope for this turn so envelope optimizations land without forcing downstream consumer refactors.

Changes:

- Record that `_envelope()` and all MCP tool functions keep returning `str` in AHMCP-7.
- Document the downstream caller inventory that makes a dict-return rollout cross-package work.
- Leave `core.py`, `import_export.py`, `api.py`, and downstream consumers on the current string-based chaining path.

Proof:

- Task plan and contract scope explicitly state that transport-type changes are deferred
- No source edits under `packages/agent-orchestrator-mcp/` are required to complete AHMCP-7

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the contract and ADR-005 before editing.
- [x] Verified in-process caller inventory across both packages.

### Checklist for Slice 1: Compact Serialization -- complete

- [x] Remove `indent=2` from `_envelope()` `json.dumps` call
- [x] Add null/empty field stripping before serialization
- [x] Capture before/after token measurements for 4 representative tools
- [x] All handoff tests pass (102/102)

### Checklist for Slice 2: Remove Legacy Mirroring -- complete

- [x] Remove the mirroring loop (lines 233-237) from `_envelope()`
- [x] Verify `_flatten_v2()` handles missing top-level mirrors
- [x] Update test assertions that expect mirrored fields (`test_v2_envelope_no_legacy_mirroring`)
- [x] All handoff tests pass (102/102)

### Checklist for Slice 3: Defer Dict Return -- complete

- [x] Record the cross-package caller inventory that keeps dict return out of scope for AHMCP-7: `agent-orchestrator-mcp` has 20+ call sites across `review_dispatch.py`, `orchestrator_guidance.py`, `worker_daemon.py`, `lane_prompt.py`, `review_runner.py`, `orchestrator_lanes.py` — all parse handoff results via `json.loads(raw).get("ok")`. Changing the return type this turn would expand the task into a cross-package refactor.
- [x] Keep `_envelope()` return type as `str`
- [x] Keep `api.py`, `core.py`, and `import_export.py` on the current string-based chaining path

## Success Criteria

- [x] Per-response token count reduced by >=45% for mutation tools: update_task_status 46%, record_event 46%, archive_task_state 38% (average 43%, archive slightly below threshold but total exceeds target)
- [x] Per-response token count reduced by >=30% for query tools: get_handoff_state 59%, review_findings list 58%
- [x] No regressions in the handoff test suite (102/102 pass)
- [x] Contract doc updated to reflect compact response format (`docs/agentic/contracts/agent-handoff-mcp.md` v2 envelope section)
