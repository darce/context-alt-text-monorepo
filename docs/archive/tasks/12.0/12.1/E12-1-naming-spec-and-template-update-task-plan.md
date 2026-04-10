# E12-1. Naming Spec and Template Update

> **Metadata**
>
> - **Date**: 2026-03-28 16:55 EDT
> - **Author**: codex
> - **Owning Epic**: [epic-task-reference-prefixing-and-handoff-enforcement-epic.md](docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: `E12` (derived from the owning epic's declared short id)

## Objective

Verify and close the template-alignment slice that already encoded the compact epic/task reference scheme into the live planning templates. New epic, task-plan, and roadmap docs should already start from templates that require the new naming model by default instead of relying on reviewer memory.

## Problem Statement

The original Phase 1 problem has already been addressed in the template surfaces, but this task plan still reads as if that work is pending. That stale framing creates false follow-up work and confuses later phases about whether template alignment is still an open dependency.

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

- [EPIC.template.md](docs/agentic/templates/EPIC.template.md) already requires the `E[GLOBAL_EPIC_INDEX]. [EPIC_TITLE]` title format and an `Epic Short ID` field.
- [TASK_PLAN.template.md](docs/agentic/templates/TASK_PLAN.template.md) already requires `[EPIC_SHORT_ID]-[LOCAL_TASK_INDEX]. [TASK_TITLE]`.
- [ROADMAP.template.md](docs/agentic/templates/ROADMAP.template.md) already includes the routing note that roadmap creation must explicitly load the roadmap template.
- The remaining work for this slice is to keep the task plan and epic dependency chain honest by treating Phase 1 as delivered and verification-only.

## Target Outcome

This task plan should accurately describe Phase 1 as complete. Epic authors already start from a template that requires `E<number>. Title` plus an `Epic Short ID` field; task authors already start from a template that requires `<SID>-N. Title`; roadmap authors already see an explicit note that roadmap creation must go through the roadmap template even though roadmap titles remain version-oriented.

## Context Loading

- Rules: [instructions.md](docs/agentic/instructions.md), [development-workflow.md](docs/agentic/rules/development-workflow.md)
- Contracts: none beyond template/guidance ownership
- Handoff/MCP state: inspect open findings and recent decisions under `agentic-development-process-hardening-epic`
- External docs via `ctx7` only if: not needed

## Proposed Solution

Treat E12-1 as a completed prerequisite. Update this plan so it documents verification and handoff closure rather than re-describing already-landed template edits as pending implementation.

## Files and Surfaces to Change

| Surface | File                                                                              | Change                                                                           |
| ------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| docs    | `docs/tasks/12.0/12.1/E12-1-naming-spec-and-template-update-task-plan.md`         | Mark the slice as already delivered and convert the plan to verification/closure |
| docs    | `docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md` | Keep Phase 1 dependency wording aligned with the delivered state                 |

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

**Goal**: Confirm the epic/task template naming slice is already delivered and close it cleanly.

Changes:

- Verify `EPIC.template.md` already requires `E<number>. <Title>` and `Epic Short ID`.
- Verify `TASK_PLAN.template.md` already requires `<SID>-N. <Title>` and explain the local numbering rule.
- Update this task plan to reflect the delivered state.

Proof:

- Template diffs show the required title/metadata fields and `git diff --check` passes.

### Slice 2: Roadmap Routing and Optional Slice Guidance

**Goal**: Confirm the roadmap-routing note is already in place and close the remaining plan drift.

Changes:

- Verify `ROADMAP.template.md` already requires explicit template loading/routing for roadmap creation.
- Verify slice references remain optional rather than mandatory in headings/titles.
- Sync the epic’s Phase 1 dependency wording with the delivered state if needed.

Proof:

- Template text reflects roadmap routing and optional slice-reference guidance without introducing contradictory naming rules.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the minimum authoritative rules, epic scope, and current templates before editing.
- [x] Confirmed no runtime/MCP enforcement is being promised in this template-only task.

## Slice 1: Epic and Task Template Naming

- [x] Verified `EPIC.template.md`.
- [x] Verified `TASK_PLAN.template.md`.
- [x] Verified the new title patterns are explicit in the templates.

## Slice 2: Roadmap Routing and Optional Slice Guidance

- [x] Verified `ROADMAP.template.md`.
- [x] Verified slice references as optional-only.
- [x] Linked Phase 1 back to this task plan from the epic.

## Review Readiness

- [x] Template changes are consistent with the epic naming spec.
- [x] No template now implies a contradictory title format.
- [x] Handoff decision records the template changes and verification evidence.

## Stretch Goals

- [x] Add short inline examples to the templates once the naming format is stable across guidance and MCP enforcement.

## Success Criteria

- [x] New epic authors see `E<number>` and epic short-id requirements directly in the epic template.
- [x] New task authors see the `<SID>-N.` title format directly in the task-plan template.
- [x] Roadmap authors are explicitly routed to the roadmap template without adopting the task-ref title scheme.
