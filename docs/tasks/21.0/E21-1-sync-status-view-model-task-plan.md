# Task Plan — E21-1

> **Metadata**
>
> - **Date**: 2026-07-12 09:30 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-1`
> - **Review Coverage Target**: 2

---

## E21-1. Sync Status View-Model + Single Status Strip

## Objective

Consolidate the five overlapping job/sync status surfaces into one `SyncPresentation` view-model derived from `resolveEffectiveSyncHealth`, rendered as a single plain-language status strip per page. Ship the epic's shared a11y harness (Playwright keyboard-walk + live-region assertions) and a banned-jargon test covering **all** `js/admin` pages.

## Problem Statement

A first-time visitor sees up to five concurrent, mutually inconsistent status surfaces: `SyncStatusIndicator` (369 lines, 9 return branches at lines 136, 223, 244, 256, 273, 286, 299, 314, 336), `ScanActionPanel` (`Panels.tsx:25`, rendered at `ScanTabContent.tsx:94`), `JobTimeline`, page notices (`DegradedModeBanner.tsx`, mounted app-wide from `App.tsx`; `detailTruncationNotice`, `WorkbenchContext.tsx:274`), and `BulkDescribeProgress` (`MediaSelection.tsx:327`, added by WBUX-3). They leak internal topology jargon ("topology", `SyncStatusIndicator.tsx:212`; "replay", "projection", "dead-letter", "Source version", "projected instances", "Curriculum", raw UUIDs) into visitor-facing copy. Status truth is duplicated instead of derived from one source ([REF-09] mutable/derived-data drift, [DOM-03] one meaning per term per context). The repo also has **zero** keyboard-navigation and **zero** aria-live e2e tests (verified 2026-07-12), while the epic's WCAG 2.2 AA floor requires both ([A11Y-11], [A11Y-21], [A11Y-23]).

## Constraints

- **No backend contract changes** (rg-015): consume existing endpoints and `data_source` markers only.
- **Data sovereignty invariants** (WBUX-1 §5): offline rendering from local projection unchanged; this task is presentation-layer only.
- **Status enums centralized** (sr-007): `SyncPresentation` statuses defined once as `as const` objects; no scattered string comparisons.
- **Icon + color + word** for every status (sr-004, [UI-02], [A11Y-06]): design tokens only (`--acx-*`).
- **No visual re-baseline here**: snapshots re-baseline once, at E21-4. Visual diffs from consolidation are expected — update snapshots only for deleted surfaces, do not re-baseline the suite.
- **Deep-link compat**: no `?tab=`/`?overlay=` semantics change (E21-10 owns migration).

## Workflow Principles

- One derivation, many renderings: every surface consumes `SyncPresentation`; none re-derives health ([REF-09], [ARCH-02] single writer owns the view-model).
- Delete-over-flag (greenfield policy): redundant surfaces are removed, not feature-flagged.
- Plain language is a gate, not polish ([RLSE-09] plain-English expert gate): the banned-strings test enforces it mechanically.
- Undesigned states are bugs ([RLSE-04], [A11Y-24]): loading/empty/error/offline each get explicit presentation mapping.

## Terminology

- **SyncPresentation**: the single view-model object — `{ status, headline, detail, icon, tone, action? }` — derived from `resolveEffectiveSyncHealth` (`degradedModeBannerLogic.ts:10-13`) plus job/run state; the only status-truth source for admin pages.
- **Status strip**: the one per-page rendering of `SyncPresentation`; a `role="status"` live region.
- **Banned string**: an internal-vocabulary term that must never render on any `js/admin` page: topology, replay, projection, dead-letter, curation acknowledgement, Source version, projected instances, Curriculum, raw UUIDs.

## Current State Analysis

- `resolveEffectiveSyncHealth` (`js/admin/pages/workbench/degradedModeBannerLogic.ts:10-13`) already computes effective health but only feeds the degraded-mode banner (2 consumers).
- `SyncStatusIndicator.tsx` (369 lines) hand-rolls 9 presentation branches with jargon; `DashboardPage.tsx:54` consumes health separately.
- `BulkDescribeProgress` (`MediaSelection.tsx:327`) is the fifth surface, landed with WBUX-3, with its own progress vocabulary.
- `JobTimeline.tsx` and page notices render overlapping run-state messages.
- `tests/e2e/a11y/` contains axe-only specs; zero `.press()`/`toBeFocused()` and zero `aria-live`/`role="status"` assertions anywhere in `tests/e2e/`.

## Target Outcome

Each admin page renders exactly one status strip driven by `SyncPresentation`. Async status changes are announced via the strip's live region ([A11Y-21]). All five legacy surfaces either consume the view-model (kept renderers like `BulkDescribeProgress`'s progress bar) or are deleted. A vocabulary test fails CI if any banned string renders on any `js/admin` page. The shared a11y harness exists with a keyboard-walk of the workbench status flow and live-region assertions, ready for every later E21 task to extend.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`
- Epic: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (Re-baseline table, Verification section)
- Grounding: `docs/assessments/current/workbench-ui-refactor-assessment-2026-07-04.md` (WBUX-1 §5 invariants)
- Handoff/MCP: task ref `E21-1`; epic findings UXPR-01..15 are fixed — do not relitigate.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| REST `acx/v1` responses | backend | existing endpoints + `data_source` markers | none | n/a — read-only consumption | existing unit fixtures unchanged |
| Deep links `?tab=`/`?overlay=` | frontend (E21-10) | current shims | none | yes — e2e specs depend | e2e smoke suite green |

## Proposed Solution

Build `syncPresentation.ts` (pure function: health + job/run inputs → `SyncPresentation`) beside `degradedModeBannerLogic.ts`, with a status vocabulary map that owns every user-facing string. Replace `SyncStatusIndicator`'s branch forest with a thin renderer of the view-model; retarget `ScanActionPanel` status copy, `JobTimeline` run labels, page notices, and `BulkDescribeProgress` headline to the same vocabulary. Add the banned-strings render test (mount every `js/admin` page with representative fixture states, assert no banned term in rendered output). Seed `tests/e2e/a11y/` with `keyboard-walk.spec.ts` and `live-region.spec.ts`.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/workbench/syncPresentation.ts` (new) | `SyncPresentation` view-model + status vocabulary (`as const`, sr-007) |
| frontend | `js/admin/pages/workbench/SyncStatusIndicator.tsx` | thin renderer of `SyncPresentation`; delete 9-branch logic + jargon (incl. :212 topology) |
| frontend | `js/admin/pages/workbench/Panels.tsx` (`ScanActionPanel` :25) | status copy from vocabulary; remove duplicated health derivation |
| frontend | `js/admin/pages/workbench/JobTimeline.tsx` | run-state labels from vocabulary |
| frontend | `js/admin/pages/workbench/DegradedModeBanner.tsx` | banner copy from vocabulary; remains the app-wide degraded notice, driven by the same `SyncPresentation` |
| frontend | `js/admin/pages/workbench/MediaSelection.tsx` (`BulkDescribeProgress` :327) | headline/status strings from vocabulary; progress mechanics unchanged |
| frontend | `js/admin/pages/DashboardPage.tsx` (:54) | consume `SyncPresentation` for its health display |
| tests | `js/admin/__tests__/banned-vocabulary.test.tsx` (new) | render-level banned-strings sweep over all `js/admin` pages |
| tests | `js/admin/pages/workbench/__tests__/syncPresentation.test.ts` (new) | exhaustive state-matrix mapping tests ([A11Y-24] states enumerated) |
| tests | `tests/e2e/a11y/keyboard-walk.spec.ts` (new) | shared keyboard-walk harness ([A11Y-11]) |
| tests | `tests/e2e/a11y/live-region.spec.ts` (new) | `role="status"`/`aria-live` announcement assertions ([A11Y-21]) |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/pages/workbench/degradedModeBannerLogic.ts` | `resolveEffectiveSyncHealth` (:10-13) is the health input; do not fork it |
| `js/admin/pages/workbench/__tests__/degradedModeBannerLogic.test.ts` | existing coverage; extend, don't duplicate |
| `js/admin/pages/roster/PersonWorkspacePanel.tsx` | ships "Curriculum"/"Source version" copy — in banned-test scope; E21-9 owns its full translation, this task only fixes strings the vocabulary already covers |
| `tests/e2e/a11y/workbench-axe.spec.ts` | axe floor stays; new specs sit beside it |

## Verification Strategy

- Deterministic tests:
  - iteration only (non-gating — `test:agent` is `vitest run || true` and always exits 0): `npm run test:agent -- <pattern>`
  - evidence-grade (exit codes real; use these for `test_result` writes): `cd apps/prototype-wp-alt-context && npx vitest run js/admin/pages/workbench/__tests__/syncPresentation.test.ts js/admin/__tests__/banned-vocabulary.test.tsx`
  - full gate: `cd apps/prototype-wp-alt-context && npm run check`
- Runtime-parity / environment checks:
  - `npx playwright test tests/e2e/a11y` (axe + keyboard-walk + live-region)
- Manual verification:
  - keyboard-only walk of workbench scan→status flow; VoiceOver hears status transitions ([A11Y-23])

## Slice Delivery

### Slice 1: SyncPresentation view-model + vocabulary + banned-strings test

**Goal**: One derivation of status truth with a mechanically enforced plain-language vocabulary.

Changes:

- `syncPresentation.ts` view-model + vocabulary map (sr-007 `as const`; state matrix covers loading/empty/error/offline × scan/cluster/describe).
- `banned-vocabulary.test.tsx` rendering every `js/admin` page surface — enumerate from the `js/admin/pages/` directory so new pages are auto-covered: `DashboardPage`, `WorkbenchPage`, `RosterPage`, `DescriptionHistoryPage`, `RetentionPage`, `SettingsPage`, `DescribeRunApplyView` — under representative fixtures; asserts no banned string ([RLSE-09]). Test fails if a page module exists in `pages/` but is missing from the sweep.
- Unit state-matrix tests for the mapping.

Proof:

- `npx vitest run` over the two new test files exits 0; banned test demonstrably fails when a jargon string is injected ([AGT-03] make it fail before making it pass).

### Slice 2: Surface consolidation

**Goal**: All five surfaces render from `SyncPresentation`; redundant renderings deleted.

Changes:

- `SyncStatusIndicator` → thin renderer (icon+color+word per sr-004/[UI-02]); `ScanActionPanel`, `JobTimeline`, page notices, `BulkDescribeProgress`, `DashboardPage` health consume the vocabulary.
- Delete now-dead branch code and duplicated derivations.

Proof:

- `npm run check` green; banned-vocabulary test green over the consolidated surfaces; existing e2e smoke green (deep-link shims untouched).

### Slice 3: Shared a11y harness seed

**Goal**: The epic's keyboard-walk + live-region harness exists and gates this task's changed flow.

Changes:

- `keyboard-walk.spec.ts`: tab-order walk of workbench scan/status flow with `.press()`/`toBeFocused()` ([A11Y-11]); pattern documented for later tasks.
- `live-region.spec.ts`: status strip announces scan/describe transitions via `role="status"` ([A11Y-21]).

Proof:

- `npx playwright test tests/e2e/a11y` green; specs assert real announcements (not vacuous source-regex checks).

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend guidelines, testing-typescript, epic re-baseline table, WBUX-1 §5 invariants.
- [ ] Confirmed no boundary contract touched (presentation-only).

### Checklist for Slice 1: View-model + vocabulary + banned test

- [ ] `syncPresentation.ts` with `as const` status vocabulary and full state matrix
- [ ] `banned-vocabulary.test.tsx` over all `js/admin` pages; failure demonstrated with injected jargon
- [ ] Unit state-matrix tests green

### Checklist for Slice 2: Surface consolidation

- [ ] Five surfaces consume `SyncPresentation`; dead derivations deleted
- [ ] sr-004 icon+color+word on every status rendering, tokens only
- [ ] `npm run check` + e2e smoke green

### Checklist for Slice 3: A11y harness seed

- [ ] `keyboard-walk.spec.ts` + `live-region.spec.ts` green and non-vacuous
- [ ] Harness pattern reusable by E21-2/3/12 (documented in spec header comments)

## Review Readiness

- [ ] No surface left re-deriving status truth outside the view-model.
- [ ] Runtime-parity: live-region announcements verified in Playwright, not only unit render.
- [ ] Handoff decision records change, verification, and the "no re-baseline until E21-4" note.

## Success Criteria

- [ ] Exactly one status strip per admin page; status truth derived once from `resolveEffectiveSyncHealth`.
- [ ] Banned-strings test green over all `js/admin` pages and wired into `npm run check`.
- [ ] Repo's first keyboard-walk + live-region e2e specs green; axe suite still green.
- [ ] `handoff_close_check(enforce=True)` passes.
