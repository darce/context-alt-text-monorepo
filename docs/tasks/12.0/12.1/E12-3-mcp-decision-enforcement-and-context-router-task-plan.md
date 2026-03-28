# E12-3. MCP Decision Enforcement and Context Router

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Enforce the new decision-id grammar in `agent-handoff-mcp` and add an auditable context-routing surface for guide/template selection. When complete, malformed new decision ids should be rejected or surfaced clearly, slice-complete parsing should still work, and operators should be able to ask MCP which guide/template is required for a given request context.

## Problem Statement

The naming scheme only becomes reliable when the MCP layer validates and parses it consistently. Today `record_decision` accepts broader freeform values, and review/slice logic still keys off the old `slice_complete_*` assumption. The repo also lacks an MCP-visible answer to “which guide/template should have been loaded for this request?”

## Constraints

- Existing historical decisions must remain readable and mostly grandfathered.
- Slice-complete detection used by close checks and slice-review packets must keep working through the transition.
- New enforcement should focus on new writes and additive audit surfaces rather than destructive migration.

## Workflow Principles

- Validation should reject malformed new writes early rather than relying on post-hoc review.
- Parsing helpers should keep the grammar centralized instead of scattering regexes across modules.
- Routing should be inspectable and explainable, not hidden in prompt lore.

## Terminology

- **Decision author tag**: The compact lowercase agent prefix such as `cdx` or `cop`.
- **Work reference**: The epic/task reference embedded in a decision id, such as `E12-1`.
- **Routing audit surface**: An MCP-visible helper that returns the expected guide/template for a request context.

## Current State Analysis

- [core.py](packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py) already validates structured `slice_complete_*` rationale content, but decision-id grammar enforcement is still evolving.
- [slice_review_packet.py](packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py) depends on slice-complete detection and must continue to work with prefixed author/work references.
- There is no MCP helper today that deterministically answers which review guide or planning template applies to a given request/target pair.
- The epic explicitly calls for doctor/audit output where hard-fail enforcement is not yet appropriate.

## Target Outcome

New decision writes should follow one compact grammar, with author and work reference embedded in the decision string. Slice-complete decisions remain discoverable for close-check and packet derivation. MCP should also expose a lightweight routing helper or audit result that turns review/doc-creation routing into an inspectable system capability rather than a doc-only expectation.

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

Centralize decision-id parsing/validation in shared helpers, update write-time validation in `record_decision`, teach close-check and slice-review helpers to recognize the prefixed slice-complete form, and add one additive routing helper or audit tool that answers guide/template selection from request intent and target path.

## Files and Surfaces to Change

| Surface  | File                                                                                    | Change                                                                        |
| -------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py`                              | Validate new decision ids and preserve close-check semantics                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/slice_review_packet.py` | Recognize the prefixed slice-complete format                                  |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`                               | Expose routing helper/audit surface and any decision-grammar-facing additions |
| tooling  | `packages/agent-handoff-mcp/src/agent_handoff_mcp/enums.py`                             | Add shared enums only if routing or grammar ownership benefits                |
| test     | `packages/agent-handoff-mcp/tests/test_handoff_state.py`                                | Add write-validation and close-check coverage                                 |
| test     | `packages/agent-handoff-mcp/tests/test_review_runner.py`                                | Preserve downstream review compatibility where applicable                     |
| test     | `packages/agent-handoff-mcp/tests/test_review_ready.py`                                 | Preserve readiness semantics under the new decision grammar                   |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                           | Document decision-id grammar and routing helper/audit output                  |
| docs     | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md`       | Mark Phase 3 task-plan linkage once scoped                                    |

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

### Slice 1: Decision Grammar Helpers and Validation

**Goal**: Make new decision-id writes follow one enforced grammar.

Changes:

- Add shared parsing/validation helpers for author tag, work reference, and prefixed slice-complete detection.
- Enforce the new grammar in `record_decision` for new writes while grandfathering historical rows.

Proof:

- Tests show malformed new ids fail and valid new ids pass.

### Slice 2: Slice-Complete Compatibility

**Goal**: Preserve downstream slice-complete behavior under the new grammar.

Changes:

- Update close-check and slice-review helpers to recognize `<agent_tag>_slice_complete_<work_ref>_<slug>`.
- Add regression coverage for latest-slice resolution and readiness logic.

Proof:

- Tests show packet generation and close/review gates still resolve the latest completed slice.

### Slice 3: Context-Routing Audit Surface

**Goal**: Make guide/template routing inspectable through MCP.

Changes:

- Add a context-routing helper or audit surface that maps request intent + target path to the required guide/template.
- Document the helper and its expected output in the MCP contract.
- Sync the epic’s Phase 3 task-plan link once the task is created.

Proof:

- MCP-visible output answers “which guide/template is required?” for representative review and planning-creation contexts.

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the current guidance, contract, and relevant handoff findings before editing.
- [ ] Confirmed grandfathering policy assumptions for historical decisions.

## Slice 1: Decision Grammar Helpers and Validation

- [ ] Added centralized parsing/validation helpers.
- [ ] Updated `record_decision` for new-write enforcement.
- [ ] Added write-validation tests.

## Slice 2: Slice-Complete Compatibility

- [ ] Updated slice-complete detection.
- [ ] Preserved close-check/readiness/packet behavior with tests.

## Slice 3: Context-Routing Audit Surface

- [ ] Added an MCP-visible routing helper or audit output.
- [ ] Documented the new surface in the contract.
- [ ] Linked Phase 3 back to this task plan from the epic.

## Review Readiness

- [ ] New decision grammar is enforced or clearly surfaced by MCP.
- [ ] Slice-complete semantics still work under the new format.
- [ ] Handoff decision records the enforcement changes and verification evidence.

## Stretch Goals

- [ ] Add a lightweight doctor command that audits recent malformed new decision ids or missing routing evidence in one report.

## Success Criteria

- [ ] New decision writes carry author and work-reference provenance in a compact enforced grammar.
- [ ] Slice-review packet and close/review readiness flows continue to work with the new slice-complete format.
- [ ] MCP can answer which guide/template is required for a request context without relying on prompt memory.
