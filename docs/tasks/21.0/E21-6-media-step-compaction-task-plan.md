# Task Plan

> **Metadata**
>
> - **Date**: 2026-07-04
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-6`
> - **Review Coverage Target**: 2
>
> **Review coverage note:** Do not embed mutable review counts, finding totals, or run histories in this file. Those are volatile; their canonical home is the handoff DB. Use `list_review_runs(task_ref=...)` to query live coverage state.

---

## E21-6. Media Step Compaction

## Objective

The Workbench media step becomes compact and self-contained: the "Analyze n selected" CTA lives with the media table instead of ~4 panels above it, the table collapses to a summary bar while review findings are pending, only one paginator renders, and the table honors a `#/workbench?status=missing` deep link so the E21-2 dashboard Library Coverage CTA can land users on a pre-filtered table. Implements WBUX-1 S4 / roadmap P3-B.

## Problem Statement

On the Scan tab, `ScanTabContent` renders `ScanActionPanel` (which owns the "Analyze selected media" button) first and `MediaSelection` (where selection actually happens) last, with `JobTimeline`, `WorkbenchFindingsPanel`, `NoMediaPanel`, and the `SuggestionReviewPanel` anchor block between them (`ScanTabContent.tsx:89-146`). Users select at the bottom and must scroll to the top to act — WBUX-1 §2.1 "CTA is separated from its object." `MediaSelection` renders `MediaSelectionPagination` twice (top `MediaSelection.tsx:66-73`, bottom `MediaSelection.tsx:104-111`), duplicating chrome. During review the full 10–100-row table keeps competing with the review queue for attention (WBUX-1 §2.1 "everything renders at once"). Finally, `useWorkbenchFilters.ts:19` already reads a `status` URL param but with an unvalidated `as WorkbenchMediaStatus` cast, so the deep link E21-2 needs is untested and unhardened against junk values.

## Constraints

- **Dependencies: E21-1 + E21-4 must land first.** E21-1 consolidates job/sync status surfaces into one view-model; this task must not rebuild or duplicate job-status UI — `ScanActionPanel`'s progress/stall/cancel rendering stays whatever E21-1 left it as; E21-6 only relocates the analyze CTA out of it. E21-4 lands the design-token system and re-baselines visual snapshots once; the new summary-bar/footer styles must consume `--acx-*` tokens (sr-004, sr-002 of the token sweep) and land after that re-baseline so visual diffs stay reviewable.
- **rg-003 (zero-state reachability)**: the analyze CTA must remain visible and disabled-with-reason at zero selection — never hidden. The existing zero-state copy pattern (`Panels.tsx:44-45`) carries over to the new location.
- **One primary CTA per state** (WBUX-1 §2.1 action pyramid): while findings are pending, the review queue owns the primary CTA; the media region is collapsed and its analyze CTA is not rendered as primary.
- **Data sovereignty unchanged**: the media table is fully local WP data (WP REST `acx/v1/workbench/media*`; WBUX-1 §5); offline behavior of the table, filter, paginator, and deep link must not change. Collapse must fail open: any findings loading/error/unavailable state keeps the table expanded.
- **No backend contract change** (rg-015): `src/api/class-api.php` already accepts and validates the `status` param (`class-api.php:200`, `:303`); the REST surface is consumed as-is.
- **sr-005**: the `status` URL param is boundary data — validate it explicitly against the allowed set; no unchecked casts.
- Selection state must survive collapse/expand (it lives in `useMediaSelectionState` via context, not in the table DOM).

## Workflow Principles

- Relocate, don't rebuild: move the existing CTA and delete the duplicate paginator; do not redesign `ScanActionPanel`'s remaining status role (E21-1 owns status presentation).
- Behavior-preserving except the four scoped changes; every slice ships its test updates in the same commit.
- Keep components under the 300-line map limit — `MediaSelection.tsx` is at 289 lines, so net-new UI (summary bar) goes in a new file rather than growing it.
- Centralize domain values (sr-007): the `'all' | 'missing'` status set becomes one `as const` source instead of scattered string literals.

## Terminology

- **Media region**: the `MediaSelection` block — toolbar (search + status filter), table, paginator, and (after this task) the analyze CTA footer.
- **Summary bar**: the one-line collapsed rendering of the media region ("N items · M selected" + expand control) shown while review is active.
- **Review-active**: findings pending — `useWorkbenchFindings().hasFindings === true` (`useWorkbenchFindings.ts:220`, `counts.total > 0`), computed from local-projection-backed suggestion queries.
- **Deep link**: `#/workbench?status=missing` — HashRouter URL (`App.tsx:31`) whose search params `useWorkbenchFilters` reads to pre-filter the table.

## Current State Analysis

- **Works**: selection, search (`s` param), pagination (`p`/`perPage` params), and status filtering already flow through URL search params via `useWorkbenchFilters` → `useWorkbenchMedia` → `fetchWorkbenchMedia` (`workbenchMediaApi.ts:79-106` sets `status` on the request); the PHP route validates `status` server-side. React Query keys include `status` (`useWorkbenchMedia.ts:34`), so filter changes refetch correctly.
- **Broken/drifting**: CTA sits in `ScanActionPanel` at the top of `ScanTabContent` while its object (the table) renders last; two identical `MediaSelectionPagination` instances render (asserted by `WorkbenchPage.test.tsx:517-521`, which expects exactly 2 — that test encodes the defect); the table never yields visual priority to the review queue; `statusFilter` is an unvalidated cast, so `?status=garbage` flows into the Radix `Select` value and the REST request untested.
- **Misleading surfaces**: `Panels.test.tsx:23-41` tests the analyze button inside `ScanActionPanel` — those assertions must move with the CTA, not be deleted. `WorkbenchPage.test.tsx:517` ("renders pagination controls above and below the media table") asserts the duplication as if intended.

## Target Outcome

The media region matches the WBUX-1 §3 MEDIA sketch: expanded during select (step ①) with toolbar on top and a single footer row — `‹ 1 / 12 › · per-page selector · [ Analyze 24 selected ]` — where the CTA sits beside the paginator it acts after. When findings arrive (review-active), the region collapses to a summary bar ("142 items · 24 selected — Show table"), keeping the review queue as the sole primary surface; expanding is one click and selection is intact. Exactly one paginator exists. Navigating to `#/workbench?status=missing` (from the E21-2 dashboard CTA or any link) opens the Workbench with the status filter set to "Missing alt text" and the table pre-filtered; invalid `status` values fall back to `all`.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, sr-004/sr-005/sr-007 and rg-003/rg-015 in `docs/workbay/constitution.md`
- Grounding: `docs/assessments/current/workbench-ui-refactor-assessment-2026-07-04.md` (§1.1, §2.1, §3 MEDIA region, §5, §6 S4), `docs/roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md` (P3-B, §5 dependency graph)
- Post-dependency re-verification: read the landed E21-1 plan (`docs/tasks/21.0/E21-1-sync-status-view-model-task-plan.md`) and E21-4 plan before Slice 1 — if E21-1 replaced `ScanActionPanel` or introduced a pipeline step model, relocate the CTA from whatever component now owns it and prefer the pipeline model's review-active signal over raw `hasFindings` (see Slice 2)
- Handoff/MCP state: task ref `E21-6`; check `review_findings(review={"operation":"list","status":"open","task_ref":"E21-6"})` before starting

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP REST `acx/v1/workbench/media` | PHP plugin (`src/api/class-api.php:77`) | `status` enum param already accepted (`:200`, `:303`) | none | n/a — consumed as-is | existing PHP tests; `useWorkbenchMedia.test.tsx` |
| Workbench URL params | Frontend (`useWorkbenchFilters.ts`) | `s`, `p`, `perPage`, `status` read from hash-route search params | `status` becomes a validated, documented deep-link contract consumed by E21-2 | yes — E21-2's dashboard CTA targets `#/workbench?status=missing`; existing `?tab=`/`?panel=` params untouched | new `useWorkbenchFilters.test.tsx` cases + WorkbenchPage deep-link test |

## Proposed Solution

Three co-located moves, no new data flow. (1) Extract the analyze CTA (button + zero-state reason + scanning label) from `ScanActionPanel` into a new `MediaAnalyzeCta` component rendered in a new footer row of `MediaSelection`, wired to the same context fields `ScanTabContent` already destructures (`selectedMedia`, `scan`, `isScanRunning`); delete the top paginator render so the footer holds the single paginator + CTA. (2) Add a `collapsed` prop to `MediaSelection`; `ScanTabContent` computes review-active from `useWorkbenchFindings()` (React Query dedupes the underlying queries already issued by `WorkbenchFindingsPanel`) combined with a local "user expanded" override, and renders a new `MediaSummaryBar` instead of the table when collapsed. (3) Harden the `status` param read in `useWorkbenchFilters` behind a centralized `WORKBENCH_MEDIA_STATUSES` const in `workbenchMediaApi.ts`, and add deep-link tests documenting the `#/workbench?status=missing` contract for E21-2.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSelection.tsx` | Delete top `MediaSelectionPagination` render (lines 66-73); add footer row (single paginator + `MediaAnalyzeCta`); accept `collapsed`/`onExpand` props and render `MediaSummaryBar` when collapsed |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAnalyzeCta.tsx` (new) | CTA extracted from `ScanActionPanel` — primary button, `disabled={isScanning \|\| selectedCount === 0}`, zero-state reason copy, scanning/clustering label logic (`Panels.tsx:44-62` semantics preserved) |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaSummaryBar.tsx` (new) | Collapsed one-line summary: total items (`mediaQuery.data.total`), selected count, active filter, "Show media table" expand button |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx` | `ScanActionPanel` loses the analyze button and `selectedCount`/`onScanFaces` props; keeps run-status/cancel/stall rendering (post-E21-1 shape) |
| frontend | `apps/prototype-wp-alt-context/js/admin/pages/workbench/ScanTabContent.tsx` | Move `handleScanFaces` wiring to `MediaSelection`; compute `collapsed` from `useWorkbenchFindings().hasFindings` + expand override; drop relocated `ScanActionPanel` props |
| frontend | `apps/prototype-wp-alt-context/js/admin/api/workbenchMediaApi.ts` | Add `WORKBENCH_MEDIA_STATUSES = ['all','missing'] as const`; derive `WorkbenchMediaStatus` from it (sr-007) |
| frontend | `apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchFilters.ts` | Replace the line-19 cast with explicit validation against `WORKBENCH_MEDIA_STATUSES`, fallback `'all'` (sr-005) |
| styles | `apps/prototype-wp-alt-context/js/admin/styles/components/_media-selection.scss` | Footer + summary-bar styles using `--acx-space-*`/`--acx-color-*`/`--acx-shadow-*`/`--acx-radius-*` tokens only (sr-004; E21-4 ramp) |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/WorkbenchPage.test.tsx` | Paginator assertion 2→1 (lines 517-521); analyze-CTA-inside-media-region assertions; collapse/expand behavior; deep-link pre-filter test |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/Panels.test.tsx` | Remove analyze-button cases (lines 23-41, 119-124); keep status/cancel/stall coverage |
| tests | `apps/prototype-wp-alt-context/js/admin/pages/workbench/__tests__/MediaAnalyzeCta.test.tsx` (new) | Ports the removed Panels CTA cases: zero-state disabled+reason, enabled at n>0, scanning/clustering labels |
| tests | `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx` | Cases: `?status=missing` → `'missing'`; `?status=garbage` → `'all'`; absent → `'all'` |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | Context already exposes everything needed (`selectedMedia`, `scan`, `isScanRunning`, `statusFilter`, `mediaQuery`, pagination setters at lines 69-108); no new fields required — do not widen the ~70-field context (E21-11 shrinks it) |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` | Review-active source: `hasFindings` (line 220); `isLoading`/`isError`/`isUnavailable` gate the fail-open rule |
| `apps/prototype-wp-alt-context/js/admin/hooks/useMediaSelectionState.ts` | Selection store — untouched; proves selection survives collapse |
| `apps/prototype-wp-alt-context/js/admin/hooks/useWorkbenchMedia.ts` | Query already keys on `status` (line 34); untouched |
| `apps/prototype-wp-alt-context/js/admin/pages/dashboard/GuidanceCard.tsx` | Existing `#/workbench?tab=scan` links (line 65) show the deep-link shape E21-2 will extend with `status=missing`; not edited here |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | Server-side `status` validation (lines 200, 303); read-only reference |
| `apps/prototype-wp-alt-context/tests/e2e/visual/workbench-visual.spec.ts` | Visual baseline — expect scoped diffs post-E21-4 re-baseline |
| `apps/prototype-wp-alt-context/tests/e2e/a11y/workbench-axe.spec.ts` | Must stay green: footer/summary bar need proper roles and button names |

## Verification Strategy

All commands run from `apps/prototype-wp-alt-context/`.

- Deterministic tests:
  - `npm run test -- js/admin/pages/workbench js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx`
  - `npm run check` (lint + typecheck + arch + full vitest) before each slice close
- Runtime-parity / environment checks:
  - `npx playwright test tests/e2e/a11y/workbench-axe.spec.ts tests/e2e/visual/workbench-visual.spec.ts` against the local WP site
- Contract/fixture verification:
  - Assert exactly one `role="navigation"` named "Media pagination" renders (inverts `WorkbenchPage.test.tsx:520`)
  - Deep-link test renders the Workbench route with `?status=missing` and asserts the media query fires with `status: 'missing'` (query-key fixture pattern already used at `WorkbenchPage.integration.test.tsx:274`)
- Manual verification:
  - LocalWP: select 2 items → CTA in table footer enables with count; run analyze → findings arrive → table collapses to summary bar showing intact selection; expand → selection preserved; open `…#/workbench?status=missing` → filter select shows "Missing alt text" and only missing-alt rows render; airplane-mode reload → table, filter, paginator all still work (local WP data)

## Slice Delivery

### Slice 1: CTA co-location + single paginator

**Goal**: The analyze CTA renders inside the media region footer next to the only paginator; `ScanActionPanel` no longer owns it.

Changes:

- Create `MediaAnalyzeCta.tsx` with the button semantics lifted verbatim from `Panels.tsx:44-62` (zero-state reason copy, `disabled={isScanning || selectedCount === 0}`, scanning/clustering labels via the `isClusteringActive` check); reads `selectedMedia`, `scan`, `isScanRunning`, `clusterProgress`/`scanProgress` phase from `useWorkbenchContext`
- In `MediaSelection.tsx`: delete the top `MediaSelectionPagination` (lines 66-73); wrap the remaining bottom paginator and `MediaAnalyzeCta` in a `.acx-media-selection__footer` row; style with existing tokens in `_media-selection.scss`
- In `Panels.tsx`: remove the analyze `<button>` and the `selectedCount`/`onScanFaces` props from `ScanActionPanelProps`; in `ScanTabContent.tsx` drop the corresponding prop wiring (the `handleScanFaces` logic moves into `MediaAnalyzeCta`)
- Tests: update `WorkbenchPage.test.tsx` (paginator count 1, CTA queried inside the media region, zero-state disabled-with-reason — rg-003); move `Panels.test.tsx` CTA cases into new `MediaAnalyzeCta.test.tsx`

Proof:

- `npm run test -- js/admin/pages/workbench` green with the inverted single-paginator assertion and relocated CTA cases; `npm run check` green

### Slice 2: Review-active collapse to summary bar

**Goal**: While findings are pending the media region renders as a one-line summary bar; expanding restores the full table with selection intact.

Changes:

- Create `MediaSummaryBar.tsx`: renders `mediaQuery.data.total` items, selected count from `selectedMedia.length`, the active status filter label, and a "Show media table" button (`aria-expanded` wired)
- `ScanTabContent.tsx`: call `useWorkbenchFindings()` (queries dedupe with `WorkbenchFindingsPanel`'s existing calls); `collapsed = hasFindings && !userExpanded && !isLoading && !isError && !isUnavailable` (fail-open per Constraints) — a local `useState` holds the `userExpanded` override, reset to `false` when `hasFindings` transitions false→true; if the landed E21-1/E21-3 work exposes a pipeline step model, consume its review-active signal instead and record the substitution in the slice decision
- `MediaSelection.tsx`: accept `collapsed`/`onExpand`; when collapsed render only `MediaSummaryBar` (toolbar, table, footer unmounted — selection state is context-held so it survives)
- Tests: `WorkbenchPage.test.tsx` cases — findings present → summary bar visible + table absent; expand click → table + prior selection restored; findings error/unavailable → table stays expanded

Proof:

- `npm run test -- js/admin/pages/workbench` green including fail-open and selection-persistence cases; manual LocalWP collapse/expand walkthrough recorded in the slice decision

### Slice 3: `status=missing` deep-link contract

**Goal**: `#/workbench?status=missing` deterministically pre-filters the table, invalid values fall back to `all`, and the contract is test-documented for E21-2.

Changes:

- `workbenchMediaApi.ts`: add `export const WORKBENCH_MEDIA_STATUSES = ['all', 'missing'] as const;` and re-derive `WorkbenchMediaStatus` from it (line 49) — sr-007 single source
- `useWorkbenchFilters.ts`: replace line 19's cast with a validated parse (`WORKBENCH_MEDIA_STATUSES.includes(raw)` → raw, else `'all'`) — sr-005
- Tests: `useWorkbenchFilters.test.tsx` param-validation cases; `WorkbenchPage.test.tsx` deep-link render test asserting the media query key carries `status: 'missing'` and the filter select displays "Missing alt text"
- E2e: extend `tests/e2e/evidence/workbench-evidence.spec.ts` with a `#/workbench?status=missing` navigation asserting the pre-filtered table (keeps the contract live for E21-2's CTA)

Proof:

- `npm run test -- js/admin/hooks/__tests__/useWorkbenchFilters.test.tsx js/admin/pages/workbench` green; e2e evidence spec green against LocalWP; `npm run check` green

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried live via `review_findings(review={"operation":"list","status":"open","task_ref":"E21-6"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded WBUX-1 §2.1/§3/§5/S4, roadmap P3-B, frontend guidelines, and open E21-6 handoff state before editing
- [ ] Confirmed E21-1 and E21-4 are merged; re-verified `ScanActionPanel`/status surfaces against their landed shape and noted any anchor drift in the first slice decision
- [ ] Confirmed no WP REST contract change is needed (`class-api.php:200,:303` already validates `status`)

### Checklist for Slice 1: CTA co-location + single paginator

- [ ] `MediaAnalyzeCta.tsx` created with zero-state reason, disabled logic, and scanning/clustering labels preserved from `Panels.tsx:44-62`
- [ ] Top paginator render deleted from `MediaSelection.tsx`; footer row (paginator + CTA) added with token-only styles
- [ ] `ScanActionPanel` props pruned (`selectedCount`, `onScanFaces`) and `ScanTabContent` wiring moved
- [ ] `WorkbenchPage.test.tsx` asserts one paginator + CTA in media region + rg-003 zero-state; `Panels.test.tsx` CTA cases ported to `MediaAnalyzeCta.test.tsx`
- [ ] `npm run check` green; slice decision recorded via `close_slice`

### Checklist for Slice 2: Review-active collapse

- [ ] `MediaSummaryBar.tsx` created (total, selected count, filter label, expand button with `aria-expanded`)
- [ ] `ScanTabContent` computes fail-open `collapsed` from `useWorkbenchFindings` with user-expand override (or landed pipeline model, noted in decision)
- [ ] `MediaSelection` renders summary bar when collapsed; selection survives collapse/expand (test-proven)
- [ ] Findings loading/error/unavailable keep the table expanded (test-proven)
- [ ] `npm run check` green; manual collapse/expand walkthrough noted in slice decision

### Checklist for Slice 3: Deep-link contract

- [ ] `WORKBENCH_MEDIA_STATUSES` const added and `WorkbenchMediaStatus` derived from it
- [ ] `useWorkbenchFilters` validates `status` explicitly with `'all'` fallback
- [ ] Unit cases for valid/invalid/absent `status` params; page-level deep-link test asserts pre-filtered query + select label
- [ ] `workbench-evidence.spec.ts` exercises `#/workbench?status=missing` end-to-end
- [ ] `npm run check` green; slice decision recorded

## Review Readiness

- [ ] No boundary-touching change lacks matching test evidence (URL-param contract tests + unchanged REST assertions)
- [ ] Runtime-parity covered: a11y + visual e2e specs green post-change; offline manual check performed (media region fully functional without the recognition service)
- [ ] Handoff decisions record CTA relocation, collapse driver choice (hasFindings vs pipeline model), and the documented deep-link contract for E21-2

## Success Criteria

- [ ] "Analyze n selected" renders inside the media region footer; selecting rows and launching a scan requires zero vertical round-trips (WBUX-1 §2.1 fixed)
- [ ] Exactly one "Media pagination" navigation landmark exists on the Scan tab
- [ ] With findings pending, the media table is a summary bar and the review queue is the only primary surface; expanding restores table + selection
- [ ] `#/workbench?status=missing` opens the Workbench pre-filtered to missing-alt media; `?status=<junk>` falls back to `all`
- [ ] Offline (breaker open / network down), the media region — table, filter, paginator, deep link — behaves identically to online
