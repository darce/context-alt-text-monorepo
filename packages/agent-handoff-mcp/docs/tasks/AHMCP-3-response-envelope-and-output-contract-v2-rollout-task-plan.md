# AHMCP-3. Response Envelope and Output Contract v2 Rollout

> **Metadata**
>
> - **Date**: 2026-04-02
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-3`
> - **Target Branch**: `task/ahmcp-3-response-envelope`
> - **Review Coverage Target**: 2

---

## Objective

Implement the Tier 2 output-contract v2 rollout by adding a common response envelope across the handoff tool surface and shipping the package version bump to `0.2.0` with the envelope landing.

## Problem Statement

`agent-handoff-mcp` responses currently share only `ok`; every tool otherwise returns its own ad hoc shape. That forces callers to know tool-specific payload rules, makes mutation/artifact metadata inconsistent, and blocks cheap machine parsing. The approved spec makes OC-004 the contract break that introduces `schema_version: 2` and a common envelope, with OC-006 tying the package version bump to that rollout.

This work should land only after Tier 1 changes are complete, so the envelope wraps the smaller, corrected payload shapes instead of baking in avoidable render and mutation inconsistencies.

## Constraints

- Tier 1 output changes should land before this task starts; do not re-open Tier 1 behavior here except for necessary envelope wrapping.
- This task implements OC-004 and OC-006 only. Tool consolidation and polymorphic dispatch remain out of scope until ADR-005 is approved.
- `schema_version` in responses is independent from the SQLite schema version and should not change `HANDOFF_SCHEMA_VERSION`.
- Breaking response-shape changes are acceptable, but they must be complete: MCP surface, CLI/transport tests, contract docs, and package versioning move together.
- The envelope must remain machine-first. Do not replace structured `data` with freeform summary text.

## Workflow Principles

- Add one shared envelope helper and migrate call sites systematically rather than hand-coding shape changes per function.
- Roll out read/generator surfaces first, then mutation-heavy surfaces, so failures are easier to isolate.
- Keep mutation metadata explicit and structured; do not bury affected IDs or task revisions inside freeform messages.
- Treat docs and versioning as part of the same contract slice, not cleanup after the code lands.

## Terminology

- **Envelope**: The new top-level response shape containing `ok`, `schema_version`, `tool`, `scope`, `data`, `mutation`, `artifacts`, and `warnings`.
- **Mutation metadata**: Structured write-result context such as operation type, affected IDs, and the current task revision.
- **Artifact metadata**: Structured records describing generated artifacts such as `CURRENT_TASK.json` writes.
- **Transport parity**: The same envelope shape is visible through direct Python calls, CLI wiring, stdio MCP, and HTTP MCP.

## Current State Analysis

- The approved output-contract v2 spec is the canonical current-state source for OC-004 and OC-006; this task plan intentionally avoids duplicating the spec's code-verified before/after detail.
- The task-specific risk here is rollout consistency: every response-producing surface, transport-visible test, and published contract/doc example must move together when the envelope lands.
- Existing transport and regression suites already cover direct Python, CLI, stdio, and HTTP entrypoints, so the main implementation risk is inconsistent migration rather than missing harnesses.
- The approved spec explicitly ties the package version bump to the envelope landing, not to later tool-surface consolidation.

## Target Outcome

After this task:

- every handoff tool response is wrapped in the v2 envelope
- `schema_version` is `2` everywhere
- mutation responses include structured `mutation` metadata
- artifact-producing tools report structured `artifacts`
- `pyproject.toml` version is `0.2.0`
- contract docs and transport tests describe and prove the envelope contract

## Context Loading

- Spec: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md`
- Tier 1 prerequisite task: `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md`
- Contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Response-shaping anchors:
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
  - `packages/agent-handoff-mcp/pyproject.toml`
- Test anchors:
  - `packages/agent-handoff-mcp/tests/test_handoff_state.py`
  - `packages/agent-handoff-mcp/tests/test_review_findings.py`
  - `packages/agent-handoff-mcp/tests/test_import_export_regressions.py`
  - `packages/agent-handoff-mcp/tests/test_cli.py`
  - `packages/agent-handoff-mcp/tests/test_stdio.py`
  - `packages/agent-handoff-mcp/tests/test_http.py`
  - `packages/agent-handoff-mcp/tests/test_adapters.py`

## Contract and Boundary Impact

| Boundary                      | Owner        | Current Contract                      | Expected Change                                          | Compatibility Needed?         | Verification                   |
| ----------------------------- | ------------ | ------------------------------------- | -------------------------------------------------------- | ----------------------------- | ------------------------------ |
| Tool response top-level shape | handoff core | ad hoc top-level payloads per tool    | all responses wrapped in v2 envelope                     | No; greenfield contract break | direct-call + transport tests  |
| Mutation write confirmation   | handoff core | tool-specific top-level fields        | `mutation` object standardized across writes             | No                            | write-surface regression tests |
| Artifact reporting            | handoff core | mixed booleans and ad hoc path fields | `artifacts` array standardized where outputs are written | No                            | generator/import-export tests  |
| Published package contract    | handoff core | pre-envelope response examples        | versioned v2 envelope examples and guarantees            | No                            | contract doc + version bump    |

## Proposed Solution

Add a new `_envelope()` helper in `shared_primitives.py` alongside the existing `_json_response()`. Each tool call site opts into the envelope by calling `_envelope()` instead of `_json_response()`, wrapping its current payload as `data`. This per-surface migration allows incremental verification: read surfaces first, then writes, then contract sync. `_json_response()` remains untouched until all call sites are migrated, at which point it can be removed or kept as an internal helper. Finish by updating the published contract and bumping the package version to `0.2.0` in the same slice that completes the rollout.

## Files and Surfaces to Change

| Surface                      | File                                                                    | Change                                                                                         |
| ---------------------------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Shared response helper       | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py` | add `_envelope()` helper alongside `_json_response()`; update `_shared.py` re-export if needed |
| Task-state reads             | `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py`     | wrap task-state payloads in the v2 envelope                                                    |
| Findings and review surfaces | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`   | wrap list/record/update/review-run responses and populate mutation metadata                    |
| Lifecycle and generators     | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`              | wrap generator/write responses and emit artifact metadata                                      |
| Import/export and archive    | `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py`     | wrap export/import/archive responses in the v2 envelope                                        |
| MCP registry surface         | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`               | keep live tool descriptions and public docs aligned with the v2 contract                       |
| Package metadata             | `packages/agent-handoff-mcp/pyproject.toml`                             | bump package version to `0.2.0`                                                                |
| Contract docs                | `docs/agentic/contracts/agent-handoff-mcp.md`                           | document v2 envelope fields and example payloads                                               |
| Package docs                 | `packages/agent-handoff-mcp/README.md`                                  | update CLI/output examples if they rely on pre-envelope shapes                                 |
| Regression coverage          | `packages/agent-handoff-mcp/tests/test_*.py`                            | assert envelope presence and transport parity                                                  |

## Related Files

| File                                                                                 | Note                                                                                  |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_schema.py`                  | SQLite schema version is unrelated; do not conflate it with response `schema_version` |
| `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` | authoritative source for the v2 envelope fields and versioning rules                  |

## Verification Strategy

Use environment-variable-based commands only. Do not hardcode user-local absolute filesystem paths such as `/Users/...`; prefer `${PYENV_ROOT:-$HOME/.pyenv}` for interpreter paths.

- Lane `envelope-read`:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "get_handoff_state or generate_current_task_md"`
- Lane `envelope-write`:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_review_findings.py -q -k "record_review_run or list_review_runs or get_review_coverage"`
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_import_export_regressions.py -q`
- Lane `surface-sync`:
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_cli.py -q`
  - `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_stdio.py::test_stdio_server_lists_handoff_tools packages/agent-handoff-mcp/tests/test_stdio.py::test_stdio_extended_profile_exposes_all_27_tools packages/agent-handoff-mcp/tests/test_http.py::test_http_server_lists_handoff_tools packages/agent-handoff-mcp/tests/test_adapters.py::test_default_adapter_profile_is_extended_and_core_has_16_tools -q`
- Runtime-parity check:
  - `agent-handoff-mcp --workspace-root "$(pwd)" doctor`

## Slice Delivery

### Slice 1: Add the Envelope Helper and Migrate Read Surfaces

**Goal**: Establish the per-surface `_envelope()` helper and prove it on read/generator surfaces first.

Changes:

- Add `_envelope()` in `shared_primitives.py` (not `_shared.py`) — call sites opt in individually
- Migrate `get_handoff_state`, `generate_current_task_md`, and other hot-state read/generator surfaces from `_json_response()` to `_envelope()`
- Populate `tool`, `scope`, and `warnings` consistently on migrated read surfaces
- Update direct-call regression tests for read/generator payloads
- Re-export `_envelope` from `_shared.py` if domain modules import through that layer

Proof:

- Read/generator regressions pass with `schema_version: 2`
- At least one hot-state tool and one render generator prove the final envelope shape

### Slice 2: Migrate Mutation, Review, and Import/Export Surfaces

**Goal**: Apply the v2 envelope consistently to all write-heavy tool families and carry structured mutation/artifact metadata.

Changes:

- Migrate `review_findings.py` write/list/review-run responses
- Migrate `core.py` write/generator responses such as `close_slice`
- Migrate `import_export.py` responses and populate `artifacts` where files are written
- Standardize `mutation` payload contents for writes that affect rows or task revision state

Proof:

- Write/import-export regressions pass with structured `mutation` and `artifacts`
- No remaining public tool response bypasses the envelope helper

### Slice 3: Sync Published Contract and Ship `0.2.0`

**Goal**: Make the envelope rollout externally legible and versioned.

Changes:

- Update `docs/agentic/contracts/agent-handoff-mcp.md` with v2 response examples and field guarantees
- Update `packages/agent-handoff-mcp/README.md` examples where output shape changed materially
- Bump `packages/agent-handoff-mcp/pyproject.toml` to `0.2.0`
- Align CLI, stdio, and HTTP transport tests with the final contract

Proof:

- CLI, stdio, and HTTP tests pass
- Published contract docs match the live v2 envelope fields
- Package version is `0.2.0`

## Lane-Ready Execution Brief

### Lanes

| Lane ID          | Owned Files                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Narrowest Proving Commands                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `envelope-read`  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_primitives.py` (envelope helper), `packages/agent-handoff-mcp/src/agent_handoff_mcp/_shared.py` (re-export), `packages/agent-handoff-mcp/src/agent_handoff_mcp/handoff_state.py`, `packages/agent-handoff-mcp/tests/test_handoff_state.py`                                                                                                                                                              | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py -q -k "get_handoff_state or generate_current_task_md"`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `envelope-write` | `packages/agent-handoff-mcp/src/agent_handoff_mcp/review_findings.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/import_export.py`, `packages/agent-handoff-mcp/tests/test_review_findings.py`, `packages/agent-handoff-mcp/tests/test_import_export_regressions.py`                                                                                                                         | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_review_findings.py -q -k "record_review_run or list_review_runs or get_review_coverage"`; `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_import_export_regressions.py -q`                                                                                                                                                                                                                                             |
| `surface-sync`   | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`, `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`, `packages/agent-handoff-mcp/pyproject.toml`, `packages/agent-handoff-mcp/README.md`, `docs/agentic/contracts/agent-handoff-mcp.md`, `packages/agent-handoff-mcp/tests/test_cli.py`, `packages/agent-handoff-mcp/tests/test_stdio.py`, `packages/agent-handoff-mcp/tests/test_http.py`, `packages/agent-handoff-mcp/tests/test_adapters.py` | `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_cli.py -q`; `PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}" PYENV_VERSION=description-service "$PYENV_ROOT/versions/description-service/bin/python" -m pytest packages/agent-handoff-mcp/tests/test_stdio.py::test_stdio_server_lists_handoff_tools packages/agent-handoff-mcp/tests/test_stdio.py::test_stdio_extended_profile_exposes_all_27_tools packages/agent-handoff-mcp/tests/test_http.py::test_http_server_lists_handoff_tools packages/agent-handoff-mcp/tests/test_adapters.py::test_default_adapter_profile_is_extended_and_core_has_16_tools -q` |

### Merge Order

1. `envelope-read` (creates the `_envelope()` helper that `envelope-write` depends on)
2. `envelope-write`
3. `surface-sync`

### Lane Notes

- `envelope-read` creates the shared `_envelope()` helper in `shared_primitives.py` — `envelope-write` depends on this, so they are sequential, not parallel.
- `surface-sync` is intentionally last because it owns the published contract, package version bump, and transport-visible assertions.
- Each lane now owns its proving test files alongside its source files.

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the approved output-contract v2 spec and confirmed Tier 1 is complete before wrapping responses.
- [x] Kept OC-005 tool consolidation out of scope for this task.
- [x] Kept response `schema_version` separate from SQLite schema versioning.

### Checklist: Slice 1

- [x] Shared envelope helper exists and is used by migrated read/generator surfaces.
- [x] Read responses expose `schema_version: 2`.
- [x] Read/generator regressions prove the new top-level contract.

### Checklist: Slice 2

- [x] Mutation-heavy surfaces emit structured `mutation` metadata.
- [x] Artifact-producing surfaces emit structured `artifacts` metadata.
- [x] No public tool response bypasses the envelope helper.

### Checklist: Slice 3

- [x] `docs/agentic/contracts/agent-handoff-mcp.md` documents the v2 envelope.
- [x] `packages/agent-handoff-mcp/README.md` is synchronized where output examples changed.
- [x] `packages/agent-handoff-mcp/pyproject.toml` is bumped to `0.2.0`.
- [x] CLI, stdio, and HTTP transport tests pass against the final envelope.

## Review Readiness

- [x] The response contract break is documented and versioned in the same slice as the code.
- [x] Transport parity is proven across direct, CLI, stdio, and HTTP entrypoints.
- [x] Handoff decisions explicitly reference OC-004 and OC-006 when slices complete.

## Success Criteria

- [x] Every handoff tool response is wrapped in the common v2 envelope.
- [x] `schema_version` is `2` across the live tool surface.
- [x] Mutation and artifact metadata are structured and consistent.
- [x] Package version `0.2.0` ships with the envelope rollout.
