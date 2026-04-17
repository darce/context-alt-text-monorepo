# AHMCP-6. Tool Surface Consolidation and CURRENT_TASK Authoring

> **Metadata**
>
> - **Date**: 2026-04-04 10:00 EST
> - **Author**: Claude Opus 4.6
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-6`
> - **Target Branch**: `feature/ahmcp-6-tool-consolidation`
> - **Review Coverage Target**: 2
> - **Expected Review Path**: ordinary branch review plus specialized module review for the handoff/orchestrator boundary

---

## Objective

Implement ADR-005's typed tool surface consolidation to reduce the extended profile from 28 tools to 15-18, complete the remaining CURRENT_TASK authoring follow-through that still belongs to this phase, and continue from the restored `packages/agent-handoff-mcp` source baseline without rewinding the standalone-consumer cutover completed by AHMCP-5.

## Problem Statement

ADR-005 was approved by AHMCP-4, selecting a hybrid domain-tool consolidation model with discriminated typed operation models. No implementation has followed. The 28-tool surface carries real discovery and prompt-cost overhead for agent clients; every session loads tool descriptions for tools that share obvious schema skeletons (e.g., four review-finding tools, three review-run tools, four artifact tools). CURRENT_TASK render-bounds improvements from AHMCP-2 are already reflected in the live contract, but the remaining authoring follow-through is still split across the older task-plan sequence and the current implementation surface. This task should continue from the live baseline instead of re-planning already-landed render changes.

The package source was extracted to `darce/mcp-agent-handoff` during AHMCP-5 and has since been restored to `packages/agent-handoff-mcp` for continued in-repo development. This task must build on that restored source baseline while preserving the git+ssh and installed-package consumer boundary that AHMCP-5 established.

## Constraints

- `core.py` must remain pure handoff-state CRUD per `[rg-013]`.
- No global cross-domain `record/update/list` tool may be introduced (ADR-005 guardrail).
- Every consolidated domain tool must expose typed operation models, not an opaque `payload: dict` (ADR-005 guardrail).
- Lifecycle and generator tools stay explicit: `close_slice`, `generate_current_task_md`, `handoff_close_check`, `export_handoff_state`, `import_handoff_state`, `archive_task_state`, `audit_decision_ids`, `search_handoff` (ADR-005 rule 1).
- All downstream enumerators (`api.py`, `cli.py`, `test_cli.py`, `test_stdio.py`, `test_http.py`, `test_adapters.py`, contract doc, README, `instructions.md`, `CLAUDE.md`) must be updated in the same slice as each tool rename (ADR-005 guardrail).
- The final extended profile count must land in the 15-18 range; deviations must be justified (ADR-005).
- FastMCP discriminated-union ergonomics must be validated before broad consolidation (ADR-005 rule 10).
- Greenfield default applies, but ADR-005 explicitly requires short-lived compatibility aliases for `update_task_status` and `load_session`; this task must preserve those migration semantics rather than removing both names immediately.

## Workflow Principles

- Validate FastMCP schema ergonomics before committing to the full consolidation; if a domain produces unreadable schemas, that domain stays split.
- Each domain consolidation lands as a self-contained slice with consistent surface state: old tools removed, new tool added, tests passing, contract updated.
- Remaining CURRENT_TASK authoring work is limited to contract-following mutation-output improvements; already-landed render-bounds behavior should be treated as baseline, not reopened scope.
- Restored-source cleanup is a mechanical prerequisite, not a reason to revert AHMCP-5's consumer dependency boundary.

## Terminology

- **Domain tool**: A single MCP tool that handles multiple operations within one entity family via a discriminated `operation` parameter (e.g., `review_findings` with `record`, `batch_record`, `update`, `list` operations).
- **Discriminated union**: A typed model where the `operation` field selects which typed payload model applies. Each variant retains its own field-level schema.
- **Downstream enumerator**: Any doc, test, adapter, or runtime surface that assumes a concrete tool name list.
- **Compatibility alias**: A temporary legacy tool name retained during migration while the canonical behavior moves behind a consolidated surface.

## Current State Analysis

- ADR-005 exists and is reviewed; it selects the hybrid domain-tool consolidation model.
- AHMCP-1 (parameterized read surfaces) is implemented: `sections`, `detail`, and `fields` parameters exist on read tools.
- AHMCP-2's render-bounds work is already reflected in the live contract: `generate_current_task_md` accepts `max_cross_task_findings`, and the default render no longer includes the old all-history findings section. The remaining CURRENT_TASK-related follow-through for this phase is mutation-output work such as OC-003-style `close_slice` response enrichment, not a second pass at bounded rendering.
- AHMCP-3 (OC-004 response envelope, OC-006 version bump) is planned but not implemented. Out of scope for this task; the tool surface consolidation does not depend on the response envelope.
- AHMCP-5 extracted the source to `darce/mcp-agent-handoff`; the monorepo consumer boundary was moved to git+ssh and installed-package usage. The editable source tree has now been restored under `packages/agent-handoff-mcp/` for continued in-repo development.
- The contract doc at `docs/agentic/contracts/agent-handoff-mcp.md` documents all 28 tools with surface classes and idempotency markers.
- Transport tests (`test_stdio.py`, `test_adapters.py`) still assert exact profile counts: 16 core, 28 extended.
- The restored-source baseline still has post-AHMCP-5 cleanup debt: `test_adapters.py` expects the old repo-local launcher while `.vscode/mcp.json` and `.codex/config.toml` now point at installed `agent-handoff-mcp` entrypoints.

## Target Outcome

After this task:

- The extended profile exposes 15-18 tools instead of 28.
- Five domain-scoped tools replace 17 individual tools: `record_event` (3→1), `review_findings` (4→1), `review_runs` (3→1), `next_actions` (2→1), `artifacts` (4→1).
- `update_task_status` is implemented as a compatibility alias over `set_handoff_state` during migration; `load_session` remains as a short-lived compatibility alias until clients fully move to parameterized reads.
- CURRENT_TASK.json bounded rendering remains the baseline behavior documented by the live contract.
- The remaining CURRENT_TASK authoring work in this task is limited to mutation-output improvements such as `close_slice` response enrichment; explicit `generate_current_task_md` remains the documented regeneration mechanism unless a later ADR changes that contract.
- `close_slice` returns the recorded decision row and updated task revision, eliminating follow-up reads.
- All downstream enumerators reflect the consolidated surface.
- Package source is in `packages/agent-handoff-mcp` for development while downstream consumers keep the AHMCP-5 standalone-package boundary intact.

## Context Loading

- ADR: `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`
- Contract: `docs/agentic/contracts/agent-handoff-mcp.md`
- Prior task plans:
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md`
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md`
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-4-typed-tool-surface-consolidation-adr-task-plan.md`
- Live tool-surface anchors (after source restoration):
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`
- Tests:
  - `packages/agent-handoff-mcp/tests/test_stdio.py`
  - `packages/agent-handoff-mcp/tests/test_http.py`
  - `packages/agent-handoff-mcp/tests/test_cli.py`
  - `packages/agent-handoff-mcp/tests/test_adapters.py`
- External docs via `ctx7` only if: FastMCP discriminated-union behavior needs upstream verification.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP tool surface | agent-handoff-mcp | `docs/agentic/contracts/agent-handoff-mcp.md` | 28 tools → 15-18; domain tools replace individual tools | Yes; `update_task_status` and `load_session` remain temporary aliases during migration | Transport tests + contract doc update + alias verification |
| Orchestrator MCP | agent-orchestrator-mcp | `docs/agentic/contracts/agent-orchestrator-mcp.md` | Handoff tool imports, re-exports, and any bridge-facing name assumptions must move in lockstep with consolidation | Yes; synchronized cross-service rename/update work | Orchestrator tests/docs updated in the same slice as each affected tool rename |
| IDE client configs | operator | `.vscode/mcp.json`, `CLAUDE.md` | Tool names in usage guidance change | No; tool names update, semantics preserved | Manual validation |
| Agent instructions | agentic-tooling | `docs/agentic/instructions.md` | Handoff tool references updated | No | Grep verification |

## Proposed Solution

Start from the already-restored in-repo source baseline, first clean up the remaining post-AHMCP-5 adapter/config drift, then validate FastMCP typed-dispatch support and progressively consolidate each domain behind a typed domain tool. Each consolidation slice removes old tools and adds the new domain tool atomically, updating all downstream enumerators, including orchestrator-owned re-export surfaces, while preserving the explicit compatibility aliases required by ADR-005. Separately, limit CURRENT_TASK follow-through to the remaining mutation-output work that is not already part of the live bounded-render baseline.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Package source baseline | `packages/agent-handoff-mcp/src/` | Treat restored source as baseline; do not reopen extraction/cutover work beyond cleanup needed to make the restored tree test-clean |
| Tool registry | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Replace 17 individual tool entries with 5 domain tools; keep `update_task_status` and `load_session` as documented compatibility aliases |
| CLI dispatch | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Update command dispatch for new tool names and operation routing |
| Core exports | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Verification-only unless an extraction is required; preserve `rg-013` purity and keep new consolidation logic out of `core.py` |
| CURRENT_TASK rendering | `packages/agent-handoff-mcp/src/agent_handoff_mcp/current_task_rendering.py` | Verify existing bounded-render behavior remains correct; only change remaining authoring outputs that are still in scope |
| Transport tests | `packages/agent-handoff-mcp/tests/test_stdio.py` | Update profile counts and tool name assertions |
| Adapter tests | `packages/agent-handoff-mcp/tests/test_adapters.py` | Update profile counts and tool name assertions |
| HTTP tests | `packages/agent-handoff-mcp/tests/test_http.py` | Update tool enumeration |
| CLI tests | `packages/agent-handoff-mcp/tests/test_cli.py` | Update command-surface assertions |
| Orchestrator API surface | `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Update imported/re-exported handoff tool names and any coordinating helpers that assume the pre-consolidation surface |
| Orchestrator tests/docs | `packages/agent-orchestrator-mcp/tests/`, `docs/agentic/contracts/agent-orchestrator-mcp.md` | Update cross-service expectations when handoff tool names or compatibility aliases change |
| Contract doc | `docs/agentic/contracts/agent-handoff-mcp.md` | Rewrite tool surface table for consolidated tools |
| README | `packages/agent-handoff-mcp/README.md` | Update tool-surface guide |
| Instructions | `docs/agentic/instructions.md` | Update handoff tool references |
| CLAUDE.md | `CLAUDE.md` | Update handoff usage guidance |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-orchestrator-mcp/pyproject.toml` | Keep the existing `darce/mcp-agent-handoff` git+ssh dependency; do not revert AHMCP-5 cutover to a local path |
| `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/api.py` | Imports and re-exports handoff tools by name; rename and compatibility work must update this surface in lockstep, not as verification-only fallout |
| `packages/agent-orchestrator-mcp/tests/` | Cross-service tests must prove orchestrator consumers still work after each consolidated rename or alias introduction |
| `.vscode/mcp.json`, `.codex/config.toml` | Restored-source baseline still needs adapter/config cleanup to align tests with the installed-entrypoint model before consolidation slices start |
| `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md` | Update status from "Proposed" to "Implemented" after completion |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md` | OC-001/OC-002 are baseline context; only the still-open CURRENT_TASK mutation-output follow-through should be absorbed here |

## Verification Strategy

- Deterministic tests:
  - `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/ -q`
  - `cd packages/agent-orchestrator-mcp && pyenv exec python -m pytest tests/ -q`
- Runtime-parity / environment checks:
  - `agent-handoff-mcp --workspace-root "$(pwd)" doctor`
  - Manual: invoke each domain tool via MCP client; verify typed schema renders correctly in VS Code Copilot tool list
- Contract/fixture verification:
  - Grep all downstream enumerators for removed tool names; zero hits expected
  - Grep orchestrator surfaces for renamed handoff tools after each slice; zero stale imports/re-exports expected
  - Profile count assertions in `test_stdio.py` and `test_adapters.py` match target range
- Manual verification:
  - Call `record_event` with each event kind (decision, test_result, blocker); verify correct dispatch
  - Call `review_findings` with each operation (record, batch_record, update, list); verify semantics preserved
  - Call `update_task_status` and `load_session`; verify the compatibility aliases still resolve to the intended migration path during consolidation

## Slice Delivery

### Slice 1: Restored-Source Baseline Cleanup

**Goal**: Treat the restored `packages/agent-handoff-mcp` tree as baseline and clean up the remaining post-AHMCP-5 adapter/config/test drift before tool consolidation starts.

Changes:

- Align restored-source tests and local adapter/config expectations with the installed-entrypoint model already established by AHMCP-5
- Verify `packages/agent-orchestrator-mcp/pyproject.toml` and related runtime/docs surfaces continue to use the AHMCP-5 git+ssh and installed-package boundary
- Verify the restored-source baseline is test-clean before any consolidation rename lands

Proof:

- `cd packages/agent-handoff-mcp && pyenv exec python -m pytest tests/test_stdio.py tests/test_adapters.py tests/test_cli.py tests/test_http.py -q` passes
- `cd packages/agent-orchestrator-mcp && pyenv exec python -m pytest tests/ -q` passes

### Slice 2: FastMCP Discriminated-Union Validation

**Goal**: Prove that FastMCP exposes discriminated-union typed operation models with usable parameter schemas in target clients before committing to broad consolidation.

Changes:

- Create a minimal proof-of-concept domain tool (e.g., `next_actions` with `list` and `update` operations) using FastMCP's typed parameter models
- Launch via stdio transport and inspect the generated JSON schema
- Verify the schema renders legibly in VS Code Copilot's tool parameter UI
- Document any ergonomic constraints that require design adjustments

Proof:

- JSON schema output shows per-operation typed fields, not a flat optional-field grab bag
- Schema renders with clear parameter descriptions in at least one MCP client
- Current transport constraint: the direct FastMCP spike preserves explicit discriminator metadata, but the live stdio transport currently exposes `record_event` as `oneOf` branches keyed by `event_kind` `const` values without a top-level `discriminator` object. Keep consolidated domains small enough that this still renders legibly.

### Slice 3: Event Domain Consolidation

**Goal**: Replace `record_decision`, `record_test_result`, and `report_blocker` with a single `record_event` tool using a discriminated `event_kind` parameter.

Changes:

- Add `record_event` tool to `api.py` with typed variants for `decision`, `test_result`, and `blocker`
- Remove the three individual tool registrations
- Update `cli.py` dispatch, orchestrator re-exports/tests where those names are imported, all transport tests, and contract docs
- Each event kind retains its own typed payload model (no opaque dict)

Proof:

- `test_stdio.py` and `test_adapters.py` pass with updated tool counts (-2 net)
- `test_cli.py` passes with updated command surface
- Contract doc reflects `record_event` with operation variants

### Slice 4: Review Domain Consolidation

**Goal**: Replace four review-finding tools and three review-run tools with `review_findings` and `review_runs` domain tools.

Changes:

- Add `review_findings` tool with `record`, `batch_record`, `update`, `list` operations
- Add `review_runs` tool with `record`, `list`, `coverage` operations
- Remove seven individual tool registrations
- Batch semantics (atomic transaction, single CURRENT_TASK.json flush) preserved in `batch_record` operation
- Update `cli.py`, all transport tests, orchestrator re-exports/tests, and contract docs

Proof:

- Transport tests pass with updated counts (-5 net from this slice)
- Batch operation still writes atomically and returns per-item results
- `close_slice` (which calls review_finding internals) still works correctly

### Slice 5: Remaining Domain Consolidation and Lifecycle Streamlining

**Goal**: Consolidate next-actions and artifact domains while preserving ADR-005's required migration aliases for `update_task_status` and `load_session`.

Changes:

- Add `next_actions` tool with `list`, `add`, `update`, `complete`, `skip` operations
- Add `artifacts` tool with `record`, `search`, `get`, `purge` operations
- Fold `update_task_status` semantics into `set_handoff_state` while keeping `update_task_status` as a compatibility alias during migration
- Keep `load_session` as a short-lived compatibility alias while clients move to parameterized `get_handoff_state` and related reads
- Remove only the individual tool registrations that ADR-005 authorizes replacing in this phase
- Update `cli.py`, all transport tests, orchestrator re-exports/tests, and contract docs

Proof:

- Transport tests pass with final consolidated tool counts in 15-18 range, including the compatibility aliases that remain temporarily documented
- `set_handoff_state` accepts status-only updates that previously went through `update_task_status`, and the alias still resolves correctly during migration
- Artifact FTS operations work through the domain tool

### Slice 6: CURRENT_TASK.json Authoring Streamlining

**Goal**: Finish the remaining CURRENT_TASK-related authoring improvements without reopening already-landed bounded-render behavior or introducing a new write-surface contract.

Changes:

- Treat OC-001 and OC-002 as already-landed baseline behavior and verify the implementation plus contract stay aligned
- OC-003: Enrich `close_slice` return value to include the recorded decision row and updated task revision
- Do not add automatic regeneration or a new `auto_render=false` parameter in this task
- Update the contract doc only for the response/output changes that are actually introduced here

Proof:

- `close_slice` response includes decision row and revision
- The live contract and implementation still agree on bounded rendering after the slice lands

### Slice 7: Downstream Enumerator Sweep and Final Validation

**Goal**: Ensure every downstream surface reflects the consolidated tool set and no stale tool names remain.

Changes:

- Update `packages/agent-handoff-mcp/README.md` with consolidated tool surface guide
- Update `docs/agentic/instructions.md` handoff tool references
- Update `CLAUDE.md` handoff usage guidance
- Update ADR-005 status from "Proposed" to "Implemented"
- Run comprehensive grep for removed tool names across all docs and configs
- Final profile count verification in transport tests

Proof:

- `grep` over live runtime/config/contract surfaces updated by this task returns zero stale pre-consolidation tool-name hits outside the documented compatibility aliases and historical references
- All tests pass: `pyenv exec python -m pytest packages/agent-handoff-mcp/tests/ packages/agent-orchestrator-mcp/tests/ -q`
- `agent-handoff-mcp --workspace-root "$(pwd)" doctor` passes

---

## Consolidated Checklist

### Context and Ownership

- [x] Loaded ADR-005 and contract doc before editing.
- [x] Confirmed FastMCP discriminated-union support via spike before broad consolidation.
- [x] Recorded boundary ownership and tool name changes in contract doc per slice.

### Checklist for Slice 1: Restored-Source Baseline Cleanup

- [x] Restored-source adapter/config/test drift resolved for the in-repo development baseline
- [x] Orchestrator dependency boundary remains on the AHMCP-5 git+ssh and installed-package path
- [x] Existing test suite passes

### Checklist for Slice 2: FastMCP Discriminated-Union Validation

- [x] Proof-of-concept domain tool created
- [x] JSON schema inspected via stdio transport
- [ ] Client rendering validated
- [x] Ergonomic constraints documented

### Checklist for Slice 3: Event Domain Consolidation

- [x] `record_event` tool implemented with decision, test_result, blocker variants
- [x] Three individual tools removed from registry
- [x] CLI, transport tests, contract doc updated
- [x] Verification evidence captured

### Checklist for Slice 4: Review Domain Consolidation

- [x] `review_findings` tool implemented with record, batch_record, update, list operations
- [x] `review_runs` tool implemented with record, list, coverage operations
- [x] Seven individual tools removed from registry
- [x] Batch semantics preserved (atomic write, per-item results)
- [x] CLI, transport tests, contract doc updated

### Checklist for Slice 5: Remaining Domain Consolidation and Lifecycle

- [x] `next_actions` tool implemented with list, add, update, complete, skip operations
- [x] `artifacts` tool implemented with record, search, get, purge operations
- [x] `update_task_status` kept as a compatibility alias over `set_handoff_state`
- [x] `load_session` kept as a short-lived compatibility alias
- [x] Final tool count in 15-18 range
- [x] CLI, transport tests, contract doc updated

### Checklist for Slice 6: CURRENT_TASK.json Authoring Streamlining

- [x] Existing bounded-render behavior verified against the live contract
- [x] `close_slice` returns decision row and revision
- [x] Contract doc updated

### Checklist for Slice 7: Downstream Enumerator Sweep

- [x] README updated
- [x] `instructions.md` updated
- [x] `CLAUDE.md` updated
- [x] ADR-005 status updated to "Implemented"
- [x] Grep sweep shows zero stale tool names in live docs
- [x] All tests pass end to end

## Review Readiness

- [x] No tool rename is left without matching contract/doc/test evidence.
- [ ] FastMCP schema ergonomics validated before broad consolidation.
- [x] Bounded render and `close_slice` output behavior tested without adding a new opt-out path.
- [ ] Handoff decision records each slice with verification and contract implications.

## Stretch Goals

- [x] Profile split removal (core vs. extended); legacy `--tool-profile core|extended` inputs now normalize to the same 17-tool surface
- [x] Response envelope (OC-004) confirmed live for public MCP tools via the v2 envelope contract and tests

## Success Criteria

- [x] Consolidated live surface exposes 15-18 tools (17 current, down from 28)
- [x] Five domain tools (`record_event`, `review_findings`, `review_runs`, `next_actions`, `artifacts`) replace 17 individual tools
- [x] CURRENT_TASK.json output is bounded (no all-status history; capped cross-task findings)
- [ ] State-mutating tools auto-regenerate CURRENT_TASK.json
- [x] `close_slice` returns enriched response (decision row + revision)
- [x] All transport, CLI, and adapter tests pass with consolidated surface
- [x] All downstream enumerators reflect the new tool names
