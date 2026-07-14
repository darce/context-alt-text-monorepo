# E21-5. Unified review queue + person-commit

**Epic**: [E21 Public-MVP UX polish](../../epics/v0.4.1/public-mvp-ux-polish-epic.md) · Phase 3 (P3-A)
**Roadmap**: [public-mvp-ux-polish-roadmap-2026-07-04.md](../../roadmaps/public-mvp-ux-polish-roadmap-2026-07-04.md) §P3-A / §8
**Depends on**: E21-1 (sync status view-model — landed), E21-4 (design tokens — landed)
**Blocks**: E21-9 (person-first roster — needs person-commit on the review card)
**Branch**: `feature/e21-5` · **Worktree**: `context-alt-text-monorepo-e21-5`
**Scope**: frontend-only (`apps/prototype-wp-alt-context/js/admin/`). **Zero backend contract changes.**

## Objective

Replace the 4-queue `SuggestionReviewPanel` stack with a **card-at-a-time review queue** driven by the existing `nextAction` selector, with projection filter chips, per-item optimistic accept/reject with an **announced** undo, and **person-commit** (creatable roster combobox) as the primary naming action on the review card. Finalize one-primary-CTA-per-state in the media footer. This is the demo's central interaction — it converts "a pile of stacked panels" into a legible one-item-at-a-time pipeline.

## Problem Statement

The scan→review→confirm loop is the demo's story, but today it renders as four vertically stacked queues (`SuggestionReviewPanel`, 369 lines) — assignment, merge, suggested-names, top-unlabeled-clusters — plus a bulk-accept block, all mounted at once and competing with a 10–100-row media table for attention (WBUX-1 §2.1 "everything renders at once"). The `nextAction` driver already computes the single highest-priority item but is used only to scroll to those queues or open a labeling panel — it is a scroll helper, not a queue driver. Primary naming routes through a **label-only** path (`updateClusterLabel` → cluster `label` string) rather than committing a real roster person, so a first-time visitor's "name this person" produces a label, not a person. Accept/reject has no user-facing undo (only a silent optimistic rollback on network error). The media footer shows two enabled CTAs (`MediaAnalyzeCta` accent + `BulkDescribeCta` WP-secondary) whose priority is expressed only by CSS class, with no state machine choosing one primary per screen state.

## Constraints

- **Frontend-only. Zero backend contract changes** — all needed endpoints already exist (accept/reject/merge/name/bulk-accept, roster `.../commit`, cluster `PATCH label`). No REST, PHP, or schema edits. If a design pressure suggests a new endpoint (e.g. a server-side batch or an "un-accept"), it is **out of scope** — file as an E16/service follow-on (rg-002).
- **rg-002 (preserve atomic write paths)**: every accept/reject/commit is a **single atomic backend call**. Do not split one backend operation into multiple frontend mutations. Card-at-a-time makes each action single-item, so the existing non-atomic **group** fan-out (`Promise.all(mutateAsync…)` in `SuggestionReviewPanel.tsx:67-112`) is eliminated, not reproduced. Undo is rg-002-safe by construction (see Proposed Solution — deferred-commit window; no inverse endpoint invented).
- **rg-003 (zero-state reachability)**: the queue's primary controls (and the media footer's Analyze CTA) must be reachable and legible from a zero/empty state — disabled-with-reason, never hidden.
- **sr-004 (design tokens)**: all new styles consume `--acx-*` tokens landed by E21-4 (`--acx-color-*`, `--acx-text-*`, `--acx-shadow-*`, `--acx-radius-*`, `--acx-font-weight-*`, `--acx-space-*`). Zero raw hex/scale literals; the tokenization test (`workbench-tokenization.test.ts`) must stay green over every touched `components/*.scss`.
- **sr-007 (centralized status enums)**: projection categories and queue-item kinds import from a single canonical definition (extend the existing `NEXT_ACTION_KIND` / `queue_memberships` union) — no scattered magic strings.
- **No new god-context coupling**: consume existing `WorkbenchContext` / `useWorkbenchFindings` / `useSuggestionReview*` surfaces; do **not** widen `WorkbenchContextValue`. The provider decomposition is E21-11 (P5-A) and is out of scope here — but do not add fields that make it harder.
- **Banned vocabulary**: all user-visible copy passes `banned-vocabulary.test.tsx` (`topology`, `replay`, `projection`, `dead-letter`, `curation acknowledgement`, `Source version`, `projected instances`, `Curriculum`, raw UUIDs). "Projection" chips must use human labels (e.g. "Needs confirmation", "Singletons"), never the raw `queue_memberships` strings.

## Workflow Principles

- **Relocate/rebuild-behind-behavior, don't redesign data flow.** The queue is a new presentation over existing queries and mutations. Every backend interaction already exists and stays byte-for-byte.
- **Risk-first slicing.** Slice 1 lands the structural core (queue driver + single-card shell replacing the stack) under orchestrator ownership; Slices 2–4 layer behavior onto the shell and are parallelizable across **Claude Agent-tool subagents on disjoint file sets** (grok offload is on security hold). Each slice merges independently through the pre-merge gate.
- **A11y is acceptance, not audit.** Every async surface (card transition, undo toast, commit result) ships a live-region assertion; the core loop passes a keyboard-walk. Axe alone gates nothing (A11Y-23).
- **Read the landed dependency plans before Slice 1** — E21-1 (`E21-1-sync-status-view-model-task-plan.md`) and E21-4 — to consume whatever status view-model and tokens actually landed rather than what this plan assumes.

## Terminology

- **Review queue**: the new card-at-a-time surface replacing the `SuggestionReviewPanel` stack.
- **Queue driver**: the `selectNextAction` priority selector (`useWorkbenchFindings.ts:112-144`), promoted from scroll-helper to the thing that chooses which single card is shown.
- **Person-commit**: creating or assigning a real roster person via `commitClusterToRosterEntry` (`POST .../roster/clusters/{id}/commit`). Distinct from **label-only rename** (`updateClusterLabel` → `PATCH .../clusters/{id}`, a `label` string with no roster person).
- **Projection chip**: a filter chip for an E15-13 `queue_memberships` category — `singleton-proposals`, `hard-examples`, `needs-confirmation-after-merge` — rendered with human copy.
- **Deferred-commit undo**: optimistic UI + a single backend call deferred until the undo toast window closes; "Undo" cancels the pending call (no inverse endpoint needed).

## Current State Analysis (ground truth, verified 2026-07-13 on `feature/e21-5` @ `177ea0aa`)

**The 4-queue stack** — `pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` (369 lines), rendered at `ScanTabContent.tsx:145` inside `#acx-findings-detail-anchor`:
1. Assignment queue `.acx-suggestion-queue` (`:175-238`) — "These faces are close matches but need your confirmation."; renders `GroupedSuggestionCard` / `SuggestionCard`.
2. Merge queue `CollapsibleMergeQueue` (`:240-245`) — "Merge Candidates", collapsed, `localStorage['AltContext:MergeQueue:Open']`.
3. Suggested-names queue `.acx-naming-queue--suggestions` (`:247-298`) — "Suggested names".
4. Top-unlabeled-clusters `TopClustersSection` (`:300-304`, 274 lines).
   Plus **bulk-accept** block `.acx-bulk-accept` (`:306-365`) — confidence-threshold slider (default `0.6`) + 3 buttons.

**Mutations** — `useSuggestionReviewMutations.ts` (144 lines) → `api/recognition/identityActionsApi.ts` (73 lines); endpoints registered `src/admin/class-admin.php:357-360`. Each is a single atomic `POST`: `suggestions/{id}/accept`, `/reject`, `/merge/{id}/accept|reject`, `/name/{id}/accept|reject`, `/bulk-accept` (`{suggestion_type, min_confidence}`). Optimistic `onMutate` removes from `queryKeys.suggestions.pending()`; `onError` restores previous cache and `console.warn`s (silent — no visible undo). **Group** accept/reject (`SuggestionReviewPanel.tsx:67-112`) fan out with `Promise.all` — the only non-atomic path.

**Queue driver** — `useWorkbenchFindings.ts` (283 lines): `NEXT_ACTION_KIND` = assignment|merge|name|cluster|none (`:14-20`); `selectNextAction` (`:112-144`) picks top item by fixed priority (reviewItems[0]→merge[0]→name[0]→largest cluster→none), reviewItems pre-sorted by descending similarity. Consumed by `WorkbenchFindingsPanel.tsx` (174 lines): `handleReviewNext` (`:75-87`) only labels (`onLabel`) or scrolls (`onTargetFindings`); single "Review next" button (`:159`).

**Person-commit vs label-only** (two comboboxes, both wrap `components/ui/combobox.tsx`, 245 lines, creatable via `onCreate`→`Create "%s"` at `:213`):
- **Person-commit (roster drawer)** — `pages/roster/ClusterDrawerPanel.tsx:259`, aria "Commit to roster entry", `Confirm Assignment` (`:290`) → `commitClusterToRosterEntry` (`api/rosterApi.ts:46-66`) → `POST roster/clusters/{id}/commit` `{roster_entry_id, new_entry_name}`; wired via `useClusterActions.ts:64` (invalidates clusters + roster, toast "Cluster committed to roster entry.").
- **Label-only (Workbench)** — `pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:252`, "Name this person" → `updateClusterLabel` (`clusterApiMutations.ts:16`) → `PATCH recognition/clusters/{id}` `{label}`. Selecting a person only copies the text; **no roster person is created**. Duplicate-detection offers `mergeCluster`. Suggestion cards route "Name Person" (`SuggestionCards.tsx:175`) → `onLabel` → this panel.

**Projections (E15-13)** — canonical union `api/generated/roster-entry.ts:26` `queue_memberships: ('singleton-proposals'|'hard-examples'|'needs-confirmation-after-merge')[]`; `projection_status: 'current'|'refreshing'|'stale'|'failed'` (`:29`). Surfaced today as roster filter badges (`RosterEntriesSection.tsx:27-50,171`) + per-person sections (`PersonWorkspacePanel.tsx:6-25`), not as Workbench chips. **Hard-examples is already the gated queue**: `RosterEntriesSection.tsx:69-72` returns notice "Hard-examples review actions stay unavailable here until the dedicated review contract lands." and has no review route (the coming-soon precedent).

**Media-footer CTAs** — `MediaSelection.tsx:137` footer renders `MediaSelectionPagination` → `BulkDescribeCta` (`:281-331`, label "Describe selected", bare WP `"button"` = secondary) → `MediaAnalyzeCta` (`MediaAnalyzeCta.tsx:30-41`, accent/primary `_workbench.scss:628-634`). Two enabled CTAs, priority only by CSS, no per-state gating. (The literal "Describe with AI" is the dashboard `DescribePanel.tsx:63`, not the footer — footer says "Describe selected".)

**DebugMetricsPanel** — `DebugMetricsPanel.tsx` (212 lines) is **already dev-gated**: `:65-68` `if (!isDevMode() || !metrics) return null` (`isDevMode()` from `api/config.ts:89-95`, server `devMode` flag). E21-5 verifies + regression-tests the gate; it does not rebuild it.

**A11y harness (E21-1/E21-12 seeds)** — `tests/e2e/a11y/`: `keyboard-walk.spec.ts` (`tabUntilFocused` helper `:31-43`, drive focus via `keyboard.press('Tab')`, never `.focus()`); `live-region.spec.ts` (assert `role=status`, `aria-live=polite`, re-read after transition; inline `BANNED` regex); `workbench-axe.spec.ts` (`assertNoBlockingViolations`). Unit: `js/admin/__tests__/banned-vocabulary.test.tsx` (378 lines, `PAGE_SWEEP` registry). Tokens landed by E21-4: `styles/tokens/_colors.scss` (incl. `--acx-shadow-1/2/-card`), `_typography.scss` (incl. `--acx-font-weight-*`), `_radius.scss`, `_spacing.scss`. Reusable toast: `context/ToastContext.tsx` (Radix Toast, `useToast()`, aria-live internal) — the announced-undo reuse target. `MergeUndoBanner.tsx` is an undo affordance but **not** a live region.

## Target Outcome

A first-time visitor, after scanning, sees **one review card at a time** — the highest-priority item the `nextAction` driver selects — with filter chips to scope by projection category. They accept or reject with a single click; an announced toast confirms and offers **Undo** for a few seconds. When they name a person, they **commit a real roster person** (creatable combobox), and a "View \<name\> →" affordance points at the roster. Bulk accept is one disclosure, not a stacked block. The media footer shows exactly **one primary CTA per screen state**. Every state (loading/empty/error/offline) manages focus and announces; the whole loop passes a keyboard-walk and a screen-reader pass. No sync-internal jargon reaches the UI.

Outcome metric (PROD-01): the epic's before/after **time-to-first-named-person** on the live demo — E21-5 is the interaction most on that path.

## Context Loading

- Landed dependency plans: `docs/tasks/21.0/E21-1-sync-status-view-model-task-plan.md`, `E21-4-design-token-system-task-plan.md`, and `E21-6-media-step-compaction-task-plan.md` (owns the footer relocation E21-5 builds on).
- WBUX-1 §2.1 (action pyramid / "everything renders at once") and §3 (REVIEW sketch); WBUX-2 §2 (capability matrix) — the source diagnoses.
- Heuristics: `gh api repos/darce/heuristics-canon/contents/lexicons/<accessibility|design-aesthetics|business-marketing>.md --jq .content | base64 -d`.

## Contract and Boundary Impact

| Boundary | Owner | Today | After E21-5 | Contract change? |
| --- | --- | --- | --- | --- |
| Suggestion accept/reject/merge/name/bulk-accept | REST `acx/v1/recognition/suggestions/*` | atomic POSTs | **unchanged** — consumed one card at a time | none |
| Person-commit | REST `acx/v1/recognition/roster/clusters/{id}/commit` | called only from roster drawer | also called from the review card | none (same body) |
| Label-only rename | REST `PATCH recognition/clusters/{id}` | primary naming path | demoted to tertiary "just label" action | none |
| `queue_memberships` / `projection_status` | generated `roster-entry.ts` | roster surfaces | also drive Workbench projection chips | none (read-only consume) |
| Workbench URL params | `useWorkbenchFilters` | `s,p,perPage,status,tab,panel` | queue filter chip may add a `queue=` param (shim-compatible) | additive, shimmed |

No PHP, REST, or schema edits. Boundary verification (backend guidelines step 5) is a read-only confirmation that no endpoint shape changes.

## Proposed Solution

**1. Queue driver (promote `nextAction`).** Extend `selectNextAction` from "top item" to an ordered, filterable **queue view** over the same sources: expose the ordered list (not just `[0]`) and a `filter` by projection category, keeping the existing priority for the default (unfiltered) order. Keep `NEXT_ACTION_KIND` as the canonical kind enum (sr-007); add a projection-category enum alias over `queue_memberships` with human labels. No new queries — derive from the data `useWorkbenchFindings` already holds.

**2. Card-at-a-time shell (`ReviewQueue`).** New `pages/workbench/identity-clusters/ReviewQueue.tsx` replaces the 4-queue body of `SuggestionReviewPanel`. Renders exactly one card (the current queue head) + a projection **filter-chip row** + a "N of M" position indicator + prev/next. Each card is the existing per-kind card (`SuggestionCard` / `MergeSuggestionCard` / name card) reused, not re-implemented. `SuggestionReviewPanel` becomes a thin host (header + `ReviewQueue` + bulk-accept disclosure) or is retired in favor of `ReviewQueue` directly at the `ScanTabContent.tsx:145` anchor. Card transition announces via live region (A11Y-21).

**3. Optimistic accept/reject + announced undo (deferred-commit window).** On accept/reject, optimistically advance the queue and show a `useToast()` toast "Accepted — Undo" with a ~5s window; the single atomic POST fires when the window closes, and **Undo cancels the pending POST** and restores the card (rg-002-safe: exactly one backend call, or none). The toast is announced (Radix Toast is a live region; add an explicit `role="status"` assertion). No inverse/"un-accept" endpoint is invented. **Rejected alternative**: fire immediately + call an inverse endpoint on undo — rejected, no such endpoint exists and it would double the backend calls.

**4. Bulk accept as a disclosure.** The confidence-threshold bulk-accept block collapses into a single disclosure ("Accept high-confidence…") reusing the existing atomic `POST .../bulk-accept`. The non-atomic **group** fan-out is removed (card-at-a-time handles a cluster as one card with its own atomic action).

**5. Person-commit primary on the card.** Bring the roster-commit creatable combobox (reuse `components/ui/combobox.tsx` with `onCreate` + `commitClusterToRosterEntry`) onto the review card as the **primary** naming action; demote label-only (`updateClusterLabel`) to a tertiary "just label, don't add to roster" affordance. On success emit "View \<name\> →" toward `#/roster?person=<uuid>` (link vocabulary is E21-10's full contract; here we emit the one confirm affordance the roadmap names).

**6. Projection chips.** Three chips from the canonical union with human labels; `singleton-proposals` + `needs-confirmation-after-merge` active (filter the queue), `hard-examples` renders a **"coming soon"** chip (disabled + notice, reusing the existing "unavailable until the review contract lands" precedent). Chip copy is human, never the raw union string (banned-vocabulary).

**7. Media-footer CTA hierarchy (state matrix).** Introduce a small per-state selector deciding the single primary CTA in `MediaSelection.tsx`'s footer: during select → Analyze is primary, Describe secondary; when a describe run is in flight → its progress owns the surface; when review is active → the queue owns primary and both footer CTAs are non-primary (consistent with E21-6's collapse). Encode the loading/empty/error/offline × focus + announcement matrix (A11Y-24) as acceptance. **Offline** here is the minimal disabled-with-reason + announced treatment; the full breaker/fail-fast model is E21-7 (P3-C) — note the seam, do not build it.

**8. DebugMetricsPanel.** Verify the existing `isDevMode()` gate; add a regression unit test asserting it renders `null` in non-dev. No rebuild.

## Files and Surfaces to Change

| Kind | Path | Change |
| --- | --- | --- |
| new | `js/admin/pages/workbench/identity-clusters/ReviewQueue.tsx` | Card-at-a-time queue shell: one card + projection chips + position/prev-next; consumes existing cards + mutations |
| edit | `js/admin/pages/workbench/identity-clusters/SuggestionReviewPanel.tsx` | Retire the 4-queue stack body; host `ReviewQueue` + bulk-accept disclosure (or delete in favor of `ReviewQueue` at the anchor) |
| edit | `js/admin/pages/workbench/identity-clusters/useWorkbenchFindings.ts` | Expose ordered/filterable queue (not just `[0]`) + projection-category alias enum |
| edit | `js/admin/pages/workbench/identity-clusters/useSuggestionReviewMutations.ts` | Deferred-commit window + undo-cancel; remove need for the group fan-out |
| edit | `js/admin/pages/workbench/identity-clusters/WorkbenchFindingsPanel.tsx` | "Review next" drives the card queue, not scroll/label routing |
| edit | `js/admin/pages/workbench/identity-clusters/SuggestionCards.tsx` | "Name Person" routes to person-commit combobox (primary); label-only tertiary |
| edit | `js/admin/pages/workbench/MediaSelection.tsx` | Per-state single-primary CTA gating in the footer (Analyze vs Describe) |
| edit | `js/admin/pages/workbench/MediaAnalyzeCta.tsx` | Honor the per-state primary/secondary signal |
| edit | `js/admin/styles/components/_workbench.scss` (+ new `_review-queue.scss`) | Card/chip/disclosure styles, `--acx-*` tokens only (sr-004) |
| test | `js/admin/pages/workbench/identity-clusters/__tests__/ReviewQueue.test.tsx` (new) | Queue navigation, filter chips, one-card invariant, coming-soon chip |
| test | `js/admin/pages/workbench/identity-clusters/__tests__/useSuggestionReviewMutations.test.tsx` | Deferred-commit + undo-cancel = 0/1 backend calls |
| test | `js/admin/pages/workbench/identity-clusters/__tests__/DebugMetricsPanel.test.tsx` (new) | Dev-gate regression (null in non-dev) |
| test | `tests/e2e/a11y/review-queue.spec.ts` (new) | Keyboard-walk over the queue; live-region on card transition + undo toast; state matrix |
| test | `js/admin/__tests__/banned-vocabulary.test.tsx` | Extend `PAGE_SWEEP` to cover the review-queue surface |

## Related Files (read, likely unchanged)

`ScanTabContent.tsx` (anchor `:145`), `api/recognition/identityActionsApi.ts`, `api/rosterApi.ts`, `pages/roster/ClusterDrawerPanel.tsx` (combobox reuse reference), `components/ui/combobox.tsx`, `context/ToastContext.tsx`, `api/generated/roster-entry.ts`, `styles/tokens/*`, `api/config.ts` (`isDevMode`).

## Verification Strategy

- **Unit** (Vitest): `ReviewQueue` navigation/one-card invariant/chip filtering/coming-soon; deferred-commit undo asserts exactly 0 (undone) or 1 (committed) backend call — the rg-002 guard; person-commit routes to `commitClusterToRosterEntry` not `updateClusterLabel`; DebugMetricsPanel dev-gate; banned-vocabulary sweep green.
- **E2E a11y** (Playwright, `ACX_E2E_SEEDED`): `review-queue.spec.ts` — `tabUntilFocused` keyboard-walk reaches accept/reject/name; `role=status` announced on card transition + undo toast; state-matrix cases (loading/empty/error/offline) keep focus + announce (A11Y-24). `workbench-axe.spec.ts` stays green.
- **Tokenization**: `workbench-tokenization.test.ts` green over `_workbench.scss` + new `_review-queue.scss` (sr-004).
- **Visual**: `workbench-visual.spec.ts` re-diffs (baseline already re-set at E21-4; new queue is an intended diff — re-baseline the review region once, documented).
- **Manual (LocalWP)**: scan → review card appears (highest-priority) → accept → toast "Accepted — Undo" → Undo restores card (network shows no commit) → accept again → commits → name via combobox creates a roster person visible on `#/roster` → footer shows one primary CTA per state → airplane-mode reload keeps the queue legible + disabled-with-reason.
- Every slice merges through the pre-merge gate (`handoff_close_check(enforce=True)`); findings in handoff by ID only.

## Slice Delivery

### Slice 1: Queue driver + card-at-a-time shell (orchestrator-owned — highest structural risk)
Promote `selectNextAction` to an ordered/filterable queue; build `ReviewQueue.tsx` rendering one reused card + projection chips + position/prev-next; retire the 4-queue stack body at the `ScanTabContent.tsx:145` anchor; seed `review-queue.spec.ts` (keyboard-walk + card-transition live region). All existing accept/reject/merge/name actions still fire (unchanged, one card at a time). Bulk-accept temporarily kept as-is (disclosure in Slice 2). **Exit**: one card renders at a time; queue navigates by keyboard; existing mutations green; axe + tokenization green.

### Slice 2: Optimistic accept/reject + announced undo + bulk disclosure (Claude subagent; orchestrator reviews)
Deferred-commit window in `useSuggestionReviewMutations.ts`; `useToast()` announced "Undo"; bulk-accept collapses to one disclosure over the existing atomic endpoint; remove the group fan-out. **Exit**: undo-cancel = 0 backend calls, commit = 1 (unit-proven); toast announced (`role=status` asserted); rg-002 intact.

### Slice 3: Person-commit on the review card (Claude subagent; orchestrator reviews)
Roster-commit creatable combobox on the card → `commitClusterToRosterEntry`; label-only demoted to tertiary; "View \<name\> →" confirm affordance; projection chips wired (singleton/needs-confirmation active, hard-examples coming-soon). **Exit**: naming a person creates a roster entry (not just a label); chips filter; coming-soon chip disabled+noticed; banned-vocabulary green.

### Slice 4: Media-footer CTA hierarchy + state matrix + DebugMetricsPanel verify (Claude subagent; orchestrator reviews)
Per-state single-primary gating (Analyze vs Describe); state-matrix a11y cases (loading/empty/error/offline × focus + announcement); DebugMetricsPanel dev-gate regression test. **Exit**: exactly one primary CTA per screen state; state matrix passes; dev-gate regression green; visual re-baseline documented.

## Consolidated Checklist

### Checklist for Slice 1: Queue driver + shell
- [ ] `selectNextAction` exposes ordered + filterable queue; projection-category enum alias added (sr-007)
- [ ] `ReviewQueue.tsx` renders exactly one card + chips + position/prev-next; reuses existing cards
- [ ] 4-queue stack body retired at `ScanTabContent.tsx:145`; existing mutations still fire per card
- [ ] `review-queue.spec.ts` seeded: keyboard-walk reaches actions; card-transition `role=status` asserted
- [ ] axe + tokenization green; no `WorkbenchContextValue` widening

### Checklist for Slice 2: Undo + bulk disclosure
- [ ] Deferred-commit window; undo cancels the pending single POST (0 calls); commit = 1 call — unit-proven
- [ ] `useToast()` announced undo; `role=status` asserted; group fan-out removed (rg-002)
- [ ] Bulk-accept collapsed to one disclosure over the existing atomic `bulk-accept` endpoint

### Checklist for Slice 3: Person-commit
- [ ] Creatable roster combobox on the card → `commitClusterToRosterEntry` (real person, not label)
- [ ] Label-only demoted to tertiary; "View \<name\> →" confirm affordance emitted
- [ ] Projection chips: singleton + needs-confirmation active; hard-examples coming-soon (disabled+notice)
- [ ] banned-vocabulary sweep extended to the queue and green (human chip labels)

### Checklist for Slice 4: CTA hierarchy + state matrix
- [ ] One primary CTA per screen state in the footer (Analyze vs Describe) — state-driven, not CSS-only
- [ ] State matrix (loading/empty/error/offline × focus + announcement) asserted (A11Y-24)
- [ ] DebugMetricsPanel dev-gate regression test (null in non-dev)
- [ ] Visual re-baseline of the review region documented

## Context and Ownership

Slice 1 is orchestrator-owned (structural risk: it moves the anchor and changes the driver contract). Slices 2–4 touch disjoint file sets (mutations/toast · combobox/chips · footer CTAs) and are dispatchable to Claude Agent-tool subagents in parallel after Slice 1 lands, each verified by the orchestrator re-running its tests. Grok offload is on security hold — do not route these to grok.

## Review Readiness

Per-slice: review pass with findings recorded in handoff (by ID), zero open findings, fresh `test_result` at HEAD, `handoff_close_check(enforce=True)`, slice-complete decision. Cross-branch guards in scope: rg-002 (atomic writes — the undo design's core invariant), rg-003 (zero-state reachability), rg-005 (no schema drift — N/A, zero backend), sr-004/sr-007.

## Success Criteria (roadmap §8 subset owned by E21-5)

- [ ] Review queue is **card-at-a-time** with **person-commit** naming (not label-only).
- [ ] **One primary CTA per screen state** on the Workbench.
- [ ] Every new async surface (card transition, undo toast, commit) has a **live-region assertion**; the core loop passes a **keyboard-only + screen-reader** walkthrough (A11Y-23/24).
- [ ] Zero raw hex in touched component sheets; tokenization test covers `_review-queue.scss` (sr-004).
- [ ] No sync-internal jargon in the queue surface (banned-vocabulary green).
- [ ] Zero backend contract changes (rg-002/rg-005 intact).

## Heuristic IDs cited

- **A11Y-21** — announce async status via live region (undo toast, card transition).
- **A11Y-23** — scanner-pass is the floor; keyboard + AT walkthrough required.
- **A11Y-24** — every screen state (loading/empty/error/offline) keeps focus + announcement.
- **A11Y-14 / A11Y-15** — (inherited from E21-9 seam) target size ≥24px and single-pointer alternatives; relevant where the card exposes any drag affordance.
- **PROD-01** — outcome over output: time-to-first-named-person is the metric this task moves.
- **PROD-12** — builder–user proximity: the worst-day AT user must complete the loop.
- Local guards: **rg-002** (atomic writes), **rg-003** (zero-state), **sr-004** (tokens), **sr-007** (centralized enums).
