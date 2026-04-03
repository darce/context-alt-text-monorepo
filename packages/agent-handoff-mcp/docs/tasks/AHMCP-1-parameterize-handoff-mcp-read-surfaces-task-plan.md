# AHMCP-1. Parameterize Handoff MCP Read Surfaces

> **Metadata**
>
> - **Date**: 2026-04-01
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-1`
> - **Target Branch**: `feature/ahmcp-1-parameterize-reads`
> - **Review Coverage Target**: 2

---

## Objective

Reduce MCP handoff schema and payload cost by expanding existing read tools with projection, detail, and section parameters instead of proliferating narrowly scoped read tools. Preserve explicit write semantics and the existing handoff audit trail while making startup and targeted lookups cheaper for clients.

## Problem Statement

`agent-handoff-mcp` currently spreads read behavior across a few fixed-shape tools: `get_handoff_state` returns a broad task snapshot with limited shaping controls, `list_review_findings` supports filtering but not projection or summary-only modes, and `load_session` duplicates state-plus-findings as a separate compound read. That makes the tool surface larger than it needs to be and forces clients to ingest broad response payloads even when they only need hot-state identity, counts, or one narrow section.

## Constraints

- Keep write and lifecycle tools explicit; do not collapse `record_decision`, `record_test_result`, `update_review_finding`, `close_slice`, or import/export actions behind generic mode flags.
- Prefer additive, compatibility-managed parameterization for read tools before any tool removal or deprecation.
- Preserve the current handoff contract semantics for task scoping, review-finding lookup, and `CURRENT_TASK` generation unless the task plan explicitly changes them.
- Keep core versus extended tool-profile behavior coherent; parameter changes must not silently move write-heavy or search-heavy surfaces between profiles.
- CLI wrappers, MCP tool descriptions, tests, and contract docs must stay in sync with the live tool signatures.

## Workflow Principles

- Consolidate read behavior by shaping outputs with parameters such as `sections`, `detail`, `fields`, and `include_*`; do not add one-off read tools for every new view.
- Optimize the largest payload contributors first, especially decision rationales, test command strings, and full finding bodies.
- Treat a smaller tool count as secondary to slimmer result payloads; response shaping helps all clients, while fewer tool definitions only helps when clients inject the full schema into prompt context.
- Stage deprecations conservatively; compatibility aliases are acceptable for read tools during migration, but the end state should favor one primary read surface per data family.

## Terminology

- **Read surface**: A query or generator tool that returns handoff state without mutating it.
- **Projection**: Returning only selected sections or fields from a larger logical payload.
- **Detail mode**: A parameter that controls text verbosity, such as omitting or truncating rationale and command strings.
- **Compound read**: A tool like `load_session` that bundles multiple underlying reads into one response.
- **Explicit write**: A mutating tool with a single clear audit meaning, such as recording a decision or closing a finding.

## Current State Analysis

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` exposes `get_handoff_state` with limits, `verbose`, `view`, and `include_archived`, but it still returns a mostly fixed response shape for task views.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` exposes `list_review_findings` with filtering and pagination, but it does not support summary-only reads, field projection, or grouping-oriented outputs.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` exposes `load_session` as a separate compound read that largely duplicates `get_handoff_state` plus open findings.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` and its `ToolEntry` / `ArgSpec` registry define the MCP and CLI schema shape, so every extra read tool adds prompt-schema and adapter-surface cost.
- The current contract already emphasizes hot, warm, and cold selective loading, but the live read tools do not yet fully support that guidance with shaped responses.

## Target Outcome

The handoff server exposes one primary task-state read surface and one primary review-findings read surface, each with enough parameters to cover hot-state startup, dashboard views, summary-only queries, and targeted detail retrieval. `load_session` becomes either a thin compatibility wrapper over parameterized reads or a staged deprecation candidate, while explicit write tools remain separate and unchanged.

## Context Loading

- Rules: `docs/agentic/instructions.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`
- Handoff/MCP state: `task_ref=AHMCP-1`; recent decision `ghc_design_note_handoff_tool_surface_parameterization`
- External docs via `ctx7` only if FastMCP tool-schema behavior or optional-argument encoding needs confirmation for list-valued/read-projection parameters

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP read-tool schema | handoff core | `docs/agentic/contracts/agent-handoff-mcp.md` | Add projection/detail parameters to existing read tools; possibly mark `load_session` as compatibility-only | Yes; additive first, then explicit deprecation | contract doc + stdio/http tool smoke tests |
| CLI read-tool wrappers | handoff core | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` ArgSpec registry | Add matching CLI flags for new read parameters | Yes; keep existing commands working | CLI smoke tests |
| CURRENT_TASK and handoff consumers | handoff core | `get_handoff_state` task payload shape | No required behavior change; new params should be optional | Yes; default behavior must remain stable | CURRENT_TASK + handoff-state regression tests |
| Review-finding consumers | handoff core | `list_review_findings` response shape | Add summary/projection modes without breaking default full-detail listing | Yes; default listing remains stable | review-finding regression tests |

## Proposed Solution

Parameterize the existing read tools instead of inventing more narrowly scoped ones. Extend `get_handoff_state` with section and detail controls that align with hot/warm/cold loading, extend `list_review_findings` with projection-oriented options for summary and field selection, and rework `load_session` into a compatibility wrapper or staged deprecation path once the parameterized reads can express the same use cases.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Task-state read surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py` | Add `sections`, `detail`, or equivalent shaping parameters to `get_handoff_state` |
| Review-finding read surface | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py` | Add summary/projection parameters to `list_review_findings` |
| Compound read wrapper | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Rework `load_session` to call parameterized reads or mark it deprecated |
| MCP/CLI registry | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Update tool descriptions, CLI args, and any deprecation markers |
| Contract docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Document new parameters, default behavior, and any staged deprecation guidance |
| Task-state tests | `packages/agent-handoff-mcp/tests/test_handoff_state.py` | Add regression coverage for section/detail shaping and compatibility defaults |
| Review-finding tests | `packages/agent-handoff-mcp/tests/test_review_findings.py` | Add regression coverage for summary/projection modes |
| CLI / transport tests | `packages/agent-handoff-mcp/tests/test_cli.py` | Verify new flags and default compatibility |
| CLI / transport tests | `packages/agent-handoff-mcp/tests/test_stdio.py` | Verify expected tool presence if `load_session` deprecation affects surface expectations |
| CLI / transport tests | `packages/agent-handoff-mcp/tests/test_http.py` | Verify expected tool presence if `load_session` deprecation affects surface expectations |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Must keep working against the default `get_handoff_state` shape |
| `packages/agent-handoff-mcp/tests/test_artifact_tools.py` | `doctor` registry counts may need updates if tool counts change |
| `packages/agent-handoff-mcp/tests/test_adapters.py` | Adapter-level expectations may need updates if descriptions or profiles change |
| `docs/agentic/instructions.md` | Selective handoff loading guidance should stay aligned with the live parameterized read surface |

## Verification Strategy

Use environment-variable-based commands only. Do not hardcode user-local absolute filesystem paths such as `/Users/...`; prefer `${PYENV_ROOT:-$HOME/.pyenv}` for interpreter paths.

- Deterministic tests:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py packages/agent-handoff-mcp/tests/test_review_findings.py packages/agent-handoff-mcp/tests/test_cli.py -q`
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_stdio.py packages/agent-handoff-mcp/tests/test_http.py -q`
- Runtime-parity / environment checks:
  - `agent-handoff-mcp --workspace-root "$(pwd)" doctor`
- Contract/fixture verification:
  - Verify default `get_handoff_state()` output remains backward-compatible for CURRENT_TASK and existing tests
  - Verify summary/projection modes omit or truncate heavy fields as specified
- Manual verification:
  - Inspect the MCP tool schema in a client and confirm the new parameters reduce the need for one-off read tools

## Slice Delivery

### Slice 1: Parameterize Task-State Reads

**Goal**: Let `get_handoff_state` return only the task-state sections and detail level the caller needs.

Changes:

- Add projection-oriented parameters such as `sections`, `detail`, or equivalent to `get_handoff_state`
- Support hot-state reads without forcing broad default payload growth
- Keep the current default response shape stable for existing callers, including CURRENT_TASK generation
- Add regression tests for compact defaults, explicit section requests, and backward-compatible task/dashboard views

Proof:

- `test_get_handoff_state_compact_defaults_enforced` and new section/detail tests pass
- CURRENT_TASK-related tests continue to pass without changing default reads

### Slice 2: Parameterize Review-Finding Reads and Fold Compound Session Reads

**Goal**: Make `list_review_findings` and `load_session` support targeted reads without separate tool proliferation.

Changes:

- Add summary/projection controls to `list_review_findings`, such as summary-only modes, field selection, or grouped-count outputs
- Rework `load_session` to reuse the new parameterized read behavior instead of duplicating broad nested payload logic
- Decide whether `load_session` remains as a compatibility wrapper or enters explicit deprecation
- Add regression tests for projected finding outputs, grouped counts, and `load_session` compatibility behavior

Proof:

- Existing review-finding scope and pagination tests still pass
- New tests prove narrow finding reads omit unnecessary full bodies while preserving default behavior
- `test_load_session_merges_state_and_findings` either continues to pass unchanged or is replaced with a compatibility/deprecation test agreed by the contract update

### Slice 3: Align Tool Registry, CLI, and Contract Surface

**Goal**: Keep MCP schema, CLI flags, tests, and docs synchronized with the new parameterized read model.

Changes:

- Update `TOOL_DESCRIPTIONS`, `ToolEntry`, and `ArgSpec` registrations in `api.py` for new read parameters
- Update CLI smoke tests and transport/tool-list tests if the tool surface or deprecation markers change
- Update `docs/agentic/contracts/agent-handoff-mcp.md` to describe the new read-shaping parameters and the intended consolidation path
- If `load_session` remains, document it as a compatibility convenience rather than the preferred hot-state entrypoint

Proof:

- CLI, stdio, and HTTP transport tests pass
- Contract doc matches the live tool signatures and expected profile counts
- `doctor` still reports coherent registry counts

### Slice 4: Optimize Token-Efficient Read Shapes

**Goal**: Make the parameterized read surfaces materially cheaper for startup and targeted follow-up reads by supporting compact structured projections, not just smaller full-detail blobs.

Changes:

- Add a true hot-state identity read path for `get_handoff_state` so callers can request only always-included task identity data without silently expanding back to the full task payload
- Add field-level or metadata-level compact projection controls where they reduce parsing and prompt cost more than string truncation alone
- Keep compact responses structured by default; add human-oriented summary strings only for explicitly human-facing read paths if structured compact projections still prove too heavy
- Extend CLI and regression coverage so compact read modes are verified end-to-end, not just through direct Python calls

Proof:

- A targeted startup read can return task identity without broad task-state sections
- Compact read modes measurably omit unused metadata and heavy text fields while preserving backward-compatible defaults
- CLI, stdio, and HTTP coverage prove the compact read shapes remain available across all supported entrypoints

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [x] Confirmed that external dependency context only requires `ctx7` if FastMCP parameter encoding behavior becomes ambiguous.
- [x] Recorded boundary ownership and compatibility expectations for MCP, CLI, and contract surfaces.

### Checklist: Slice 1

- [x] `get_handoff_state` gains section/detail shaping without breaking default callers.
- [x] CURRENT_TASK and other default consumers remain backward-compatible.
- [x] Regression tests cover compact defaults, explicit sections, and dashboard compatibility.

### Checklist: Slice 2

- [x] `list_review_findings` gains summary/projection behavior.
- [x] `load_session` is reworked into a compatibility wrapper or explicitly deprecated.
- [x] Regression tests cover projected finding output and compound-read compatibility.

### Checklist: Slice 3

- [x] `api.py` tool descriptions and CLI args match the live read parameters.
- [x] Contract docs describe the new parameterized read model and any deprecation path.
- [x] CLI and transport tests confirm the intended tool surface and counts.

### Checklist: Slice 4

- [x] `get_handoff_state` supports a true identity-only hot-state read without falling back to the full payload.
- [x] Compact read modes can omit unused metadata or fields, not just truncate long strings.
- [x] Human-oriented summary strings are added only where structured compact projections are still too heavy.
- [x] CLI, stdio, and HTTP coverage prove the compact read modes end-to-end.

## Review Readiness

- [x] No read-surface behavior change is left undocumented in the contract.
- [x] Backward-compatible defaults are covered by regression tests.
- [x] Handoff decision records the change, verification, and any deprecation or compatibility implications.

## Stretch Goals

- [x] Extend the same projection/detail pattern to artifact or search read surfaces only if the handoff read-surface work proves the pattern ergonomic.

## Success Criteria

- [x] A client can request hot-state identity, dashboard views, and targeted findings without paying for broad default payloads through an explicit documented identity-only request path.
- [x] A client can request compact structured projections that avoid unnecessary metadata and large text fields on startup and targeted follow-up reads.
- [x] The handoff read surface uses the same or fewer tools for these workflows than today, without collapsing explicit write semantics.
- [x] MCP, CLI, tests, and contract docs all agree on the new parameterized behavior, including compact read modes and identity-only semantics.
