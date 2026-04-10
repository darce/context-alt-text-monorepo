# E12-3. MCP Decision Enforcement and Context Router

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Enforce the new decision-id grammar in `agent-handoff-mcp` while preserving slice-complete compatibility end to end. When complete, malformed new decision ids should be rejected or surfaced clearly, the new grammar should be concretely specified, and slice-complete parsing should still work without an intermediate broken state. Any routing-audit helper is secondary and should not block the core enforcement slice.

## Problem Statement

The naming scheme only becomes reliable when the MCP layer validates and parses it consistently. Today `record_decision` accepts broader freeform values, and review/slice logic still keys off the old `slice_complete_*` assumption. If grammar enforcement ships before compatibility updates, close-check and slice-review would stop finding valid new slice-complete decisions.

## Constraints

- Existing historical decisions must remain readable and mostly grandfathered.
- Slice-complete detection used by close checks and slice-review packets must keep working through the transition.
- New enforcement should focus on new writes and additive audit surfaces rather than destructive migration.

## Workflow Principles

- Validation should reject malformed new writes early rather than relying on post-hoc review.
- Parsing helpers should keep the grammar centralized instead of scattering regexes across modules.
- Compatibility updates must land atomically with new-write enforcement.
- Routing should be inspectable and explainable when it proves necessary, but it should not outrank the core grammar-compatibility path.

## Terminology

- **Decision author tag**: The compact lowercase agent prefix such as `cdx` or `cop`.
- **Work reference**: The epic/task reference embedded in a decision id, such as `E12-1`.
- **Routing audit surface**: An MCP-visible helper that returns the expected guide/template for a request context.

## Decision Grammar Specification

- Canonical form: `<author_tag>_<decision_kind>_<work_ref>_<slug>`
- `author_tag`: lowercase compact agent tag, recommended `[a-z]{2,4}`
- `decision_kind`: lowercase underscore-delimited action label such as `slice_complete`, `review_complete`, or another explicitly supported write target
- `work_ref`: epic/task-style reference such as `E12-1` or another task ref allowed by repo policy
- `slug`: lowercase `[a-z0-9_]+`
- Canonical slice-complete example: `cdx_slice_complete_E12-1_gate_validation`
- Legacy `slice_complete_*` rows remain grandfathered for read paths; new writes must follow the canonical prefixed form once enforcement lands

## Current State Analysis

- [core.py](packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py) already validates structured `slice_complete_*` rationale content, but decision-id grammar enforcement is still evolving.
- [slice_review_packet.py](packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py) depends on slice-complete detection and must continue to work with prefixed author/work references.
- There is no MCP helper today that deterministically answers which review guide or planning template applies to a given request/target pair.
- The epic explicitly calls for doctor/audit output where hard-fail enforcement is not yet appropriate.

## Target Outcome

New decision writes should follow one compact grammar, with author and work reference embedded in the decision string. Slice-complete decisions remain discoverable for close-check and packet derivation in the same release that enforces the new grammar. A lightweight routing audit output can exist as a stretch goal or doctor-style helper, but it is not required for the core slice to be correct.

## Context Loading

- Rules: [instructions.md](docs/agentic/instructions.md), [development-workflow.md](docs/agentic/rules/development-workflow.md)
- Contracts: [agent-handoff-mcp.md](docs/agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: inspect open findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: not needed

## Contract and Boundary Impact

| Boundary               | Owner              | Current Contract                                    | Expected Change                                  | Compatibility Needed?                                      | Verification          |
| ---------------------- | ------------------ | --------------------------------------------------- | ------------------------------------------------ | ---------------------------------------------------------- | --------------------- |
| Decision write grammar | MCP                | `agent-handoff-mcp.md` + `record_decision` behavior | Enforce author/work-ref grammar for new writes   | Yes; grandfather historical decisions, enforce new writes  | pytest + contract doc |
| Slice-complete parsing | MCP/review tooling | close-check + slice packet semantics                | Preserve detection under the new prefixed format | Yes; existing review flows must still resolve latest slice | pytest                |
| Context routing        | MCP/docs           | doc-only routing today                              | Add additive helper or audit surface             | Yes; additive only                                         | pytest + contract doc |

## Proposed Solution

Ship grammar enforcement and slice-complete compatibility together as one atomic slice. Centralize decision-id parsing/validation in shared helpers, update write-time validation in `record_decision`, and teach close-check and slice-review helpers to recognize the prefixed slice-complete form in the same change. Treat the routing-audit helper as a lower-priority follow-up unless a concrete failure shows the doc-based router is insufficient.

## Files and Surfaces to Change

| Surface  | File                                                                                    | Change                                                                         |
| -------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                              | Validate new decision ids and preserve close-check semantics                   |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py` | Recognize the prefixed slice-complete format                                   |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                               | Expose any decision-grammar-facing additions; routing audit is optional        |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py`                             | Add shared enums only if routing or grammar ownership benefits                 |
| test     | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                                | Add write-validation and close-check coverage                                  |
| test     | `packages/agent-handoff-mcp/tests/test_review_runner.py`                                | Verification-only: preserve downstream review compatibility where applicable   |
| test     | `packages/agent-handoff-mcp/tests/test_review_ready.py`                                 | Verification-only: preserve readiness semantics under the new decision grammar |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                           | Document decision-id grammar and routing helper/audit output                   |
| docs     | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md`       | Mark Phase 3 task-plan linkage once scoped                                     |

## Related Files

| File                                          | Note                                                                      |
| --------------------------------------------- | ------------------------------------------------------------------------- |
| `docs/agentic/rules/branch-review-guide.md`   | Routing helper should align with branch-review selection rules            |
| `docs/agentic/rules/planning-review-guide.md` | Routing helper should align with planning-review/template selection rules |

## Verification Strategy

- Deterministic tests:
  - `PYTHONPATH="packages/agent-handoff-mcp/src:packages/codex-subagent-bridge/src" python3 -m pytest packages/agent-handoff-mcp/tests/test_handoff_state.py packages/agent-handoff-mcp/tests/test_review_runner.py packages/agent-handoff-mcp/tests/test_review_ready.py -q`
- Contract/fixture verification:
  - Verify the MCP contract doc names the enforced decision grammar and routing-helper output
- Manual verification:
  - Exercise one valid and one invalid decision id
  - Exercise one code-review context and one planning-doc context through the routing helper/audit surface

## Slice Delivery

### Slice 1: Decision Grammar Enforcement and Slice-Complete Compatibility

**Goal**: Make new decision-id writes follow one enforced grammar without breaking slice-complete detection in any intermediate state.

Changes:

- Add shared parsing/validation helpers for author tag, work reference, and prefixed slice-complete detection.
- Enforce the new grammar in `record_decision` for new writes while grandfathering historical rows.
- Update close-check and slice-review helpers in the same slice to recognize `<author_tag>_slice_complete_<work_ref>_<slug>`.

Proof:

- Tests show malformed new ids fail, valid new ids pass, and packet generation / close-review gates still resolve the latest completed slice.

### Slice 2: Optional Routing Audit Follow-Up

**Goal**: Add inspectable routing output only if a lightweight doctor-style surface is still justified after the grammar work lands.

Changes:

- If kept, add a lightweight doctor or audit output that maps request intent + target path to the required guide/template.
- Document the helper and its expected output in the MCP contract only if the surface is implemented.
- Sync the epic’s Phase 3 task-plan link once the task is created.

Proof:

- Any implemented MCP-visible output answers “which guide/template is required?” for representative review and planning-creation contexts.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the current guidance, contract, and relevant handoff findings before editing.
- [x] Confirmed grandfathering policy assumptions for historical decisions.

## Slice 1: Decision Grammar Enforcement and Slice-Complete Compatibility

- [x] Added centralized parsing/validation helpers. (`slice_decision.py` module with `is_slice_complete_decision`, `is_prefixed_slice_complete_decision`, `extract_slice_label`.)
- [x] Updated `record_decision` for new-write enforcement. (`_validate_decision_payload` rejects legacy and malformed ids.)
- [x] Updated slice-complete detection in the same slice. (`slice_review_packet.py` matches both legacy and prefixed formats.)
- [x] Preserved close-check/readiness/packet behavior with tests.
- [x] Added write-validation tests.

## Slice 2: Optional Routing Audit Follow-Up

- [ ] Added an MCP-visible routing helper or doctor-style audit output only if justified. (Deferred; doc-based routing in `development-workflow.md` is sufficient.)
- [ ] Documented the new surface in the contract only if implemented. (N/A; routing helper not implemented.)
- [x] Linked Phase 3 back to this task plan from the epic.

## Review Readiness

- [x] New decision grammar is enforced or clearly surfaced by MCP.
- [x] Slice-complete semantics still work under the new format.
- [x] Handoff decision records the enforcement changes and verification evidence.

## Stretch Goals

- [x] Add a lightweight doctor command that audits recent malformed new decision ids or missing routing evidence in one report. (`audit_decision_ids` MCP tool in `decisions.py`; classifies each decision as `canonical`, `legacy_slice`, `malformed_slice`, or `freeform`; `healthy=False` when any malformed slice ids exist.)

## Success Criteria

- [x] New decision writes carry author and work-reference provenance in a compact enforced grammar.
- [x] Slice-review packet and close/review readiness flows continue to work with the new slice-complete format.
- [x] If a routing audit surface is implemented, MCP can answer which guide/template is required for a request context without relying on prompt memory. (`audit_decision_ids` surfaces grammar violations per task with per-row detail.)
