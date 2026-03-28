# E12-1. Naming Spec and Template Update

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Define the compact epic/task reference scheme as executable authoring rules and encode it directly into the planning templates. When this task is complete, new epic, task-plan, and roadmap docs should start from templates that require the new naming model by default instead of relying on reviewer memory.

## Problem Statement

The epic defines the target naming system, but the live templates still allow unnumbered epics, unprefixed task titles, and roadmap creation without an explicit routing contract. That leaves the most common authoring entrypoints misaligned with the intended scheme and makes later enforcement noisier than necessary.

## Constraints

- The task must stay in authoring-layer docs/templates; MCP enforcement belongs to later tasks.
- Epic numbering is global, but template guidance must remain deterministic even when the number is computed manually.
- Slice references are optional and must stay optional in template wording.

## Workflow Principles

- Templates should make the correct default easy and the wrong default conspicuous.
- Naming rules belong near the title/metadata surfaces where authors will actually see them.
- Roadmap template updates should focus on loading/routing requirements, not force the task-ref scheme onto roadmap titles.

## Terminology

- **Epic index**: The global `E<number>` prefix used in epic titles.
- **Epic short id**: The compact uppercase id that namespaces local task references.
- **Task reference**: The `<SID>-<local_index>` identifier shown in a task title.

## Current State Analysis

- [EPIC.template.md](docs/agentic/templates/EPIC.template.md) does not yet require an `E<number>` title or a declared epic short id.
- [TASK_PLAN.template.md](docs/agentic/templates/TASK_PLAN.template.md) still uses a generic `[TASK_TITLE]` placeholder with no enforced `<SID>-N.` pattern.
- [ROADMAP.template.md](docs/agentic/templates/ROADMAP.template.md) exists, but the epic notes that roadmap creation must explicitly load it through the same routing model as epic/task creation.
- The epic examples use `E12` as the local reference prefix for this workstream, but the authoring templates do not yet explain where that identifier belongs in a newly created epic.

## Target Outcome

The planning templates should encode the reference scheme directly. Epic authors start from a template that requires `E<number>. Title` plus an `Epic Short ID` field; task authors start from a template that requires `<SID>-N. Title`; roadmap authors see an explicit note that roadmap creation must go through the roadmap template even though roadmap titles remain version-oriented. Slice references remain clearly optional.

## Context Loading

- Rules: [instructions.md](docs/agentic/instructions.md), [development-workflow.md](docs/agentic/rules/development-workflow.md)
- Contracts: none beyond template/guidance ownership
- Handoff/MCP state: inspect open findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: not needed

## Proposed Solution

Update the three planning templates so the naming/reference model is visible at the point of authoring. Add concise template notes for global epic numbering, epic short-id declaration, task-title formatting, and roadmap routing expectations. Keep the template changes purely structural and defer runtime validation to later tasks.

## Files and Surfaces to Change

| Surface | File                                                                              | Change                                                                           |
| ------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| docs    | `docs/agentic/templates/EPIC.template.md`                                         | Require `E<number>.` title format and a declared epic short-id field             |
| docs    | `docs/agentic/templates/TASK_PLAN.template.md`                                    | Require `<epic_short_id>-<local_index>. <Title>` task titles                     |
| docs    | `docs/agentic/templates/ROADMAP.template.md`                                      | Clarify that roadmap creation must explicitly route through the roadmap template |
| docs    | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md` | Mark Phase 1 task-plan linkage once scoped                                       |

## Related Files

| File                                                                              | Note                                                                      |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `docs/agentic/rules/planning-review-guide.md`                                     | Later review guidance should validate the template-driven naming surfaces |
| `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md` | Phase source of truth for scope and exit criteria                         |

## Verification Strategy

- Deterministic tests:
  - `git diff --check -- docs/agentic/templates/EPIC.template.md docs/agentic/templates/TASK_PLAN.template.md docs/agentic/templates/ROADMAP.template.md`
- Contract/fixture verification:
  - Verify each template visibly encodes the required naming/routing rule at the title or metadata layer
- Manual verification:
  - Confirm a new epic/task/roadmap author could follow the template without consulting the epic prose

## Slice Delivery

### Slice 1: Epic and Task Template Naming

**Goal**: Encode epic/task reference rules directly into the two primary planning templates.

Changes:

- Update `EPIC.template.md` to require `E<number>. <Title>` and `Epic Short ID`.
- Update `TASK_PLAN.template.md` to require `<SID>-N. <Title>` and explain the local numbering rule.

Proof:

- Template diffs show the required title/metadata fields and `git diff --check` passes.

### Slice 2: Roadmap Routing and Optional Slice Guidance

**Goal**: Align the roadmap template and template notes with the rest of the naming model.

Changes:

- Update `ROADMAP.template.md` to require explicit template loading/routing for roadmap creation.
- Add concise wording that slice references are optional rather than mandatory in headings/titles.
- Sync the epic’s Phase 1 task-plan link once the task is created.

Proof:

- Template text reflects roadmap routing and optional slice-reference guidance without introducing contradictory naming rules.

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, epic scope, and current templates before editing.
- [ ] Confirmed no runtime/MCP enforcement is being promised in this template-only task.

## Slice 1: Epic and Task Template Naming

- [ ] Updated `EPIC.template.md`.
- [ ] Updated `TASK_PLAN.template.md`.
- [ ] Verified the new title patterns are explicit in the templates.

## Slice 2: Roadmap Routing and Optional Slice Guidance

- [ ] Updated `ROADMAP.template.md`.
- [ ] Documented slice references as optional-only.
- [ ] Linked Phase 1 back to this task plan from the epic.

## Review Readiness

- [ ] Template changes are consistent with the epic naming spec.
- [ ] No template now implies a contradictory title format.
- [ ] Handoff decision records the template changes and verification evidence.

## Stretch Goals

- [ ] Add short inline examples to the templates once the naming format is stable across guidance and MCP enforcement.

## Success Criteria

- [ ] New epic authors see `E<number>` and epic short-id requirements directly in the epic template.
- [ ] New task authors see the `<SID>-N.` title format directly in the task-plan template.
- [ ] Roadmap authors are explicitly routed to the roadmap template without adopting the task-ref title scheme.
