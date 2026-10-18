# Task Plan — E21-3

> **Metadata**
>
> - **Date**: 2026-07-12 14:55 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-3`
> - **Review Coverage Target**: 2

---

## E21-3. Confirm-Tab Removal + Advanced Drawer

## Objective

Retire the Workbench "Confirm & Publish" tab as a first-class step and move its contents (`ConfirmPanel`, `RecentJobsPanel`, clustering help card) into an "Advanced: jobs & recovery" drawer, so the Workbench presents one linear scan→review flow. `?tab=confirm` deep links keep working via a redirect shim.

## Problem Statement

`WorkbenchPage.tsx` defines a two-tab flow (`TAB_IDS.scan` at `:21`, `TAB_IDS.confirm` at `:30` titled "Confirm & Publish" `:32`, rendering `ConfirmTabContent` at `:150`). The confirm tab hosts job history and clustering controls (`ConfirmTabContent.tsx`: help card + `ConfirmPanel` from `Panels.tsx:170` + `RecentJobsPanel` from `Panels.tsx:236`) that read as a mandatory second step, but WBUX-1 established they are recovery/advanced surfaces — a first-time visitor should never need them. Tab routing runs through `useTabParam('tab', TAB_IDS.scan, ...)` (`WorkbenchPage.tsx:128`), and both internal links (`DashboardPage.tsx`, `GuidanceCard.tsx`, `DashboardRecentActivitySection.tsx`) and unit tests reference `tab=confirm`; E21-1's `keyboard-walk.spec.ts` asserts the "Confirm & Publish" tab by name.

## Constraints

- **Deep-link compat (epic hard constraint)**: `#/workbench?tab=confirm` (and `?overlay=` generally) must keep resolving — shim redirects into the drawer-open state until E21-10 migrates specs.
- **No backend contract changes** (rg-015).
- **In-repo `tab=confirm` producers must be retargeted in this slice**: `DashboardPage.tsx`, `GuidanceCard.tsx`, `DashboardRecentActivitySection.tsx` (verified consumers) — coordinate: if E21-2 merged first, re-verify these sites, some may be culled already.
- **A11y**: drawer must be a real disclosure — trigger reachable by keyboard, focus moves into drawer on open, Esc closes and restores focus ([A11Y-11], [A11Y-13] focus not obscured); drawer state announced ([A11Y-21]). E21-1's `keyboard-walk.spec.ts` MUST be updated in the same slice (it names the Confirm tab).
- **Banned vocabulary**: drawer copy uses `SYNC_VOCABULARY`/plain language; sweep stays green.
- **No visual re-baseline** (E21-4).

## Workflow Principles

- The primary flow shows only the primary path; recovery lives behind an explicit "Advanced" affordance ([LAY-06], [RLSE-06]).
- Shims are temporary and owned: redirect logic carries a comment pointing at E21-10 as the removal owner.
- Delete-over-flag: the confirm tab entry is removed from `TAB_IDS`/tablist, not hidden.

## Terminology

- **Advanced drawer**: a disclosure region titled "Advanced: jobs & recovery" on the Workbench page hosting the former confirm-tab contents.
- **Shim**: `?tab=confirm` → scan tab + drawer open (URL normalized), preserving old links.

## Current State Analysis

- `WorkbenchPage.tsx:21-35` defines the two tabs; `:128` `useTabParam('tab', TAB_IDS.scan, [...])`; `:143-150` renders confirm tab + `ConfirmTabContent`.
- `ConfirmTabContent.tsx` pulls `useWorkbenchContext` fields (isPrimary, latestJobId, jobHistory, jobStatuses, historySource, handlers) and renders help card + `ConfirmPanel` + `RecentJobsPanel`.
- Internal producers of `tab=confirm`: `DashboardPage.tsx`, `GuidanceCard.tsx`, `DashboardRecentActivitySection.tsx`; tests `WorkbenchPage.test.tsx`, `GuidanceCard.test.tsx`, `DashboardPage.test.tsx`.
- `tests/e2e/a11y/keyboard-walk.spec.ts` + `live-region.spec.ts` reference the Confirm tab / `tab=confirm`.

## Target Outcome

Workbench shows the scan/review flow with no Confirm tab. Below/beside it, an "Advanced: jobs & recovery" disclosure opens a drawer with the former contents. Old `?tab=confirm` URLs land with the drawer open. Keyboard: Tab reaches the disclosure; open moves focus in; Esc closes and restores. In-repo links point at the new state; e2e a11y specs updated to the drawer contract.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Epic: re-baseline row E21-3; WBUX-1 grounding.
- Handoff/MCP: task ref `E21-3`. E21-1 vocabulary + a11y harness are on main — extend, don't fork.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `#/workbench?tab=` deep links | frontend | `useTabParam('tab', ...)` two values | `confirm` becomes shim → scan+drawer | yes — e2e/e21-10 | shim unit test + updated e2e |
| Drawer disclosure semantics | frontend | n/a (new) | ARIA disclosure or dialog pattern with focus contract | n/a | a11y specs |

## Proposed Solution

Add `AdvancedDrawer` (workbench component) hosting `ConfirmTabContent`'s children unchanged (help card content may move to the drawer header copy). Remove the confirm entry from the tab registry and tablist; keep `TAB_IDS.confirm` as a shim constant consumed only by the URL-normalization effect: when `tab=confirm` is present, replace URL param with scan + `advanced=open` (or equivalent state) and open the drawer. Retarget the three dashboard producers to `#/workbench?advanced=open` (or drop, coordinating with E21-2's culls). Update unit + e2e specs to the drawer contract.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/WorkbenchPage.tsx` | remove confirm tab from registry/tablist (:21-35, :143-150); mount `AdvancedDrawer`; `?tab=confirm` shim in the `useTabParam` consumer (:128 area) |
| frontend | `js/admin/pages/workbench/AdvancedDrawer.tsx` (new) | disclosure/drawer with focus management (open→focus in, Esc→close+restore), `aria-expanded`, announced state |
| frontend | `js/admin/pages/workbench/ConfirmTabContent.tsx` | becomes drawer body (or inlined); no context-field changes |
| frontend | `js/admin/pages/DashboardPage.tsx`, `js/admin/pages/dashboard/GuidanceCard.tsx`, `js/admin/pages/dashboard/DashboardRecentActivitySection.tsx` | retarget `tab=confirm` links (re-verify against merged E21-2 first) |
| tests | `js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` + dashboard tests | tab absent; shim redirect test; drawer open/close + focus tests |
| tests | `tests/e2e/a11y/keyboard-walk.spec.ts` | replace Confirm-tab assertions with drawer disclosure walk (bounded-Tab pattern) |
| tests | `tests/e2e/a11y/live-region.spec.ts` | update `tab=confirm` reference if present |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/pages/workbench/Panels.tsx` (:170 `ConfirmPanel`, :236 `RecentJobsPanel`) | move unchanged into drawer body |
| `js/admin/pages/workbench/WorkbenchContext.tsx` | context fields unchanged (E21-11 owns decomposition) |
| `js/admin/__tests__/banned-vocabulary.test.tsx` | sweep must stay green with drawer mounted/mocked consistently |

## Verification Strategy

- Deterministic (evidence-grade): `cd apps/prototype-wp-alt-context && node_modules/.bin/vitest run js/admin/pages/workbench js/admin/pages/__tests__ js/admin/pages/dashboard js/admin/__tests__` ; `npm run typecheck`
- Runtime-parity: `npx playwright test tests/e2e/a11y`
- Manual: old bookmark `#/workbench?tab=confirm` opens scan view with drawer open; Esc closes and focus returns to trigger.

## Slice Delivery

### Slice 1: Drawer + tab removal + shim

**Goal**: Confirm tab gone; drawer hosts contents; old links land correctly.

Changes:

- `AdvancedDrawer` with focus contract; tab registry/tablist edits; `tab=confirm` shim; unit tests incl. failing-first test on old two-tab behavior and a shim redirect test.

Proof:

- Scoped vitest exits 0; shim test demonstrates `tab=confirm` → drawer-open state.

### Slice 2: Producer retargeting + a11y spec migration

**Goal**: No in-repo link mints `tab=confirm`; a11y specs assert the drawer contract.

Changes:

- Retarget dashboard producers (post-E21-2 verify); update `keyboard-walk.spec.ts` (drawer walk: bounded-Tab to trigger → Enter opens → focus inside → Esc restores) and `live-region.spec.ts` reference.

Proof:

- `grep -rn "tab=confirm" js/` returns only the shim; vitest + `npx playwright test tests/e2e/a11y` green.

## Consolidated Checklist

## Context and Ownership

- [x] Loaded frontend guidelines, epic row, WBUX-1 grounding; re-verified dashboard producer sites against current main.
- [x] Shim ownership comment points at E21-10.

### Checklist for Slice 1: Drawer + removal + shim

- [x] Confirm tab removed; AdvancedDrawer with full focus contract
- [x] `?tab=confirm` shim lands drawer-open; failing-first tests
- [x] Scoped vitest green

### Checklist for Slice 2: Producers + specs

- [x] No non-shim `tab=confirm` producers left in `js/`
- [x] keyboard-walk + live-region specs migrated to drawer contract
- [x] e2e a11y suite green

## Review Readiness

- [x] Drawer passes keyboard-only open/close/restore; state announced.
- [x] Banned-vocabulary sweep green.
- [x] Handoff decision records change + verification + shim ownership.

## Success Criteria

- [x] Workbench has one visible flow; advanced surfaces behind the drawer.
- [x] Old `tab=confirm` links functional via shim.
- [x] `handoff_close_check(enforce=True)` passes.
