# Epic Template

> Use this template for multi-phase epics under `docs/epics/`.
> Epics define a **product capability** delivered across multiple task plans.
> Each phase spawns one or more task plans (`TASK_PLAN.template.md`) for implementation details.
>
> Key differences from task plans:
>
> - No "Functions to Change" or code patterns (too granular for an epic)
> - Phases have goals, deliverables, and exit criteria
> - External dependencies and parallel workstreams are first-class
> - Code anchors orient agents to the relevant codebase surface area
>
> Key differences from roadmaps:
>
> - Epics deliver one bounded capability; roadmaps span the full product vision
> - Epics track progress (completed / in-progress / not-started phases)
> - Epics link to concrete task plans; roadmaps link to epics

---

# [EPIC_TITLE] (v[VERSION])

## Objective

[What capability the system gains when this epic is complete. 2-3 sentences max.]

## Problem Statement

[What user-visible behavior is broken or missing. Why the current architecture fails.]

## UX Vision

[Target user experience. What the user sees and does when the epic is complete.]

## Constraints

- [Architectural or policy constraint that shapes all phases]
- [External dependency constraint]
- [Technology or timeline constraint]

## Terminology

- **[Term]**: [Definition as used in this epic]

## Current State

[What works, what's broken, what's missing. Bullet points.]

- [Component] does X but should do Y.
- [Capability] does not exist yet.

## Target Architecture

[Narrative description of the end-state architecture. Include data model, integration pattern, and key design decisions.]

### Design Decisions

| Decision                         | Rationale                                  |
| -------------------------------- | ------------------------------------------ |
| [e.g., No taxonomy for clusters] | [Why this was chosen over the alternative] |

### Data Model

[Table schemas, entity relationships, or data flow description.]

## Phased Delivery

### Phase N: [Title] -- [STATUS]

> **Status**: completed | in-progress | not-started
> **Task plans**: [link to task plan(s)] or "not yet scoped"

**Goal**: [One sentence.]

Deliverables:

- [Deliverable]

Exit criteria:

- [Observable outcome that proves the phase is done]

## External Dependencies

| Dependency                | Owner                | Status                             | Blocks                  |
| ------------------------- | -------------------- | ---------------------------------- | ----------------------- |
| [e.g., Snapshot endpoint] | [e.g., Backend team] | [Not started / In progress / Done] | [Phase N exit criteria] |

## Code Anchors

| Layer    | File               | Note                            |
| -------- | ------------------ | ------------------------------- |
| Plugin   | `path/to/file.php` | [Current role and what changes] |
| Backend  | `path/to/file.py`  | [Current role]                  |
| Frontend | `path/to/file.ts`  | [Current role]                  |

---

# Consolidated Checklist

## Phase N: [Title] -- [STATUS]

- [ ] [Deliverable or sub-task]

## Deferred (Post-[VERSION])

- [ ] [Explicitly deferred work with rationale]
