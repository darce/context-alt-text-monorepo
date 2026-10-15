# Task Plan — WBTRUST-2

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-2
> **Target Branch:** feature/wbtrust-2
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** frontend; request-count test for the commit sequence
> **Depends on:** WBTRUST-3 merged (reuses the settled naming control); WBTRUST-1 merged (both edit `ReviewQueue.tsx`; sequential by design)
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R4, root cause 5), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A4, B3, B4, C4), [workbench-review-queue map](../../ux-maps/workbench-review-queue.md), [GPUFLOW-3 plan](GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md) (cluster→person bind, name weaving); semantic prior art: E21-5-BR-37 (stale show-all member list after remove, fixed with a generation guard and snapshot reset on refetch), IDREBIND-1-W3-01 (`invalidateLabelSurfaces` helper), UXW2-3-R1-02 (roster-loading gate on commit), [roster-person-binding scope](../../scopes/roster-person-binding-scope.md) (roster may be empty while cluster labels exist)
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-2")`

## WBTRUST-2. One curation surface — exclude mismatches, accept the rest

Frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/pages/workbench/` unless stated.

## Objective

From a group of N faces the operator can exclude the wrong ones (reversibly), see the running count, and finish with one primary action — without a confirm dialog per face and without leaving the surface.

## Problem Statement

"Review these faces" (47 Ellyn Heald faces) offers only a × per face. Each × opens a confirm dialog and fires one reassign POST. There is no name, no accept, and no way back to a decision: "there is no path to accept, curate, or manage these matches from this screen. How to accept all after removing mismatches?" The shipped UX map records "remove an incorrect face with confirmation, and return" as the intended job, so this is a design gap, not a regression.

## Constraints

- Deep link `panel=review&cluster=<id>` (NAV-11, `ClusterPanelContext.tsx`) must keep working; do not change URL shape.
- Atomic write paths stay atomic: removal is the existing `removeClusterMember(identityId, block=true)` → `reassignClusterIdentity` → `POST recognition/clusters/reassign` (rg-002). No batch endpoint in this plan.
- Name/commit behavior reuses `PersonCommitControl`, `useClusterLabelMutations`, `NameFaceControl`, `useClusterConfirmSuggestion`; no second naming implementation.
- Operator vocabulary: group, person, face. sr-004 tokens; status = colour + icon + text. sr-007 enums for tile state. sr-008 ≤ 8 params.
- Tests on the remote VM lane.

## Workflow Principles

- Excluding is a *selection*, not a mutation, until the primary action runs. Nothing is sent to the server on toggle.
- Primary action is one button whose label states the outcome ("Accept 44 faces as Ellyn Heald").
- Stop on first failure; show exactly what was applied (INT-10).

## Terminology

**Excluded** = a face the operator marked to leave out; dimmed with an icon and the word "Excluded". **Accept** = apply exclusions, then confirm the remainder (exact server action pinned in S1).

## Current State Analysis

(Symbols, not line numbers.)

- `ScanTabContent.tsx` mounts `ClusterLabelingPanel` when `clusterPanel.mode === 'label'` (props `clusterId`, `onClose`, `onLabel`; on label it announces "Name saved. Back to review suggestions." and calls `focusQueueRoot()`), `ClusterReviewPanel` when `reviewClusterId !== null` (props `clusterId`, `onClose`; announces "Returned to review suggestions"), else `ReviewQueue`. `ClusterPanelContext.tsx` holds `{ mode: 'none' | 'label' | 'review', clusterId }`; `useOpenReviewTargetLifecycle.ts` retires/rebinds; the heading `#acx-workbench-queue-heading` comes from the panel.
- `identity-clusters/ClusterReviewPanel.tsx`: members via `useShowAllClusterMembers`, `DurableFaceThumb`, a confirm `Dialog` per removal, `removeClusterMember`, then invalidation of `memberList`, `clusters.all` and `invalidateSuggestionProjection`. It focuses its Back button on mount and announces show-all expansion.
- `identity-clusters/ClusterLabelingPanel.tsx` already hosts the name form (`NameFaceControl`, duplicate guard, merge undo) **and** a read-only member grid: `ClusterLabelingMemberGrid.tsx` (member loading, reading-order positions via `buildMemberPositions`, show-all expansion and announcement).
- Entry points: `ReviewQueue.tsx` card `onReview(clusterId)` → `open_review`; `PersonCommitControl` `onCurateGroup` → `onLabel` → `open_label`; `useOpenReviewTargetLifecycle` `onRebindSync` → `open_review`.
- Related tests: `ClusterReviewPanel.test.tsx`, `ClusterReviewPanel.expandError.test.tsx`, `ClusterLabelingPanel*.test.tsx` (rosterCandidates, busyCandidateError, candidateBudgetRegression, duplicateGuardBudget, hangingClosestBudget), `PersonCommitControl*.test.tsx`, `NameFaceControl*.test.tsx`, `ScanTabContent.*.test.tsx` (including `labelPanelReachable`).
- Staleness prior art: the expanded-members list once showed removed faces after show-all plus remove (E21-5-BR-37; generation guard, snapshot reset on refetch). The R4 stale grid is a different defect (inspect-only panel), but S2/S3 must keep those properties: exclusions keyed by identity id, dropped when a refetch no longer returns the id.
- Label/commit side effects: invalidation after a commit goes through `utils/invalidateLabelSurfaces.ts` (IDREBIND-1-W3-01), already wired from `useClusterMutations.ts`; `PersonCommitControl` already gates commit while the roster is loading or errored (UXW2-3-R1-02). Reuse both; do not add a second invalidation path.
- Served-build caveat (scope "Step 0"): the fir site serves an older release; confirm the 47-face grid and the "×"-only behavior on current `main` before changes.
- UX map text to change: `docs/ux-maps/workbench-review-queue.md` (the "remove an incorrect face with confirmation" job and its `ClusterReviewPanel` code references — currently line-anchored; re-anchor by symbol) and `workbench-2pane.uxmap.json`.

## Target Outcome

```
← Back to review suggestions        Review these faces — Ellyn Heald
47 faces · 3 excluded                          [Undo all] [Accept 44 faces as Ellyn Heald]
┌────┐ ┌────┐ ┌────┐        tile: click/Space toggles Excluded (dim + icon + "Excluded")
│    │ │ ▒▒ │ │    │        hover/focus: filename · date
└────┘ └────┘ └────┘        arrow keys move between tiles; "Show all (47)" when truncated
```

K exclusions followed by Accept issue exactly K reassigns + 1 commit. Zero exclusions issues the commit only.

## Context Loading

`ClusterReviewPanel.tsx`, `ClusterLabelingPanel.tsx`, `ClusterLabelingMemberGrid.tsx`, `ScanTabContent.tsx`, `ClusterPanelContext.tsx`, `useOpenReviewTargetLifecycle.ts`, `PersonCommitControl.tsx`, `useClusterLabelMutations.ts`, `useClusterConfirmSuggestion.ts`, `useClusterMatchAction.ts`, `useBulkReviewCommit.ts` (sequencer to mirror), `api/recognition/clusterApiMembers.ts`. Canon (v0.26.2): HAI-13, NAV-07, INT-04, INT-10, INT-13, VIZ-15, VIZ-25, A11Y-13, A11Y-14, A11Y-16, A11Y-21, PERC-01.

## Contract and Boundary Impact

- No contract change. If the member wire lacks filename/date (S1 checks), tiles show "Face on media {id}" plus a link to the media edit screen; a contract extension is out of scope.
- **Open decision (operator):** does "accept" need a durable verified-membership state? **Binding default: no** — no new server flag. Accept means: apply exclusions, then run the existing action for the entry context (S1 pins it).

## Proposed Solution

Make `ClusterLabelingMemberGrid` selectable and let `ClusterLabelingPanel` host the primary action. Retire `ClusterReviewPanel` (delete over flag). Keep both reducer actions and the URL so no caller changes: `open_review` and `open_label` render the same panel, differing only in initial focus (grid vs name field) and whether a `suggestionId` is present.

## Files and Surfaces to Change

Owned paths:

- `identity-clusters/ClusterLabelingMemberGrid.tsx`, `ClusterLabelingPanel.tsx`, delete `ClusterReviewPanel.tsx`, new `useClusterExclusions.ts`, new `useCurationCommit.ts`
- `ScanTabContent.tsx` (mount one panel), `ClusterPanelContext.tsx` (optional `suggestionId` on `open_review`), `ReviewQueue.tsx` `onReview` wiring only
- Styles: the cluster-panel partials under `styles/components/` (tokens only)
- Tests: rewrite `ClusterReviewPanel*.test.tsx` into `ClusterLabelingPanel.curation.test.tsx`; update `ScanTabContent.*.test.tsx`
- Docs: `docs/ux-maps/workbench-review-queue.md`, `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` (+ `.md`)

## Verification Strategy

- Unit: exclusion reducer (toggle, undo all, survives show-all expansion, resets on cluster change); request-count test (K=3 ⇒ 3 reassigns then 1 commit, in order); stop-on-first-failure leaves the remaining exclusions pending and reports "Removed 1 of 3".
- A11y: roving tabindex grid, `aria-pressed` on tiles, count in a `role="status"`, Back/Close focus return to the originating card (`focusQueueRoot()` behavior preserved).
- Browser (fir tenant, 47-face group): exclude 3, Accept, return to the queue; media chips reflect membership after reload.
- `npm run typecheck`, `npm run lint`, `vitest run` on the VM; `make lint-ux-maps`.

## Slice Delivery

### Slice S1: pin-accept-and-red-tests

Decide what "accept" executes, then fail first.
Closes: R4 (definition). Canon: HAI-13, INT-13.
Design decision (binding): record the served build first (scope Step 0). Then read `useClusterConfirmSuggestion`, `useClusterMatchAction`, `PersonCommitControl` and `useClusterLabelMutations` and write down, per entry context, the single server action Accept runs: (a) opened from a suggestion card ⇒ confirm that suggestion; (b) opened on an unnamed group ⇒ the name commit; (c) opened on a named group with no suggestion ⇒ apply exclusions and close ("Done — keep N faces"). Check whether the member wire carries filename/date. RED tests encode the request counts and the label text.
Acceptance: decision recorded with the three mappings and the wire finding; RED tests fail on the base SHA.

### Slice S2: exclusion-state

Selection without mutation.
Closes: R4. Canon: INT-04, VIZ-15.
Design decision (binding): `useClusterExclusions(clusterId)` holds a `Set<identityId>`, exposes `toggle`, `clear`, `count`; tile state is a sr-007 enum (`included | excluded`). State survives show-all expansion and resets on cluster change; a member refetch drops ids that are no longer returned (E21-5-BR-37 property). Nothing is persisted.
Acceptance: reducer tests; header reads "N faces · K excluded" via `role="status"`.

### Slice S3: selectable-grid

Make the grid the work surface.
Closes: R4. Canon: A11Y-13, A11Y-14, A11Y-16, VIZ-25, PERC-01.
Design decision (binding): each tile is a toggle button (`aria-pressed`), Excluded = dimmed + icon + text (not colour alone); ≥ 24×24 hit area; roving tabindex with arrow-key movement; filename/date (or "Face on media {id}") on hover and focus only (VIZ-25, no always-on clutter); reading-order positions from `buildMemberPositions` unchanged; the per-face confirm dialog and × button are removed. Handle `truncated` ("Show all (N)").
Acceptance: keyboard walk test; no confirm dialog in the DOM; tile target size asserted.

### Slice S4: accept-sequencer

One primary action, bounded blast radius.
Closes: R4. Canon: INT-10, INT-13, rg-002, rg-007.
Design decision (binding): `useCurationCommit` mirrors the `useBulkReviewCommit` sequencer — run `removeClusterMember(id, true)` for each excluded face in order, stop on first failure, then run the S1-pinned commit; invalidate once at the end through the WBTRUST-4 `runAfterCooldown` primitive wrapping the existing `invalidateLabelSurfaces` helper (not per removal, no new invalidation path). Failure UI: "Removed 1 of 3 — Retry remaining" keeping the rest selected; the Accept button is disabled-with-reason (aria-disabled) while running. Label states the outcome: "Accept {N} faces as {Name}" or "Done — keep {N} faces".
Acceptance: K=3 ⇒ exactly 3 reassigns + 1 commit; failure on the 2nd leaves 2 exclusions pending and no commit.

### Slice S5: one-panel-two-entries

Retire the inspect-only panel.
Closes: R4. Canon: NAV-07, NAV-19.
Design decision (binding): `ScanTabContent` mounts the curation panel for both `label` and `review`; `open_review` carries an optional `suggestionId` (not in the URL; absent on deep-link reload ⇒ context (c) or (b) from S1); initial focus: grid for review, name field for label; closing returns focus to the originating card; heading id `#acx-workbench-queue-heading` preserved. Delete `ClusterReviewPanel.tsx` and its two tests after the rewrite.
Acceptance: `ScanTabContent.labelPanelReachable` and deep-link tests green; both entry points reach the same component.

### Slice S6: maps-and-browser-check

Close the loop in docs and on screen.
Closes: R4. Canon: LAY-24, INT-22.
Design decision (binding): re-anchor the review-queue map by symbol (drop line anchors), describe the curation job in operator vocabulary, mirror the JSON/`.md`; browser walk of the 47-face group recorded in the decision. Duplicate-pixel collapse stays a follow-up unless WBTRUST-1 S1 proves it is a product-path problem.
Acceptance: `make lint-ux-maps` green; browser walk noted; slice-complete decision per template.
