# E12-4. Migration Policy and Audit Pass

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Add one explicit grandfathering rule for historical planning artifacts and one lightweight checklist reviewers can use for new work. When complete, the repo should be clear that old docs/decisions remain historical records while new epics, task plans, and handoff writes must follow the new naming scheme.

## Problem Statement

The remaining risk is not a large migration; it is drift. Without one short grandfathering rule and one short compliance checklist, reviewers can still waste time debating whether older docs need renames or whether new work is actually in bounds.

## Constraints

- Treat historical docs and decisions as grandfathered by default unless a specific artifact blocks review or tooling.
- The written rule must match the actual MCP enforcement boundary for new writes.
- Keep this task to checklist and policy text, not broad cleanup.

## Workflow Principles

- Prefer a clear grandfathering rule over silent inconsistency.
- Reviewers need a short compliance checklist, not an archaeology exercise.
- Contract and rule surfaces should describe the same old-vs-new policy.

## Current State Analysis

- The epic already points in the right direction: enforce new work and treat older content as historical unless there is a concrete reason to touch it.
- Reviewers do not yet have a named checklist for verifying new epic/task/decision compliance.
- Contract text and guidance still need one final alignment pass once the naming grammar lands.

## Target Outcome

The repo should have one explicit statement that historical planning docs and historical decisions are grandfathered by default, and one compact checklist for reviewing new work. Any still-live rule/contract text that documents the old format should be updated in the same pass.

## Context Loading

- Rules: [development-workflow.md](docs/agentic/rules/development-workflow.md), [planning-review-guide.md](docs/agentic/rules/planning-review-guide.md)
- Contracts: [agent-handoff-mcp.md](docs/agentic/contracts/agent-handoff-mcp.md)
- Handoff/MCP state: inspect open findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: not needed

## Proposed Solution

Write the grandfathering rule where reviewers and implementers will actually see it, then align this phase with the checklist/routing guidance that lands in `E12-2` instead of creating a second owner for `planning-review-guide.md`. Avoid broad historical rename policy and avoid planning a backfill unless a specific stale artifact is already causing confusion.

## Files and Surfaces to Change

| Surface  | File                                                                              | Change                                                                                          |
| -------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| docs     | `docs/agentic/rules/development-workflow.md`                                      | Add one concise grandfathering rule and reviewer checklist references                           |
| docs     | `docs/agentic/rules/planning-review-guide.md`                                     | Verification-only: confirm the checklist added by `E12-2` remains sufficient for policy rollout |
| contract | `docs/agentic/contracts/agent-handoff-mcp.md`                                     | Clarify that new decision writes are enforced while historical rows are grandfathered           |
| docs     | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md` | Keep Phase 4 language aligned with the slimmed task scope                                       |

## Related Files

| File                                                       | Note                                                                       |
| ---------------------------------------------------------- | -------------------------------------------------------------------------- |
| `docs/agentic/instructions.md`                             | Should keep only concise routing/pointer text once the policy is finalized |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | Runtime behavior the grandfathering rule must match                        |

## Verification Strategy

- Deterministic tests:
  - `git diff --check -- docs/agentic/rules/development-workflow.md docs/agentic/rules/planning-review-guide.md docs/agentic/contracts/agent-handoff-mcp.md docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md`
- Contract/fixture verification:
  - Verify the written grandfathering rule matches the actual enforcement boundary for new writes
- Manual verification:
  - Confirm a reviewer can answer “is this new epic/task/decision compliant?” from the checklist without reading the whole epic

## Slice Delivery

### Slice 1: Grandfathering Rule and Review Checklist

**Goal**: Finish the naming rollout with one explicit historical-content rule and one lightweight compliance checklist.

Changes:

- Add a concise grandfathering rule for historical docs and historical decision rows.
- Add a compact checklist for reviewing new epics, task plans, and decisions.
- Update any still-live stale text that implies old naming remains current for new work.
- Keep the epic’s Phase 4 wording aligned with this smaller scope.

Proof:

- Workflow, planning-review guidance, and the MCP contract all describe the same old-vs-new rule.
- Review guidance contains one concise checklist for naming compliance and no contradictory stale guidance remains.

# Consolidated Checklist

## Context and Ownership

- [x] Loaded the current workflow, planning-review, and MCP contract surfaces before editing.
- [x] Confirmed the grandfathering rule matches actual new-write enforcement behavior.

## Slice 1: Grandfathering Rule and Review Checklist

- [x] Documented a concise grandfathering rule in workflow/contract text. (`development-workflow.md` Grandfathering Rule section; `agent-handoff-mcp.md` contract grandfathering paragraph.)
- [x] Added a concise compliance checklist. (`development-workflow.md` New-Work Compliance Checklist; `planning-review-guide.md` Naming and Reference Compliance section.)
- [x] Updated stale old-format references that would confuse reviewers.
- [x] Kept the rule aligned with actual enforcement boundaries.
- [x] Kept the epic's Phase 4 language aligned with this scope.

## Review Readiness

- [x] Historical grandfathering rule is explicit.
- [x] Reviewers have a practical checklist for new work.
- [x] Handoff decision records the policy/audit updates and verification evidence.

## Stretch Goals

- [ ] Add a future audit helper command only if the manual checklist proves too noisy. (Deferred; manual checklist is adequate.)

## Success Criteria

- [x] The repo has a written grandfathering rule for historical docs/decisions and a clear new-write enforcement rule.
- [x] Reviewers can verify new epic/task/decision naming compliance from a lightweight checklist.
