# Task Plan — WBTRUST-5

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-5
> **Target Branch:** feature/wbtrust-5
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 2
> **Review Coverage Target:** frontend layout, focus and copy; browser pass required (planner had none)
> **Depends on:** none (Wave A). Edits `MediaSelection.tsx`, `ActivityStatusStrip.tsx`, `AdvancedDrawer.tsx`, `WorkbenchPage.tsx` — sole Wave A owner of strip interactivity/layout; WBTRUST-4 owns cooldown state/data only. Later integration consumes both final outputs before adding cooldown rendering.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R6, R8, R12, root causes 9–10), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A8–A10, B6, C6, D2), [workbench-2pane map](../../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json) (zones `z-lib-actions`, `z-lib-table`), [gpu-operator-control map](../../../apps/prototype-wp-alt-context/docs/ux-maps/gpu-operator-control.uxmap.json), [describe-gpu-tier map](../../../apps/prototype-wp-alt-context/docs/ux-maps/describe-gpu-tier.uxmap.json), E23 epic `docs/epics/v0.5.0/gpu-operator-control-and-named-captions-epic.md`; semantic prior art: ISSUEDAG-1 decisions 11085 and 11113 (no blanket new GPU control; cost/ETA copy must be configured and provenance-backed; one Settings link only), [cpu-gpu-lane-control-plane scope](../../scopes/cpu-gpu-lane-control-plane.md) and [gpu-detailed-tier scope](../../scopes/gpu-detailed-tier-oci-bursty-scope.md) (what is automated/backend)
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-5")`

## WBTRUST-5. Control placement — Describe, GPU information, pagination, Details

Frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/`.

## Objective

The library pane carries the frequent command (Describe) and one line of state; GPU/recognition information is informative-only and reachable on demand; pagination appears above and below the table; "Details" opens something next to the strip and returns focus to it.

## Problem Statement

- R6: where does `…acx-media-selection__bulk-describe > div > button` belong? "GPU controls seem to be all over the place and may overwhelm the user with options and config/settings that belong to the backend or should be automated or in modals/informative only."
- R8: `acx-media-selection__pagination` "needs to be at the top and bottom of library table."
- R12: `…acx-workbench-control-scan … acx-activity-status-strip__meta-actions` "just scrolls up to top of page."

## Constraints

- E23 hard constraints: no agent GPU actuation; operator GPU control (start/stop/auto/lease) stays in Settings › Burst GPU (`pages/settings/GpuControlCard.tsx`, mounted only in `SettingsPage.tsx`). Nothing configurable is added to the workbench.
- rg-003: primary controls reachable from zero state — hold reasons use `aria-disabled` + `aria-describedby`, never HTML `disabled`. Preserve the sr-only live regions of `BulkDescribeCta`.
- Operator copy: no "cluster/identities/embeddings". sr-004 tokens; status = colour + icon. The accepted scope requires top and bottom pagination with distinct nav `aria-label`s; NAV-21 concerns bounded return trips.
- Style edits in `styles/components/_workbench.scss` (AdvancedDrawer block) and the media-selection partial only.
- Tests on the remote VM lane.
- Preserve existing cancellation, CAS, backoff and 20-job data guards; no new interactivity beyond the accepted info control and single Run details trigger. Footer remains nonsticky.

## Workflow Principles

- Reproduce R12 before redesigning it (S1): the report names a scroll jump; the code shows `setAdvancedOpen(true)` and an inline drawer at the page end.
- Delete dead UI (greenfield): a component without a mount goes, with its tests.

## Terminology

**Strip** = `ActivityStatusStrip`. **Drawer** = `AdvancedDrawer` ("Advanced: jobs & recovery"). **Footer** = `acx-media-selection__footer`.

## Current State Analysis

(Symbols, not line numbers.)

- `pages/workbench/MediaSelection.tsx`: the footer `<div className="acx-media-selection__footer">` holds `MediaSelectionPagination` (label id `acx-media-page-size-label`) then `BulkDescribeCta` (props: selectedCount, isSubmitting, isCancelling, isRunning, errorMessage, remoteActionTitle, remoteActionAriaDisabled, accentPrimary, recognitionPolicy, isIdentifying, onSubmit, onCancel). `BulkDescribeCta` renders the recognition disclosure `<p id=DESCRIBE_RECOGNITION_DISCLOSURE_ID>` (exhaustive switch over `RECOGNITION_POLICY`: ON/OFF/UNAVAILABLE/LOADING) and `<p data-testid="acx-bulk-describe-gpu-cost">` with a "GPU controls" link via `toSettings()`. `mediaFooterCtaState.ts` owns `ACCENT_PRIMARY_ATTR`.
- GPU wording appears in four places: that footer paragraph, `BulkDescribeProgress` warming copy, `ActivityStatusStrip` warming/timeout copy, and `GpuTierStatus.tsx` (`pages/workbench/`), which has **no mount outside its own file** (tests: `GpuTierStatus.test.tsx`, `MediaSelection.gpuStatus.test.tsx`; helper `gpuStatePresentation.ts`; toasts via `useGpuStateToasts`).
- `ActivityStatusStrip.tsx`: the "Details" button (`acx-activity-status-strip__meta-actions`) calls `setAdvancedOpen(true)` from `useWorkbenchNav()`. `AdvancedDrawer.tsx` (inline disclosure, own trigger "Advanced: jobs & recovery", `aria-controls="acx-advanced-drawer-panel"`, focuses the first focusable on open, Esc closes and restores focus to its own trigger) is rendered at the end of `pages/WorkbenchPage.tsx`, after the two-pane layout; `JobPipelineContext.tsx` also calls `setAdvancedOpen(true)`.
- Prior findings that bound this plan (ISSUEDAG-1, decision 11085): the bulk-describe CTA carries a credit/recognition disclosure but no verified GPU cold-cost preview; `GpuTierStatus` treated total completed as CPU drafts without tier proof (`cpuDraftCount`, still referenced from `gpuStatePresentation.ts`); the Settings `GpuControlCard` already covers stale-as-unknown, Start/Stop inline confirmation and deferred-stop copy. Verdict then and now: no new GPU control; any price or ETA wording needs configured, provenance-backed values, otherwise it is removed. Decision 11113 flagged a second Settings link inside the recognition-describe node: the popover keeps exactly one.
- The `describe-gpu-tier` map still lists "explicit Start/Stop GPU control?" as an open question while the `gpu-operator-control` map and E23 already place those controls in Settings; S6 supplies final copy for the later shared-map integration owner to reconcile the two.
- Served-build caveat (scope Step 0): the footer and Details behavior were observed on an older overlay build; S1 confirms they persist on current `main` before layout work.
- Why R12 happens is **unverified**: candidates are `focus()` into a far-away panel without `preventScroll`, a drawer that is empty or already open, or an off-screen scroll container. S1 settles it.
- Map text: `workbench-2pane.uxmap.json` zone `z-lib-actions` has a very long label pinned in the JSON and `.md`; it also lists an open question "Bulk-describe cost preview granularity".

## Target Outcome

```
Library table
  ┌ pagination (top):  ‹ Prev  Page 2 of 9  Next ›   Per page [25▾] ┐
  │ …rows…                                                          │
  └ pagination (bottom): same component, same state ────────────────┘
  Footer: [ Describe 12 selected ]  "Uses Burst GPU when ready"  (i) ← popover: what runs where, link to Settings › Burst GPU
Strip:  Scanning… 8/20     [Run details]  → panel opens adjacent; Esc/close returns focus to [Run details]
```

## Context Loading

`MediaSelection.tsx` (holds `MediaSelectionPagination`, `BulkDescribeCta`, `BulkDescribeProgress`), `mediaFooterCtaState.ts`, `GpuTierStatus.tsx`, `gpuStatePresentation.ts`, `ActivityStatusStrip.tsx`, `AdvancedDrawer.tsx`, `pages/WorkbenchPage.tsx`, `WorkbenchTwoPaneLayout.tsx`, `JobPipelineContext.tsx`, `navigation/appLinks`. Canon (v0.26.2): INT-13, INT-23, INT-28, NAV-06, NAV-19, NAV-21, NAV-38, COG-07, PERC-01, VIZ-17, VIZ-27, LAY-21, LAY-22, LAY-24, A11Y-13, A11Y-16.

## Contract and Boundary Impact

- None (no API, PHP or service change).
- Footer remains nonsticky; S5 verifies the accepted layout.
- WBTRUST-5 owns the final Wave A strip. One later integration owner consumes that strip plus WBTRUST-4 actual cooldown observations (`cooldownRemainingMs`, suppression/retry outcomes) to add wait-state hints; no concurrent WBTRUST-4 strip edits and no prescribed new UI prop/callback API. This names the data and exclusive strip resource (canon v0.26.2, GRPH-32, **An edge exists only where data moves**, `lexicons/graph-theory.md#grph-32`).

## Proposed Solution

Move information off the action row: the footer keeps the Describe action and one status line; the long GPU/recognition explanations become a non-modal popover from an info control (COG-07 just-in-time help). Pagination renders twice from one component and one state. "Details" opens a panel beside the strip and returns focus to the strip's own button; the duplicate drawer trigger goes.

## Files and Surfaces to Change

Owned paths:

- `pages/workbench/MediaSelection.tsx` (also defines `MediaSelectionPagination`, `BulkDescribeCta`, `BulkDescribeProgress`), `mediaFooterCtaState.ts`, new `GpuInfoPopover.tsx`, delete `GpuTierStatus.tsx` + `GpuTierStatus.test.tsx` + `MediaSelection.gpuStatus.test.tsx` if S1 confirms no mount/export use
- `pages/workbench/ActivityStatusStrip.tsx`, `AdvancedDrawer.tsx` (becomes the adjacent panel), `pages/WorkbenchPage.tsx`, `WorkbenchTwoPaneLayout.tsx` (slot only)
- `styles/components/_workbench.scss`, the media-selection style partial (tokens only)
- Tests: `BulkDescribeCta.test.tsx`, `BulkDescribeCta.disclosure.test.tsx`, `MediaSelection*.test.tsx`, `ActivityStatusStrip.test.tsx`, `AdvancedDrawer.test.tsx`
- Docs: `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` + `.md` (zones `z-lib-actions`, `z-lib-table`), `gpu-operator-control` map if its workbench-side text changes; `make lint-ux-maps`. The shared `describe-gpu-tier.uxmap.json` and `.md` must be excluded from both WBTRUST-5 and WBTRUST-7 parallel owned sets; WBTRUST-5 does not own them: one later integration owner writes them after both tasks supply final copy (WBTRUST-7 plan alignment is a separate owned-doc handoff)

## Verification Strategy

- Unit: pagination renders twice with distinct nav labels and shared state; footer has no `<p>` prose besides the one-line state; popover opens/closes with Esc and returns focus to the info control; Details opens the panel and Esc/close returns focus to the strip's button; aria-disabled hold reasons unchanged.
- Dead-code check: `grep -rn GpuTierStatus` outside tests returns nothing before deletion.
- Browser (fir site): footer at 1280 and 782 px widths; keyboard order top-pagination → table → bottom-pagination → Describe → info; Details opens in view without a page jump; no GPU configuration control outside Settings.
- `npm run typecheck`, `npm run lint`, `vitest run` on the VM; `make lint-ux-maps`.

## Slice Delivery

### Slice S1: recon-and-red-tests

Reproduce R12 and confirm what is dead.
Closes: R12 (diagnosis). Canon: TEST-15 (Prove the green can go red; `lexicons/engineering.md#test-15`), A11Y-13.
Design decision (binding): record the served build (scope Step 0), then record, with the browser on the fir site, what "Details" does today (scroll target, focus target, drawer state) and which element `…meta-actions button` resolves to; `grep` and codemap-confirm `GpuTierStatus` has no consumer. RED tests: footer prose absent, pagination twice, Details returns focus to the strip button.
Acceptance: decision records the R12 cause and the dead-code result; RED tests fail on the base SHA.

### Slice S2: pagination-top-and-bottom

Controls at both ends of a long list.
Closes: R8. Canon: NAV-21, NAV-19, PERC-01.
Design decision (binding): `MediaSelectionPagination` renders above the table and in the footer from one component and one state, each in a `<nav>` with a distinct `aria-label` ("Library pages, top" / "Library pages, bottom"); page-size select appears once (top) to avoid two labelled selects; ids unique (`acx-media-page-size-label` stays on the one select).
Acceptance: both navs present; changing page from either updates both; axe-style duplicate-id test passes.

### Slice S3: footer-describe-and-info

Frequent command first; configuration prose out of the row.
Closes: R6. Canon: INT-13, NAV-06, INT-23, COG-07, VIZ-27, LAY-22.
Design decision (binding): the footer renders `BulkDescribeCta` (button + the existing sr-only live regions) and one state line (selected count / running / hold reason). The recognition disclosure and GPU-cost paragraphs move into `GpuInfoPopover` (non-modal, opened by an "i" button, Esc closes, focus returns); the popover links to Settings › Burst GPU via `toSettings()` and contains no configurable control and no hardcoded price or ETA: numbers come from configured values with their source named, else the sentence is dropped (decision 11085). `aria-describedby` keeps pointing at the hold reason/disclosure so assistive tech still hears the cost note. Delete `GpuTierStatus` and its tests if S1 confirms.
Acceptance: `BulkDescribeCta*` tests updated and green; `data-testid="acx-bulk-describe-gpu-cost"` lives in the popover; no GPU start/stop/auto/lease control in the workbench.

### Slice S4: details-adjacent-panel

Open the thing next to where you clicked.
Closes: R12. Canon: NAV-19, NAV-38, A11Y-13, INT-28.
Design decision (binding): the strip's "Details" is renamed "Run details" and opens a non-modal panel anchored to the strip (same column), replacing the end-of-page drawer; one trigger only (remove "Advanced: jobs & recovery" as a second button; `JobPipelineContext` callers still call `setAdvancedOpen(true)`); Enter/Space on Run details opens it; focus uses `focus({preventScroll:true})`, with `scrollIntoView({block:'nearest'})` only if the adjacent panel is outside the visible scroll region; no forced page-top jump. Preserve native scroll-key behavior outside handled controls; Esc/close ⇒ focus returns with `preventScroll` to Run details. No modal focus trap or new global key handler.
Acceptance: focus-return tests; no `window.scrollTo` side effects; `AdvancedDrawer.test.tsx` rewritten.

### Slice S5: layout-and-browser-check

Check the grid, not just the DOM.
Closes: R6, R8, R12. Canon: LAY-21, LAY-22, LAY-24, UI-01.
Design decision (binding): footer and pagination rows use a group-level layout property (grid/flex on the container, not margins on children) with `--acx-*` spacing tokens; verify at desktop and ≤ 782 px; keep the footer nonsticky.
Acceptance: browser walk recorded, including focus/scroll-key behavior and the nonsticky footer.

### Slice S6: maps-and-close

Keep the maps true.
Closes: R6, R8, R12. Canon: INT-22, LAY-24.
Design decision (binding): edit `workbench-2pane.uxmap.json` first (shorten the pinned `z-lib-actions` label; add the top pagination to `z-lib-table`; resolve or restate the "Bulk-describe cost preview granularity" question), hand-mirror `workbench-2pane.md` (no extra H2, never `json.dump`), then `make lint-ux-maps`. Supply final strip/layout observations and GPU information copy (including Settings-only Start/Stop) to the one later integration owner, who consumes WBTRUST-7 final provenance copy before updating the shared `describe-gpu-tier` JSON/Markdown map. Request cooldown rendering integration only after WBTRUST-4 actual observations and this final strip are available; do not write that shared map in this lane.
Acceptance: owned map lint green; final copy/observations and integration request handed off; slice-complete decision per template.
