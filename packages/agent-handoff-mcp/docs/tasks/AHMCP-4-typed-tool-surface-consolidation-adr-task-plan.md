# AHMCP-4. Typed Tool Surface Consolidation ADR

> **Metadata**
>
> - **Date**: 2026-04-02
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-4`
> - **Target Branch**: `feature/ahmcp-4-tool-consolidation-adr`
> - **Review Coverage Target**: 2

**Status Note**: ADR-005 now exists as the reviewed design artifact for OC-005. This task plan is the planning and review wrapper that got that ADR through review and leaves behind an implementation-ready gate for OC-005; it is not an implementation plan for live tool-surface consolidation.

---

## Objective

Resolve OC-005 by producing and reviewing an ADR that chooses a typed tool-surface consolidation strategy for `agent-handoff-mcp`, without starting the implementation rewrite prematurely.

## Problem Statement

The output-contract v2 spec originally left tool consolidation unresolved on purpose. ADR-005 now resolves that design gate, but this task still needs its planning wrapper to reflect the reviewed state honestly: the ADR selects the typed-dispatch direction, the spec now carries ADR-backed guardrails, and the remaining output of AHMCP-4 is an implementation-ready design record rather than any live tool-surface rewrite.

The next honest step is still not code. It is to leave behind aligned planning artifacts that inventory the real tool families and downstream enumerators, capture the chosen typed-dispatch model, and narrow the follow-on implementation direction without pretending the consolidation itself has landed.

## Constraints

- This task produces an ADR and implementation-ready decision record; it does not consolidate the live tool surface.
- Any chosen approach must preserve typed MCP schemas per entity family. An opaque `payload: dict` contract is explicitly forbidden by the reviewed spec.
- The ADR must evaluate the current profile split, downstream tool-name enumerators, and transport/test implications before choosing a mapping.
- The ADR should choose one design direction and a realistic target range or count, but it must not edit consumer contracts as if the implementation already landed.
- The resulting implementation work should remain separable from the already-approved Tier 1 and Tier 2 tasks.

## Workflow Principles

- Inventory first; do not design from memory or aspiration.
- Compare only typed-dispatch options that can be defended against the live `api.py`, CLI registry, and transport tests.
- Keep the ADR crisp: decision, alternatives, migration cost, and downstream update scope.
- End with a narrowed implementation entrypoint, not another open-ended exploration doc.

## Terminology

- **Typed polymorphic dispatch**: A smaller tool surface that still preserves field-level schemas per entity family.
- **Tool family**: A cluster of operations such as record, update, list, generate, or search that may be candidates for consolidation.
- **Downstream enumerator**: Any doc, test, adapter, or runtime surface that assumes a concrete tool name list.
- **Design gate**: A planning checkpoint that must be resolved before implementation tasks are considered valid.

## Current State Analysis

- `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` now carries the ADR-backed OC-005 direction and implementation guardrails instead of leaving the design unresolved.
- `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md` now exists as the reviewed design artifact, so the remaining role of this task plan is to document the review-approved boundary between the ADR and the deferred implementation task.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` is the source of truth for current tool registrations, descriptions, and argument schema exposure.
- Transport tests such as `test_stdio.py`, `test_http.py`, `test_cli.py`, and `test_adapters.py` already enumerate expectations about the live tool surface and profile counts; any rename or consolidation has to migrate those surfaces deliberately.
- `docs/agentic/contracts/agent-handoff-mcp.md` documents the current surface and will need a same-slice update once consolidation is implemented, but not before the ADR chooses the direction.
- The approved spec already requires downstream enumerator updates as part of any future OC-005 implementation, so the ADR must inventory those surfaces explicitly.

## Target Outcome

After this task:

- a reviewed ADR exists at `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`
- the ADR selects one typed-dispatch model and rejects the weaker alternatives with rationale
- the output-contract v2 spec is updated to replace unresolved OC-005 placeholders with the ADR-backed direction and implementation guardrails
- this task plan remains as the review and approval wrapper for ADR-005 rather than pretending to be the implementation plan for the consolidation itself
- a follow-on implementation task can be created without guessing at tool names, schema strategy, or downstream update scope

## Context Loading

- Spec: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md`
- Existing ADR draft: `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`
- Adjacent task plans:
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md`
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-2-bounded-current-task-rendering-and-mutation-output-task-plan.md`
  - `packages/agent-handoff-mcp/docs/tasks/AHMCP-3-response-envelope-and-output-contract-v2-rollout-task-plan.md`
- Live tool-surface anchors:
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py`
  - `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py`
  - `packages/agent-handoff-mcp/tests/test_cli.py`
  - `packages/agent-handoff-mcp/tests/test_stdio.py`
  - `packages/agent-handoff-mcp/tests/test_http.py`
  - `packages/agent-handoff-mcp/tests/test_adapters.py`
- Published contract:
  - `docs/agentic/contracts/agent-handoff-mcp.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP tool catalog | handoff core | current named tool list in `api.py` and contract doc | ADR chooses future consolidation model only; no live surface change yet | Yes; implementation deferred | ADR inventory + planning review |
| CLI / transport schema expectations | handoff core | tests and registry reflect current tool names | ADR enumerates migration scope but does not rewrite tests yet | Yes | enumerator inventory in ADR |
| Published contract docs | handoff core | current tool families documented | ADR names future contract direction and implementation prerequisites | Yes | ADR + updated spec |

## Proposed Solution

Treat OC-005 as a bounded design task with three slices. First, inventory the current tool families and every downstream surface that would be touched by consolidation. Second, compare the viable typed-dispatch approaches against the live FastMCP and CLI schema constraints and choose one. Third, finalize the existing ADR-005 draft and update the output-contract v2 spec so the future implementation task starts from a reviewed design instead of a preliminary mapping.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Existing ADR draft | `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md` | review, revise, and finalize the draft design decision and chosen approach |
| Output-contract spec | `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-output-contract-v2-spec.md` | replace unresolved OC-005 placeholders with ADR-backed guidance |
| Live tool inventory anchor | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | verification-only source for current tool registrations and schemas |
| CLI inventory anchor | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | verification-only source for CLI command exposure |
| Transport inventory anchor | `packages/agent-handoff-mcp/tests/test_cli.py` | verification-only downstream enumerator |
| Transport inventory anchor | `packages/agent-handoff-mcp/tests/test_stdio.py` | verification-only downstream enumerator |
| Transport inventory anchor | `packages/agent-handoff-mcp/tests/test_http.py` | verification-only downstream enumerator |
| Transport inventory anchor | `packages/agent-handoff-mcp/tests/test_adapters.py` | verification-only downstream enumerator for profile counts and launcher assumptions |
| Published contract inventory | `docs/agentic/contracts/agent-handoff-mcp.md` | verification-only downstream enumerator and future same-slice update target |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-1-parameterize-handoff-mcp-read-surfaces-task-plan.md` | recent related plan that already reduced read-surface proliferation without collapsing explicit writes |
| `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-output-state-keeping-report.md` | original assessment that framed tool-surface reduction as secondary to output-state correctness |
| `docs/adrs/ADR-004-sync-completion-and-retention-hardening-rationale.md` | style and scope reference for a repo ADR |

## Verification Strategy

- Deterministic design proof:
  - the ADR contains a full current-tool inventory, selected approach, rejected alternatives, migration scope, and downstream enumerator list
  - the output-contract v2 spec references the ADR and no longer leaves OC-005 implementation shape ambiguous
- Planning-review verification:
  - run a planning review over the ADR and spec updates before any OC-005 implementation task is created
- Manual verification:
  - compare the ADR inventory against `api.py`, `cli.py`, and transport tests to confirm no enumerator surface was missed

## Slice Delivery

### Slice 1: Inventory Current Tool Families and Downstream Enumerators

**Goal**: Build the factual baseline the ADR needs.

Changes:

- Enumerate the live tool families from `api.py`
- Classify which families are plausible consolidation candidates and which should remain explicit
- Enumerate downstream surfaces that name or assume current tool names, including transport tests and contract docs
- Record the inventory in ADR working notes or directly in the ADR draft

Proof:

- The ADR draft contains a concrete inventory derived from live files, not memory
- Every downstream enumerator named in the spec is accounted for in the inventory

### Slice 2: Evaluate Typed-Dispatch Options and Choose One

**Goal**: Pick a design that preserves typed schemas and has an honest migration cost.

Changes:

- Compare the viable approaches, at minimum:
  - grouped semantic tools with per-domain typed operation models
  - one global `record/update/list` surface with broad unions
  - keeping the current explicit tool surface plus profile split only
- Evaluate each option against typed schema preservation, transport ergonomics, downstream migration cost, and realistic tool-count reduction
- Choose one design direction and define the minimum implementation guardrails

Proof:

- The ADR records the chosen approach and rejected alternatives with concrete reasons
- The chosen approach preserves typed schemas and names the downstream migration scope

### Slice 3: Publish ADR-005 and Update the Output Spec

**Goal**: Leave behind a reviewed design artifact that implementation planning can rely on.

Changes:

- Finalize the existing draft at `docs/adrs/ADR-005-agent-handoff-mcp-typed-tool-surface-consolidation.md`
- Update OC-005 in the output-contract v2 spec to reference the ADR and chosen implementation direction
- Capture any follow-on implementation preconditions, including downstream doc/test update scope and any staged rollout requirements

Proof:

- ADR-005 exists and passes planning review
- The output-contract v2 spec references ADR-005 and no longer treats OC-005 as an unresolved placeholder

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the approved output-contract v2 spec and the live handoff tool catalog before designing.
- [x] Confirmed this task remains design-only; no live tool consolidation lands here.
- [x] Verified the ADR will preserve typed MCP schemas and not regress to opaque payload dispatch.

### Checklist: Slice 1

- [x] Current tool families are inventoried from `api.py`.
- [x] Downstream tool-name enumerators are inventoried from transport tests and contract docs.
- [x] Candidate versus non-candidate tool families are distinguished explicitly.

### Checklist: Slice 2

- [x] Viable typed-dispatch approaches are compared.
- [x] Rejected opaque-payload dispatch is documented as rejected.
- [x] One design direction is chosen with explicit tradeoffs and migration scope.

### Checklist: Slice 3

- [x] ADR-005 is finalized at the planned path.
- [x] The output-contract v2 spec is updated to cite ADR-005 and the chosen direction.
- [x] Implementation preconditions are explicit enough to support a follow-on implementation task.

## Review Readiness

- [x] No OC-005 implementation task is created before ADR-005 is reviewed.
- [x] The ADR inventory and migration scope are grounded in live code and tests.
- [x] Handoff decisions record the selected design direction and the deferred implementation boundary.

## Success Criteria

- [x] ADR-005 chooses the typed consolidation approach for OC-005.
- [x] The approved spec references ADR-005 and stops treating OC-005 as design-undefined.
- [x] A follow-on implementation task can be created without guessing at tool names, schema strategy, or downstream update scope.
