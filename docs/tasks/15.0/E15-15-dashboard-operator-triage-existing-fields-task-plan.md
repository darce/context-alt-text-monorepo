# E15-15. Dashboard Operator Triage with Existing Fields

> **Metadata**
>
> - **Date**: 2026-05-05 21:15 EST
> - **Author**: GitHub Copilot
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Task ID**: E15-15
> - **Target Branch**: `feature/e15-15-dashboard-operator-triage-existing-fields`
> - **Review Coverage Target**: 2

---

## Objective

Turn the dashboard into an operator triage surface using only fields that already exist. When this task is complete, blocking sync health and review work outrank onboarding and generic navigation, and the dashboard renders actionable healthy, failure, empty, partial, and loading states without adding new REST response fields.

## Problem Statement

[docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md](../../assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md) reports that the dashboard already exposes useful facts, but urgent sync failures and pending identity work compete with first-run onboarding, unavailable retention, local-only recent activity, and generic navigation panels. [docs/specs/alt-context-dashboard-operator-triage-spec.md](../../specs/alt-context-dashboard-operator-triage-spec.md) Tier 1 defines the low-contract implementation path: preserve the useful notice and existing panels while changing hierarchy, state handling, and existing-field copy.

## Constraints

- Tier 1 must not introduce new REST response fields.
- Keep the WordPress admin dashboard as an authenticated operator surface.
- Use existing design tokens and status indicators that pair icon/meaning with color.
- Do not fold curriculum queue ownership into the dashboard unless E15-13 explicitly selects it as an entry point.

## Workflow Principles

- Blocking health first, review queues second, progress context third, utilities last.
- Existing local/proxy state should be rendered honestly before proposing new contracts.
- Onboarding should help empty installs without obscuring real work.

## Terminology

- **Blocking health**: sync failures, conflicts, offline/stale state, and mirror divergence that require operator action.
- **Review work**: pending identity clusters, unassigned persons, or E15-13 curriculum queues if already projected.
- **Utility panel**: a secondary dashboard affordance such as retention, generic batch navigation, or onboarding.

## Current State Analysis

- `DashboardPage` renders `OrientationCard` before operational panels.
- Sync Health shows counts and remediation links, but not all available recency/topology fields.
- The Tier 1 `topology-backlog` state is already derivable from `SyncStatusResponse.topology_commands`; treat any non-zero `pending`, `failed`, or `conflict` count as backlog that should be surfaced before utilities.
- Retention unavailable state can occupy a dashboard card without a useful action.
- Batch Operations duplicates Workbench navigation even when no durable job data exists.
- Panel loading/failure states are independent, but the page lacks a deterministic priority model.

## Target Outcome

The dashboard behaves like an action console. If sync failures, conflicts, stale state, or pending review work exists, those states appear first and include direct links. First-run onboarding appears only when the product state is truly empty or non-actionable. Retention and batch navigation are concise unless they have current work to show.

## Context Loading

- Rules: `docs/agentic/rules/development-workflow.md`
- Rules: `docs/agentic/rules/frontend-guidelines.md`
- Rules: `docs/agentic/rules/testing-typescript.md`
- Spec: `docs/specs/alt-context-dashboard-operator-triage-spec.md`
- Assessment: `docs/assessments/current/alt-context-dashboard-ux-assessment-2026-05-05.md`
- Related: `docs/tasks/15.0/E15-13-roster-curation-loop-task-plan.md` only if curriculum queues become dashboard inputs
- Handoff/MCP state: active task `E15-15`, open planning findings for this plan/spec
- External docs via `ctx7` only if: React/Vitest behavior blocks a concrete implementation decision.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Dashboard React view -> existing hooks | frontend | existing media stats, identity stats, sync status, retention, job history hooks | reorder and render existing values honestly | Yes; no API field changes in this task | Vitest with mocked hooks |
| Sync status payload | plugin REST | existing `last_curation_*` and `topology_commands` fields | consume existing fields only | No response shape change | TypeScript render tests |
| Retention status payload | plugin REST | existing available/unavailable/error states | render lower priority or actionable copy | No response shape change | TypeScript render tests |

## Proposed Solution

Implement the Tier 1 spec items as a single frontend-focused dashboard plan. Introduce a small priority model over existing hook data, move orientation into state-aware rendering, enrich Sync Health copy from already-available fields, demote unavailable retention and generic batch navigation, and add mixed-state tests.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| dashboard page | `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | Apply priority model and existing-field triage layout |
| onboarding | `apps/prototype-wp-alt-context/js/admin/pages/dashboard/OrientationCard.tsx` | Make visibility product-state aware or controlled by dashboard state |
| sync types/rendering | `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts` | Consume existing recency/topology fields, type cleanup if needed |
| dashboard tests | `apps/prototype-wp-alt-context/js/admin/pages/__tests__/DashboardPage.test.tsx` | Cover priority ordering and partial states |
| dashboard styles | `apps/prototype-wp-alt-context/js/admin/styles/` | Adjust layout using `--acx-*` tokens only |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Existing sync-status payload owner; verify before assuming fields |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts` | Existing sync polling hook |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRetentionStatus.ts` | Existing retention hook |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionJobHistory.ts` | Local-storage job history remains secondary in this task |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm test -- --run js/admin/pages/__tests__/DashboardPage.test.tsx js/admin/pages/dashboard`
- Runtime-parity / environment checks:
  - Open `http://localhost:10010/wp-admin/admin.php?page=alt-context-dashboard#/dashboard` and verify failure/review priority before onboarding.
- Contract/fixture verification:
  - Tests assert no Tier 1 behavior requires new REST fields beyond current `SyncStatusResponse` and existing dashboard stats.
- Manual verification:
  - Healthy/empty first-run state can still show onboarding; failure and pending-review states do not.

## Slice Delivery

### Slice 1: Priority Model and Sync Health

**Goal**: Make blocking health and review work outrank orientation and utilities.

Changes:

- Add a deterministic dashboard priority model over current hook data.
- Render Sync Health with existing recency fields and a topology-backlog state derived from `topology_commands.pending > 0 || topology_commands.failed > 0 || topology_commands.conflict > 0`.
- Keep dead-letter/conflict links visible only when actionable.

Proof:

- Vitest covers healthy, queued, conflict, failure, offline, stale, and topology-backlog states.

### Slice 2: State-Aware Onboarding and Utilities

**Goal**: Keep onboarding and utility panels useful without letting them dominate active work.

Changes:

- Suppress the large orientation card when pending clusters, sync failures/conflicts, or stale mirror state exist.
- Defer suppression by current job state to E15-16, after that task records a durable activity source and stops relying on browser-local history.
- Make retention unavailable state actionable or lower priority.
- Compact generic batch navigation when no durable current job state exists.

Proof:

- Vitest covers first-run, active-work, dismissed, retention-available, retention-unavailable, and no-job states.

### Slice 3: Partial-State Rendering and Polish

**Goal**: Preserve independent panel loading while preventing mixed state from flattening urgency.

Changes:

- Add page-level rules for partial load/error states.
- Ensure status indicators include icon/text semantics, not color alone.
- Use existing `--acx-*` tokens for any style changes.

Proof:

- Vitest covers mixed loaded/error/loading states and avoids layout assertions that require new API fields.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the dashboard assessment, dashboard spec, frontend rules, and handoff state before editing.
- [ ] Confirmed no external dependency context is needed.
- [ ] Confirmed Tier 1 uses existing REST/hook fields only.

### Checklist for Slice 1: Priority Model and Sync Health

- [ ] Blocking health priority model implemented.
- [ ] Sync Health renders existing recency/topology fields where available.
- [ ] Healthy, queued, conflict, failure, offline, stale, and topology states tested.

### Checklist for Slice 2: State-Aware Onboarding and Utilities

- [ ] Large onboarding is suppressed when real work exists.
- [ ] Retention unavailable state is actionable or demoted.
- [ ] Generic batch navigation is compact without relying on browser-local job history as a suppression signal.

### Checklist for Slice 3: Partial-State Rendering and Polish

- [ ] Mixed loading/error states keep blocking health visible when loaded.
- [ ] Status indicators pair color with icon/text semantics.
- [ ] Token-only style changes verified.

## Review Readiness

- [ ] No new REST fields are required for this task.
- [ ] Runtime dashboard check confirms priority order in a failure or pending-review state.
- [ ] Handoff decision records existing-field scope and verification.

## Stretch Goals

- [ ] Add a compact help/onboarding affordance shared by Dashboard and Workbench if it can be done without broad navigation refactor.

## Success Criteria

- [ ] Sync failures/conflicts or pending review render above onboarding and generic navigation.
- [ ] First-run empty state remains clear when no actionable work exists.
- [ ] Dashboard tests cover the priority model and representative partial states.
