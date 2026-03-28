# E12-2. Guidance Rollout and Context Routing

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Roll the new naming scheme into the repo’s author guidance and review-routing rules so planning and review behavior become deterministic at the documentation layer. When complete, agents and human operators should have one clear rule for which guide/template to load and how to name new epic/task/decision work.

## Problem Statement

Even with updated templates, agents can still miss the scheme if the startup guidance and planning-review rules lag behind. The current repo guidance discusses related surfaces, but it does not yet provide one compact, deterministic routing table for branch review vs planning review and epic/task/roadmap creation.

## Constraints

- Guidance updates must stay consistent with the template work from `E12-1`.
- `instructions.md` should remain a dispatcher-style cold-start file, not regrow into a planning playbook.
- Review guidance must distinguish between code review and planning-doc review without relying on product-specific behavior.

## Workflow Principles

- One routing rule should answer one question: which guide or template must be loaded for this request?
- `instructions.md` should point, not narrate.
- Examples should stay compact and directly match the enforced grammar planned for MCP.

## Terminology

- **Context router**: The rule set that maps request intent plus target path to the correct guide or template.
- **Planning review**: Review of epics, task plans, roadmaps, ADRs, or other planning/process docs.
- **Branch review**: Review of code or diffs rather than planning artifacts.

## Current State Analysis

- [instructions.md](docs/agentic/instructions.md) already routes to review guides and templates, but the epic calls for more explicit naming and context-routing rules.
- [development-workflow.md](docs/agentic/rules/development-workflow.md) is the natural execution-time rule surface for naming and handoff behavior, but it does not yet define the new reference grammar end to end.
- [planning-review-guide.md](docs/agentic/rules/planning-review-guide.md) should eventually validate missing/malformed references, but that check is not yet documented.
- The repo still needs a compact examples section that demonstrates one valid epic title, task title, decision id, and routing decision.

## Target Outcome

The repo guidance should say the same thing everywhere: new epics use `E<number>.`, new tasks use `<SID>-N.`, decisions carry agent/work references, code review loads the branch-review guide, planning review loads the planning-review guide, and artifact creation loads the matching template. `instructions.md` stays concise, while the more procedural rule surfaces carry the fuller examples and audit expectations.

## Context Loading

- Rules: [instructions.md](docs/agentic/instructions.md), [development-workflow.md](docs/agentic/rules/development-workflow.md), [planning-review-guide.md](docs/agentic/rules/planning-review-guide.md), [branch-review-guide.md](docs/agentic/rules/branch-review-guide.md)
- Contracts: [agent-handoff-mcp.md](docs/agentic/contracts/agent-handoff-mcp.md) for downstream decision-id alignment
- Handoff/MCP state: inspect open findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: not needed

## Contract and Boundary Impact

| Boundary          | Owner      | Current Contract                                      | Expected Change                                    | Compatibility Needed?                        | Verification |
| ----------------- | ---------- | ----------------------------------------------------- | -------------------------------------------------- | -------------------------------------------- | ------------ |
| Planning guidance | docs/rules | `docs/agentic/instructions.md` + rule guides          | Add deterministic naming/routing guidance          | Yes; additive and routing-safe               | docs review  |
| Review behavior   | docs/rules | `planning-review-guide.md` / `branch-review-guide.md` | Clarify which guide applies to which review intent | Yes; no behavior break, clearer routing only | docs review  |

## Proposed Solution

Update the guidance surfaces in layers: keep `instructions.md` to a compact router, put naming/routing details in `development-workflow.md`, add planning-review checks to `planning-review-guide.md`, and add one compact examples block that matches the future runtime-enforced decision grammar.

## Files and Surfaces to Change

| Surface | File                                                                              | Change                                                                                 |
| ------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| docs    | `docs/agentic/instructions.md`                                                    | Add compact naming/routing guidance without expanding cold-start scope                 |
| docs    | `docs/agentic/rules/development-workflow.md`                                      | Add the canonical epic/task/decision naming rules and author workflow expectations     |
| docs    | `docs/agentic/rules/planning-review-guide.md`                                     | Add checks for missing/malformed epic/task references and wrong template/guide routing |
| docs    | `docs/agentic/rules/branch-review-guide.md`                                       | Clarify code-review routing boundary relative to planning review                       |
| docs    | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md` | Mark Phase 2 task-plan linkage once scoped                                             |

## Related Files

| File                                           | Note                                                          |
| ---------------------------------------------- | ------------------------------------------------------------- |
| `docs/agentic/templates/EPIC.template.md`      | Updated by E12-1; guidance must match template wording        |
| `docs/agentic/templates/TASK_PLAN.template.md` | Updated by E12-1; guidance must match task-title format       |
| `docs/agentic/templates/ROADMAP.template.md`   | Context-routing guidance must point here for roadmap creation |

## Verification Strategy

- Deterministic tests:
  - `git diff --check -- docs/agentic/instructions.md docs/agentic/rules/development-workflow.md docs/agentic/rules/planning-review-guide.md docs/agentic/rules/branch-review-guide.md`
- Contract/fixture verification:
  - Verify all examples and routing rules use the same title/decision grammar as the epic and templates
- Manual verification:
  - Confirm a reviewer can choose the right guide/template from request type and target path without guessing

## Slice Delivery

### Slice 1: Naming Guidance Alignment

**Goal**: Align the general workflow rules with the new naming scheme.

Changes:

- Update `development-workflow.md` with epic/task/decision grammar.
- Add compact pointer text to `instructions.md` so cold-start routing remains correct.

Proof:

- Guidance examples and rule text match the template and epic naming scheme.

### Slice 2: Review and Template Routing Rules

**Goal**: Make guide/template selection deterministic from intent and target path.

Changes:

- Update `planning-review-guide.md` and `branch-review-guide.md` to clarify review routing.
- Add a short routing examples section covering branch review, planning review, epic creation, task-plan creation, and roadmap creation.
- Sync the epic’s Phase 2 task-plan link once the task is created.

Proof:

- The routing table and review guides no longer leave review/template selection to memory.

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative guidance and epic scope before editing.
- [ ] Confirmed the updated template wording from `E12-1` so guidance does not drift.

## Slice 1: Naming Guidance Alignment

- [ ] Updated `development-workflow.md`.
- [ ] Updated `instructions.md` in a dispatcher-safe way.
- [ ] Verified examples match the epic/template naming scheme.

## Slice 2: Review and Template Routing Rules

- [ ] Updated `planning-review-guide.md`.
- [ ] Updated `branch-review-guide.md`.
- [ ] Added deterministic routing examples.

## Review Readiness

- [ ] Guidance surfaces agree on the same epic/task/decision grammar.
- [ ] Cold-start routing remains concise.
- [ ] Handoff decision records the guidance changes and verification evidence.

## Stretch Goals

- [ ] Add a compact review checklist snippet for malformed work references once MCP enforcement lands.

## Success Criteria

- [ ] Agents can determine the correct guide or template from request intent and target path using repo guidance alone.
- [ ] Naming rules in the guidance match the templates and the epic with no contradictory examples.
