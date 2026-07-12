# Task Plan — E21-2

> **Metadata**
>
> - **Date**: 2026-07-12 14:50 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-2`
> - **Review Coverage Target**: 2

---

## E21-2. Dashboard Cull Pass

## Objective

Remove the dashboard's dead weight so a first-time visitor sees one orientation path and one primary action per state: delete the Batch Operations panel, gate `OrientationCard` to the zero-people state, cull the `DescribePanel` hero and the dead `before_grid` branch, give Library Coverage a real CTA, and humanize Recent Activity identifiers.

## Problem Statement

The dashboard stacks competing panels from WBUX-2 §4: a `Batch Operations` panel (`DashboardPage.tsx:267-308`) duplicating Workbench entry points with raw job UUIDs ("Most recent batch job: %s", `:279`); `OrientationCard` rendered for everyone with a `localStorage` dismissal (`OrientationCard.tsx:7,15`) instead of rendering only when `identityStats.people_count === 0`; a `DescribePanel` hero (`DashboardPage.tsx:325`); a dead `before_grid` orientation branch (`DashboardPage.tsx:323`) that can never render because `buildDashboardPriorityModel.ts:83` hardcodes `after_grid`; a Library Coverage section (`DashboardPage.tsx:191`) with numbers but no action; and Recent Activity rendering raw UUIDs (`DashboardRecentActivitySection.tsx:63`). Multiple primary actions per state violate the epic's one-CTA rule; raw UUIDs violate the banned-vocabulary contract (now enforced by E21-1's sweep for pages, but UUIDs flow through data, not static strings).

## Constraints

- **No backend contract changes** (rg-015); presentation-only.
- **CTA retargeting is bounded**: Library Coverage CTA points at `#/workbench?status=missing` — the `status` query param contract is live in `hooks/useWorkbenchFilters.ts:23,50` (`parseWorkbenchMediaStatus`). Cross-surface link *model* work stays in E21-10.
- **Deep-link compat**: existing `#/workbench?tab=` links elsewhere unchanged.
- **Banned vocabulary**: no raw UUIDs in rendered dashboard output; E21-1's `banned-vocabulary.test.tsx` sweep must stay green (DashboardPage is in the registry).
- **A11y floor**: keyboard walk + live-region coverage for the changed dashboard flow extends E21-1's harness pattern (`tests/e2e/a11y/keyboard-walk.spec.ts` bounded-Tab pattern) ([A11Y-11], [A11Y-21]).
- **No visual re-baseline** (E21-4 owns it); delete-over-flag (greenfield).

## Workflow Principles

- One primary action per screen state ([LAY-01] contrast engine — one big thing; [PROD-01] outcome over output).
- Orientation is for the un-oriented: `OrientationCard` only at `people_count === 0`, replacing localStorage dismissal state ([RLSE-04] — the dismissal is undesigned state).
- Numbers without a next action are decoration: coverage stats get a CTA ([RLSE-06] the adversarial user is in a hurry).
- Dead branches are deleted, not documented ([AGT-05] scoped: `before_grid` is in-scope per the epic amendment).

## Terminology

- **Cull**: delete a panel/branch entirely, including its styles and tests.
- **Zero-people state**: `identityStats.people_count === 0` (`DashboardPage.tsx:146`).
- **Coverage CTA**: link from Library Coverage to `#/workbench?status=missing`.

## Current State Analysis

- `DashboardPage.tsx` panel registry builds `batchOperations` (`:267-308`) with three action cards duplicating Workbench/Roster nav plus raw `latestRecognitionJobId` display.
- `OrientationCard.tsx:7,15` uses `localStorage.getItem/setItem('acx_orientation_dismissed')`.
- `DashboardPage.tsx:323` renders `before_grid` branch; `buildDashboardPriorityModel.ts:30,83` types both positions but only ever returns `'after_grid'`.
- `DescribePanel` hero rendered unconditionally at `:325`.
- Library Coverage section `:191-217` shows stats with no link.
- `DashboardRecentActivitySection.tsx:63`: `{item.jobId ?? item.runId ?? item.id}` renders raw identifiers.
- E21-1 landed `SYNC_VOCABULARY` and `DashboardSyncHealthSection` consuming it — do not regress.

## Target Outcome

Dashboard = orientation (zero-people only) → coverage numbers with a "Fix missing descriptions" CTA → sync health (E21-1 strip) → recent activity in human terms ("Scan finished · 24 images · 2 hours ago" shape from available fields, no raw UUIDs). Batch Operations panel, DescribePanel hero, dead branch, and localStorage dismissal are gone.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Epic: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (Re-baseline row E21-2)
- Grounding: WBUX-2 §4 (`docs/assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md`)
- Handoff/MCP: task ref `E21-2`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `#/workbench?status=` filter param | frontend (`useWorkbenchFilters.ts`) | `parseWorkbenchMediaStatus(searchParams.get('status'))` | none — new consumer only | yes — existing filter tests stay green | `hooks/__tests__/useWorkbenchFilters.test.tsx` |
| REST `acx/v1` dashboard stats | backend | existing | none | n/a | existing fixtures |

## Proposed Solution

Delete the `batchOperations` entry from the panel registry and its `gridSectionOrder` references in `buildDashboardPriorityModel.ts`; simplify the model to a single `after_grid` orientation (drop the `before_grid` type member and the `:323` branch). Convert `OrientationCard` gating from localStorage-dismissal to `people_count === 0` prop passed from `DashboardPage` (delete the localStorage read/write). Remove the `DescribePanel` hero render from the dashboard only (the component is shared — `MediaSelection.tsx` imports it). Add the Coverage CTA link. Replace `DashboardRecentActivitySection` identifier rendering with a human summary derived from existing item fields; keep an accessible details affordance if an ID is genuinely needed (none expected).

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/DashboardPage.tsx` | delete `batchOperations` panel (:267-308) + `before_grid` branch (:323) + `DescribePanel` render (:325); pass `peopleCount` to `OrientationCard`; Coverage CTA in Library Coverage section (:191-217) |
| frontend | `js/admin/pages/dashboard/buildDashboardPriorityModel.ts` | drop `before_grid` from `orientationPosition` type (:30) and `batchOperations` from `gridSectionOrder`; model returns only `after_grid` |
| frontend | `js/admin/pages/dashboard/OrientationCard.tsx` | remove localStorage (:7,15); render decided by `peopleCount === 0` prop |
| frontend | `js/admin/pages/dashboard/DashboardRecentActivitySection.tsx` | humanize activity rows (:63); no raw UUIDs |
| frontend | `js/admin/pages/dashboard/DescribePanel.tsx` | component STAYS — `MediaSelection.tsx` (workbench) also imports it; remove only the dashboard render at `DashboardPage.tsx:325` |
| tests | `js/admin/pages/__tests__/DashboardPage.test.tsx` + dashboard component tests | update: batch panel absent, orientation gating matrix (0 vs >0 people), CTA href, no-UUID assertion |
| tests | `tests/e2e/a11y/keyboard-walk.spec.ts` or new `dashboard-keyboard-walk.spec.ts` | bounded-Tab walk: dashboard load → Coverage CTA reachable |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/hooks/useWorkbenchFilters.ts` (:23,:50) | `status` param contract the CTA targets; do not modify |
| `js/admin/pages/dashboard/DashboardSyncHealthSection.tsx` | E21-1 vocabulary consumer; keep intact |
| `js/admin/__tests__/banned-vocabulary.test.tsx` | sweep must stay green; DashboardPage in registry |

## Verification Strategy

- Deterministic tests (evidence-grade; `test:agent` is iteration-only):
  - `cd apps/prototype-wp-alt-context && node_modules/.bin/vitest run js/admin/pages/dashboard js/admin/pages/__tests__ js/admin/__tests__`
  - `npm run typecheck`
- Runtime-parity: `npx playwright test tests/e2e/a11y` (axe + walks)
- Manual: fresh install shows OrientationCard; with people it disappears; Coverage CTA lands on workbench filtered to missing.

## Slice Delivery

### Slice 1: Cull + gating

**Goal**: Batch Ops panel, DescribePanel hero, dead branch, and localStorage dismissal removed; OrientationCard gated by people count.

Changes:

- Deletions in `DashboardPage.tsx` + `buildDashboardPriorityModel.ts` + `OrientationCard.tsx` as tabled.
- Test matrix: 0-people (card shows) vs >0 (card absent); batch panel absent; priority model has no `before_grid`/`batchOperations` members (type-level + runtime).

Proof:

- `node_modules/.bin/vitest run js/admin/pages/dashboard js/admin/pages/__tests__` exits 0, including a new test that fails against the old always-rendered OrientationCard behavior ([AGT-03]).

### Slice 2: Coverage CTA + humanized activity + a11y walk

**Goal**: Coverage numbers actionable; activity readable; dashboard keyboard path proven.

Changes:

- CTA `#/workbench?status=missing` in Library Coverage; humanized Recent Activity rendering (no raw IDs); dashboard keyboard-walk spec (bounded-Tab to CTA).

Proof:

- Vitest green incl. CTA href + no-UUID-pattern assertions; `npx playwright test tests/e2e/a11y` green.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded frontend guidelines, epic re-baseline row, WBUX-2 §4.
- [x] Confirmed `status=missing` consumer-only change on the filter contract.

### Checklist for Slice 1: Cull + gating

- [x] Batch Ops panel + `before_grid` + DescribePanel hero + localStorage dismissal deleted
- [x] OrientationCard people-count gating with failing-first test
- [x] Priority model type narrowed; vitest scope green

### Checklist for Slice 2: CTA + activity + a11y

- [x] Coverage CTA lands on `#/workbench?status=missing`
- [x] Recent Activity renders no raw UUIDs
- [x] Dashboard keyboard-walk spec green (bounded-Tab pattern)

## Review Readiness

- [x] No deleted panel leaves orphaned styles/components/tests.
- [x] Banned-vocabulary sweep green; sync-health section untouched.
- [x] Handoff decision records change + verification.

## Success Criteria

- [x] One primary action per dashboard state; zero raw UUIDs rendered.
- [x] OrientationCard appears iff `people_count === 0`.
- [x] `handoff_close_check(enforce=True)` passes.
