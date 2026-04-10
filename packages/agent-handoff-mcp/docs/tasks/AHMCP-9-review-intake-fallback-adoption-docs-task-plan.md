# AHMCP-9. Review Intake Fallback Adoption Docs

> **Metadata**
>
> - **Date**: 2026-04-10 02:30 EST
> - **Author**: GPT-5.4
> - **Project**: `agent-handoff-mcp`
> - **Task ID**: `AHMCP-9`
> - **Target Branch**: `feature/ahmcp-9-review-intake-fallback-docs`
> - **Review Coverage Target**: 2
> - **Expected Review Path**: planning-aware branch review focused on contract/doc accuracy and boundary clarity
> - **Spec**: `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md`

---

## Objective

Implement `RIF-003` by updating the handoff contract and review guidance so agents have a documented packet-first path plus a deterministic handoff-only fallback. When this task is complete, the docs describe the real public surfaces from AHMCP-8 and the planning artifacts point to concrete package-local implementation tasks instead of placeholders.

## Problem Statement

The assessment and ADR now define the correct ownership boundary, but the surrounding docs still leave the fallback sequence implicit. The current review guides say to prefer the latest-slice packet, and the handoff contract says cross-task review-summary tools live on orchestrator, but none of those docs tell a handoff-only caller exactly what to do next. That gap invites ad hoc archaeology and risks reintroducing the wrong architectural idea: a second compound review packet on handoff.

## Constraints

- AHMCP-8 must land first; this task documents shipped primitives, not speculative APIs.
- The docs must preserve the preferred orchestrator packet path and present the handoff-only flow as a degraded fallback.
- No guide, contract, README, or planning artifact may imply that handoff owns a compound `get_review_packet` surface.
- Planning artifacts stay package-local under `packages/agent-handoff-mcp/docs/` rather than monorepo app task directories.

## Workflow Principles

- Update the owning contract first, then the review guides that consume it.
- Keep the fallback recipe deterministic and short: exact tool names, exact order, no narrative drift.
- Replace placeholders in the assessment/ADR with real artifact paths in the same slice so the planning chain is self-contained.

## Terminology

- **Packet-first path**: Use `get_latest_slice_review_packet` when orchestrator is loaded.
- **Handoff-only fallback**: The documented four-call sequence that reconstructs review-intake context without orchestrator.
- **Adoption docs**: Contracts, review guides, and planning artifacts that teach callers how to use the implemented surface.

## Current State Analysis

- `docs/agentic/contracts/agent-handoff-mcp.md` points review-summary tools to orchestrator but does not yet document the handoff fallback sequence.
- `docs/agentic/rules/branch-review-guide.md` and `docs/agentic/rules/planning-review-guide.md` already prefer packet-first review, but they do not yet show the handoff-only degraded path.
- The assessment and ADR now point at the package-local spec and task plans, but AHMCP-9 still needs to verify and finalize those cross-links as part of the adoption-docs pass.
- Contract ownership between AHMCP-8 and AHMCP-9 needs to stay distinct: AHMCP-8 owns the new tool-surface rows and parameter docs, while AHMCP-9 owns the fallback-sequence guidance that sits around those surfaces.

## Target Outcome

The handoff contract, branch review guide, and planning review guide all describe the same two-level workflow: packet-first when orchestrator is available, deterministic handoff-only fallback when it is not. The assessment and ADR point to the package-local spec and task plans that implement that decision. A reviewer can enter the planning chain at the assessment, ADR, spec, or task-plan level and reach the same artifact set without guessing where the implementation work lives.

## Context Loading

- Rules:
  - `docs/agentic/rules/branch-review-guide.md`
  - `docs/agentic/rules/planning-review-guide.md`
  - `docs/agentic/rules/planning-pipeline.md`
- Contracts:
  - `docs/agentic/contracts/agent-handoff-mcp.md`
  - `docs/agentic/contracts/agent-orchestrator-mcp.md`
- Handoff/MCP state: open planning findings for the review-intake spec and ADR, if any
- External docs via `ctx7` only if: not needed; this task is repo-internal documentation work

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Handoff contract | `agent-handoff-mcp` | Documents orchestrator-owned review-summary tools but not the new fallback guidance around the AHMCP-8 primitives | Add only the fallback-sequence guidance that frames the AHMCP-8 tool rows and parameter docs | Yes; wording must stay consistent with AHMCP-8 implementation and ADR-007 without duplicating AHMCP-8 ownership | `rg` verification across contract and guides |
| Review guidance | monorepo docs | Packet-first guidance exists; fallback path is implicit | Add explicit handoff-only fallback section to both guides | Yes; branch and planning guidance must agree on tool order and ownership | `rg` verification and planning review |
| Planning chain | package-local docs + ADR | Assessment/ADR still contain placeholders | Replace placeholders with package-local spec/task plan references | Yes; keep the artifact trail coherent | `rg` verification across assessment/ADR/spec/task plans |

## Proposed Solution

Update the contract and guides after AHMCP-8 lands, then rewrite the assessment/ADR references so the planning chain points at the concrete package-local artifacts. The docs will explicitly present a preferred packet-first path and a four-call handoff-only fallback path, and they will call out that the fallback is degraded rather than compound.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| Handoff contract | `docs/agentic/contracts/agent-handoff-mcp.md` | Document `get_verified_tests`, `verified_test`, and the fallback sequence |
| Branch review guide | `docs/agentic/rules/branch-review-guide.md` | Add `Handoff-only fallback` section under latest-slice review guidance |
| Planning review guide | `docs/agentic/rules/planning-review-guide.md` | Add parallel `Handoff-only fallback` section |
| Assessment | `packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md` | Replace placeholder next-step lines with the real spec/task plan references |
| ADR | `docs/agentic/adrs/ADR-007-review-intake-handoff-fallback-boundary.md` | Replace placeholder implementation-task reference with the created package-local task plans |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/docs/specs/agent-handoff-mcp-review-intake-handoff-fallback-spec.md` | Source of `RIF-003` |
| `packages/agent-handoff-mcp/docs/tasks/AHMCP-8-verified-test-search-and-read-surfaces-task-plan.md` | Upstream implementation dependency |
| `docs/agentic/contracts/agent-orchestrator-mcp.md` | Reference-only; preferred packet path stays here |

## Verification Strategy

- Deterministic tests:
  - none required beyond the code-backed proofs from AHMCP-8
- Contract/fixture verification:
  - `rg -n "get_verified_tests|verified_test|Handoff-only fallback|get_latest_slice_review_packet" docs/agentic/contracts/agent-handoff-mcp.md docs/agentic/rules/branch-review-guide.md docs/agentic/rules/planning-review-guide.md packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md docs/agentic/adrs/ADR-007-review-intake-handoff-fallback-boundary.md`
- Runtime-parity / environment checks:
  - none required; this is documentation alignment work
- Manual verification:
  - Read the branch guide and planning guide top-to-bottom and confirm the preferred path and fallback path use the same tool names and ordering

## Slice Delivery

### Slice 1: Contract and Planning Chain Alignment

**Goal**: Update the owning contract and the planning artifacts to point at the real package-local implementation path.

Changes:

- Verify and finalize the assessment/ADR cross-links to the package-local spec and task plan references.
- Add the fallback-sequence guidance section to the handoff contract around the AHMCP-8-documented `get_verified_tests` and `verified_test` surfaces.
- Confirm the planning chain still resolves cleanly after the contract/guidance updates.

Proof:

- `rg -n "get_verified_tests|verified_test|AHMCP-8|AHMCP-9" docs/agentic/contracts/agent-handoff-mcp.md packages/agent-handoff-mcp/docs/assessments/agent-handoff-mcp-review-intake-tooling-proposal.md docs/agentic/adrs/ADR-007-review-intake-handoff-fallback-boundary.md`

### Slice 2: Review Guide Fallback Adoption

**Goal**: Teach reviewers the exact packet-first and handoff-only flows without implying a second compound packet on handoff.

Changes:

- Add a `Handoff-only fallback` section to the branch review guide.
- Add the same fallback section to the planning review guide.
- Keep `get_latest_slice_review_packet` as the preferred path and label the handoff-only sequence as degraded fallback.

Proof:

- `rg -n "Handoff-only fallback|get_latest_slice_review_packet|get_verified_tests" docs/agentic/rules/branch-review-guide.md docs/agentic/rules/planning-review-guide.md`

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded ADR-007, the review-intake spec, and both MCP contracts before editing.
- [ ] Confirmed AHMCP-8 shipped before documenting the new public tool and record type.
- [ ] Preserved orchestrator ownership of the compound packet in every doc touchpoint.

### Checklist for Slice 1: Contract and Planning Chain Alignment

- [ ] Add the fallback-sequence guidance section to the handoff contract around the AHMCP-8-documented `get_verified_tests` and `verified_test` surfaces.
- [ ] Verify the assessment next steps still point at the package-local artifact references.
- [ ] Verify the ADR implementation-task references still point at the package-local task plans.
- [ ] Capture grep-based proof for those references.

### Checklist for Slice 2: Review Guide Fallback Adoption

- [ ] Add a `Handoff-only fallback` section to the branch review guide.
- [ ] Add the matching section to the planning review guide.
- [ ] Confirm the packet-first path remains the preferred guidance.
- [ ] Capture grep-based proof for the fallback wording.

## Review Readiness

- [ ] No doc claims a second compound packet exists on handoff.
- [ ] Packet-first and fallback guidance use the same tool names as the shipped contract.
- [ ] Handoff decision records the contract/guide updates and the verification commands.

## Stretch Goals

- [ ] Add one concise README example if package-level usage docs start listing review-intake tools explicitly after AHMCP-8.

## Success Criteria

- [ ] The planning chain from assessment -> ADR -> spec -> task plans resolves to concrete package-local artifacts.
- [ ] The handoff contract and review guides all describe the same deterministic fallback sequence.
- [ ] No shared doc routes this work into plugin or description-service task directories.