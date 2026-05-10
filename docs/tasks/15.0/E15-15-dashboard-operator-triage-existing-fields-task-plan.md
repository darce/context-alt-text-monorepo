# E15-15. Dashboard Operator Triage with Existing Fields

> **Metadata**
>
> - **Date**: 2026-05-05 21:15 EST
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-15
> - **Target Branch**: `feature/e15-15`
> - **Review Coverage Target**: 2

---

## Objective

Close out the original Tier 1 dashboard triage plan without duplicating the canonical PREIMPL track. When this task is complete, E15-15 explicitly points operators and implementers at [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md), documents which dashboard triage pieces have already landed, and limits any remaining E15-15 work to residual lifecycle cleanup rather than fresh implementation scope.

## Problem Statement

[docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md](../../assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md) and [docs/specs/alt-context-dashboard-operator-triage-spec.md](../../specs/alt-context-dashboard-operator-triage-spec.md) captured the original Tier 1 dashboard triage direction. Since this plan was drafted, the dashboard priority work landed in code and the broader PREIMPL implementation path moved to [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md), which explicitly supersedes E15-15 and E15-16 as the canonical implementation track. Leaving E15-15 in its original state creates duplicate implementation instructions and stale claims about missing behavior.

The superseding handoff decision is recorded as `cdx_decision_E15-20_supersede_e15_15_e15_16_dashboard_preimpl_tracks` (decision `2823`). E15-15 should therefore remain as a narrow closeout and redirection artifact, not as an active implementation plan.

## Constraints

- Do not re-open dashboard implementation scope that [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md) now owns.
- Do not describe already-landed dashboard behavior as missing work.
- Keep any residual E15-15 follow-up limited to lifecycle cleanup, redirects, and documentation alignment.
- Preserve the original Tier 1 constraint that no new REST response fields are justified solely for this retired plan.

## Workflow Principles

- Canonical implementation guidance lives in one plan, not two competing task plans.
- Residual task plans should describe current code honestly before asking for more work.
- Retirement notes should point to the owning successor task and the handoff decision that performed the supersession.

## Terminology

- **Blocking health**: sync failures, conflicts, offline/stale state, and mirror divergence that require operator action.
- **Review work**: pending identity clusters, unassigned persons, or E15-13 curriculum queues if already projected.
- **Residual closeout**: narrow task-plan work that documents supersession, lifecycle follow-up, or remaining cleanup after the primary implementation track moved elsewhere.
- **Canonical PREIMPL track**: [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md), plus its linked spec/ADR work, which now owns dashboard priority and durable-activity implementation decisions.

## Current State Analysis

- `DashboardPage` already imports `buildDashboardPriorityModel`, renders sections from `priorityModel.gridSectionOrder`, and renders `OrientationCard` after the dashboard grid rather than before it.
- `buildDashboardPriorityModel.ts` already exists as a pure ordering helper, so the old “missing deterministic priority model” claim is no longer accurate.
- Sync Health already renders topology backlog counts plus last-conflict and last-failure dates from existing fields.
- `useRecognitionJobHistory` and `DashboardPage` already distinguish recent activity with durable data and browser-local fallback labels, so the original “local-only recent activity” framing is incomplete.
- [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md) now owns the remaining implementation work for dashboard priority, durable activity authority, and optional diagnostics.
- The remaining gap for E15-15 is documentation and lifecycle alignment: retire this plan as an implementation source, point readers to E15-20, and avoid reopening already-landed work.

## Target Outcome

E15-15 becomes an honest historical/residual task plan. Readers can see which Tier 1 dashboard behaviors already landed, which successor task owns the remaining PREIMPL implementation, and what limited E15-15 lifecycle work remains before the task can be retired cleanly.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Spec: `docs/specs/alt-context-dashboard-operator-triage-spec.md`
- Assessment: `docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md`
- Related: `docs/tasks/15.0/E15-20-preimpl-dashboard-authority-and-priority-task-plan.md`
- Related: `docs/tasks/15.0/E15-16-dashboard-durable-activity-and-diagnostics-task-plan.md`
- Handoff/MCP state: active task `E15-15`, open planning findings for this plan/spec
- External docs via `ctx7` only if: React/Vitest behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| E15-15 task plan -> E15-20 task plan | docs/planning | stale parallel implementation guidance | redirect to canonical PREIMPL implementation owner | Yes; keep links explicit | planning review + doc inspection |
| E15-15 current-state notes -> dashboard code | docs/planning | outdated claims about missing UI behavior | document the landed `DashboardPage`/priority model state accurately | Yes | doc-to-code comparison |
| Handoff findings -> revised task plan | handoff/docs | two open planning findings | resolve by updating the plan to reflect supersession and current code | Yes | review-finding closure evidence |

## Proposed Solution

Rewrite E15-15 as a residual closeout task plan. Keep the original dashboard-triage context, but explicitly mark implementation ownership as superseded by E15-20, replace stale “to build” claims with current-state notes anchored to the existing dashboard code, and scope any remaining E15-15 work to lifecycle closure rather than fresh UI implementation.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| residual task plan | `docs/tasks/15.0/E15-15-dashboard-operator-triage-existing-fields-task-plan.md` | Mark supersession, refresh current-state claims, and constrain remaining scope |
| successor implementation plan | `docs/tasks/15.0/E15-20-preimpl-dashboard-authority-and-priority-task-plan.md` | Reference only; no edit required for this closeout |
| dashboard implementation anchor | `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | Reference only; evidence for landed priority/orientation behavior |
| priority helper | `apps/prototype-wp-alt-context/js/admin/pages/dashboard/buildDashboardPriorityModel.ts` | Reference only; evidence that the pure ordering model already exists |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts` | Existing recent-activity source/fallback behavior that makes the old “local-only” wording stale |
| `docs/specs/e15-app-refactoring-preimplementation-spec.md` | Upstream PREIMPL scope that E15-20 implements |
| `docs/specs/alt-context-dashboard-operator-triage-spec.md` | Original Tier 1 dashboard intent retained here as historical context |

## Verification Strategy

- Planning verification:
  - Confirm the revised plan explicitly names [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md) as the canonical implementation owner and cites decision `2823`.
- Code-anchor verification:
  - Confirm the revised current-state section matches `DashboardPage.tsx`, `buildDashboardPriorityModel.ts`, and the existing recent-activity hook behavior.
- Handoff verification:
  - Close planning findings `E15-15-PLAN-01` and `E15-15-PLAN-02` only after the revised document reflects supersession and the landed code state.

## Slice Delivery

### Slice 1: Supersession and Ownership Alignment

**Goal**: Remove E15-15 as a competing implementation source.

Changes:

- Mark [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md) as the canonical PREIMPL implementation track.
- Cite superseding handoff decision `2823`.
- Reframe E15-15 as residual closeout/lifecycle work only.

Proof:

- Planning review no longer reports E15-15 as a duplicate implementation track.

### Slice 2: Current-State Refresh

**Goal**: Replace stale implementation claims with repo-accurate notes.

Changes:

- Document that `DashboardPage` already uses `buildDashboardPriorityModel` and renders `OrientationCard` after the grid.
- Document that Sync Health already surfaces recency/topology details from existing fields.
- Document that recent activity already includes durable/fallback distinctions, making the original local-only framing stale.

Proof:

- Planning review no longer flags the current-state section as stale.

### Slice 3: Residual Lifecycle Closeout

**Goal**: Leave only narrow E15-15 follow-up that can be retired cleanly.

Changes:

- Limit remaining checklist items to handoff/documentation closeout.
- Avoid assigning new dashboard implementation slices to E15-15.
- Prepare the task to be retired once residual lifecycle work is done.

Proof:

- Open planning findings close against the revised document without reopening code scope.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded the dashboard assessment, dashboard spec, frontend rules, and handoff state before editing.
- [x] Confirmed [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md) is the canonical PREIMPL implementation owner.
- [x] Recorded the superseding handoff decision reference (`2823`) in this plan.

### Checklist for Slice 1: Supersession and Ownership Alignment

- [x] E15-15 no longer presents itself as the active implementation track.
- [x] E15-20 is linked as the canonical successor.
- [x] Residual E15-15 scope is limited to closeout/lifecycle work.

### Checklist for Slice 2: Current-State Refresh

- [x] `DashboardPage` current-state notes match the landed priority/orientation implementation.
- [x] Sync Health notes match the landed recency/topology rendering.
- [x] Recent-activity notes match the durable/fallback behavior already present.

### Checklist for Slice 3: Residual Lifecycle Closeout

- [x] No fresh dashboard implementation slices remain under E15-15.
- [x] Remaining task language is compatible with eventual done/archive flow.
- [x] Open planning findings can be closed against this revised document.

## Review Readiness

- [x] The plan explicitly defers implementation ownership to [E15-20](E15-20-preimpl-dashboard-authority-and-priority-task-plan.md).
- [x] The plan no longer claims already-landed dashboard behavior is missing.
- [x] Handoff decision records the residual-closeout scope and finding resolution.

## Stretch Goals

- [x] Retire E15-15 cleanly once any remaining lifecycle bookkeeping is complete.

## Success Criteria

- [x] E15-15 is no longer a stale or competing implementation plan.
- [x] The revised current-state section matches the dashboard code that already landed.
- [x] Planning findings `E15-15-PLAN-01` and `E15-15-PLAN-02` can be closed against this document revision.
