# Task Plan — WBTRUST-1

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-1
> **Target Branch:** feature/wbtrust-1
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 1
> **Review Coverage Target:** frontend + one contract read; PHP/service only if slice S1 shows the producer emits a score for an empty reference set
> **Depends on:** WBTRUST-4 merged (the reference strip adds one cached request per visible card; its budget must exist first)
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R1–R3), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (A1–A3, B1–B2, B6, C1, D1), [FIR report](../../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html), [workbench-review-queue map](../../ux-maps/workbench-review-queue.md), [workbench-2pane map](../../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json), [GPUFLOW-3 plan](GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md) (queue unification, HAI-17 gate origin)
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-1")`

## WBTRUST-1. Review-queue trust — evidence before score

All frontend paths are relative to `apps/prototype-wp-alt-context/js/admin/`.

## Objective

An assignment suggestion ("Is this X?") never shows a match percent without the reference face(s) it was computed against, never locks "Yes" behind a toggle whose content cannot satisfy it, and never presents a 30–40 % candidate as an ordinary item.

## Problem Statement

Operator walk-through of the fir site (suggestions 1, 2 and 5 of 31):

- Card 1: "Is this Nicky Ross?" says "100 % match (1 faces)" beside an avatar with `data-avatar-state="data-missing"`; Yes is enabled.
- Card 2: "100 % match (10 faces)", Yes disabled behind "Show stored faces first to approve."; the opened list shows an image only for stored face 1.
- Card 5: 34 % "Low confidence" for a candidate compared with a smoke-fixture image stored in another person's group.

## Constraints

- NAME-kind cards keep the blind-judgment protocol (`nameJudgments`, `revealedNameSuggestionIds`). Only the ASSIGN card changes.
- rg-003: primary controls reachable from zero state. rg-015: no invented contract metadata. rg-002: approve/reject write paths unchanged.
- sr-004 tokens only; status = colour + icon (sr-004). sr-007 enums for any new state. sr-008 ≤ 8 destructured params.
- No migrations (greenfield). No new endpoint unless S6 is triggered.
- Tests run on the remote VM lane (`vitest run <paths>` from `apps/prototype-wp-alt-context`); never locally containerised.

## Workflow Principles

- RED first: S1 lands failing tests that encode the operator's three cards before any component edit.
- Prove the duplicate-pixel hypothesis before writing any guard for it (S1, S5).
- Evidence is cached and shared: reuse `queryKeys.clusters.memberList(clusterId)`; add no parallel store.

## Terminology

Operator vocabulary: **group** (cluster), **person**, **face**. Code keeps `cluster`/`identity`. "Reference face" = a stored face of the suggested group that the score was computed against.

## Current State Analysis

(Symbols, not line numbers.)

- `pages/workbench/identity-clusters/SuggestionCards.tsx` `SuggestionCard`: `matchPercent = Math.round(similarity * 100)` is rendered unconditionally; `isLowConfidence = similarity < lowConfidenceThreshold` adds a flag only. `storedFaceCount` comes from `suggestion.identityCount`, else 1 when a representative exists, else 0.
- Stored-face list: an `Avatar` is rendered only for `position === 1 && representativeThumbUrl !== null`; every other position is the text "Stored face N of M — Image unavailable". `SuggestionFacePlaceholder` renders the missing-image avatar for card 1.
- `storedFaceReviewGate.ts`: `requiresStoredFaceReview` is true when `identityCount > 1` (HAI-17 origin); `isStoredFaceApprovalBlocked` is shared with `ReviewQueue.tsx` `isBulkApprovalBlocked` (ASSIGNMENT case). Yes: `disabled={isPending || approvalRequiresReview}` with the hint below the button.
- Wire data is thin: `PendingSuggestion` (`api/recognition/types/suggestion.ts`) carries one representative image (`representative_thumb_url`, `representative_media_url`, `representative_bbox`), `identity_*` for the candidate and `cluster_identity_count`. A multi-face strip needs the group's members.
- Member source already exists: `useShowAllClusterMembers(clusterId)` (`identity-clusters/`), `queryKeys.clusters.memberList(clusterId)`, `fetchClusterMembers`, rendered with `components/ui/DurableFaceThumb`.
- Fetch path: `fetchPendingSuggestions(limit, offset)` in `api/recognition/identityQueriesApi.ts` sends no `min_confidence`; PHP `class-suggestions-controller.php` accepts it. The 34 % card comes from the server floor (`suggestion_floor` 0.35 − `low_confidence_band_width` 0.05 = 0.30 effective in `recognition/config`/`application/settings/clustering.py`); the `min_confidence=0` default belongs to `fetchPendingNameSuggestions` (NAME kind), **not** the assignment list. The scope's root cause 3 conflates the two; this plan follows the code. A pending ~100 % item is anomalous: a score ≥ the 0.55 ceiling auto-accepts, so S1 must explain why it is pending (same-photo duplicate row is the leading hypothesis).
- `ReviewQueue.tsx`: `LOW_CONFIDENCE_THRESHOLD = 0.6` is client-side; `buildSuggestionReviewItems` (`suggestionReviewItems.ts`) sorts by score and groups by group.
- The `acx-smoke-*` fixture generator was not found in this repo; removing those files from the fir tenant is an operator purge, not product code.

## Target Outcome

| Card state | Display | Yes |
| --- | --- | --- |
| ≥ 1 reference thumbnail loaded | Candidate beside a strip of up to 6 reference faces ("+N" opens the rest), score as band word + number | enabled; low band adds a visible caution, not a lock |
| 0 references resolvable (URLs absent or all fail to load) | "Can't verify — reference image unavailable"; **no score** | aria-disabled with the reason beside the button; No and "Open face group" stay active |
| Score below the low-confidence threshold | Not in the main list; in a "Low confidence (N)" disclosure after the rest, same card, caution on | enabled, individually only (excluded from select-all) |

## Context Loading

Read in order: `SuggestionCards.tsx`, `storedFaceReviewGate.ts`, `suggestionReviewItems.ts`, `ReviewQueue.tsx` (ASSIGNMENT case and `isBulkApprovalBlocked`), `useShowAllClusterMembers.ts`, `components/ui/DurableFaceThumb`, `api/recognition/types/suggestion.ts`. Canon (v0.26.2): HAI-01, HAI-08, HAI-13, HAI-17, HAI-21, CAL-02, CAL-11, FORM-09, VIZ-15, VIZ-16, VIZ-23, VIZ-27, VIZ-33, PERC-05, PERC-07, LAY-24, INT-22.

## Contract and Boundary Impact

- None required for S2–S5 (client reuses the member list).
- S6 (conditional) adds a server-derived field to the pending-suggestion payload; `docs/workbay/contracts/` entry and PHP controller test must change together (rg-005, rg-015).
- **Open decisions (operator):** (1) low-confidence threshold — default 0.6 (existing constant), settled from the S1 distribution; (2) whether select-all may include low-confidence items — default no.

## Proposed Solution

Replace the "toggle to unlock" gate with always-visible evidence. The card reads reference faces from the shared member cache, tracks whether each thumbnail actually loaded, and derives everything else from that: score visibility, Yes availability, and the "Can't verify" state. Low scores move into a disclosure instead of a flag on the main list.

## Files and Surfaces to Change

Owned paths (no other task edits these):

- `pages/workbench/identity-clusters/SuggestionCards.tsx`, `storedFaceReviewGate.ts` (delete), `suggestionReviewItems.ts`, new `useSuggestionReferenceFaces.ts`, new `SuggestionReferenceStrip.tsx`
- `ReviewQueue.tsx` ASSIGNMENT case, `isBulkApprovalBlocked` and the low-confidence grouping only (WBTRUST-2 later edits the panel-open wiring; sequential)
- `api/recognition/types/suggestion.ts` (S6 only)
- Tests under `pages/workbench/identity-clusters/__tests__/`: `SuggestionCards.test.tsx`, `ReviewQueue.test.tsx`, `ReviewQueue.closestPendingBudget.test.tsx`, `useBulkReviewCommit.test.tsx`, new `SuggestionReferenceStrip.test.tsx`
- Docs: `docs/ux-maps/workbench-review-queue.md`, `apps/prototype-wp-alt-context/docs/ux-maps/workbench-2pane.uxmap.json` (+ derived `.md`, hand-mirrored; no extra H2; run `make lint-ux-maps`)

## Verification Strategy

- Unit: the three operator cards as fixtures (no reference; 10 references with one image today; 0.34 score). Percent text absent when no thumbnail loaded; Yes available with ≥ 1 loaded; reference tiles rendered for every stored face the member list returns.
- Request count: one `memberList` fetch per visible card, shared cache key (assert via fetch mock).
- Existing HAI-17 tests are rewritten to assert *presentation*, not blocking.
- Browser (fir site, remote-verified by the operator or a Chrome tier when available): cards 1, 2, 5 of the 31; focus order Candidate → references → Yes/No; announce text for the "Can't verify" state.
- `npm run typecheck`, `npm run lint`, `vitest run` on the VM; `make lint-ux-maps`.

## Slice Delivery

### Slice S1: evidence-baseline

Settle the three unknowns and land RED tests.
Closes: R1, R2, R3 (diagnosis). Canon: EVAL-16, EVAL-19, CAL-02.
Design decision (binding): no component change in this slice.
Steps: (a) read the 31 pending suggestions from the fir tenant (pinned-socket `rest_do_request` probe) and record `similarity`, `cluster_identity_count` and representative-image presence per item; (b) hash the files behind media 11/86, 6/27/28, 9/26 and compare `acx-smoke-wrong_person-dc6bef8f62de.jpg` with Bea Burke's stored face 1 — decision rule if confirmed: cosine ≈ ≥ 0.999 between different identity rows of one photo means "same photo", not identity evidence; (c) locate the producer of the pending list via codemap `search_graph` for `cluster_identity_count` and state why a ~100 % item is still pending; (d) commit RED tests for the three cards.
Acceptance: a handoff decision with the distribution, the hash result (confirmed / refuted) and the producer location; RED tests fail on the base SHA for the stated reasons.

### Slice S2: reference-faces-hook

Give the card its evidence.
Closes: R2. Canon: HAI-17, VIZ-23.
Design decision (binding): `useSuggestionReferenceFaces(clusterId, { enabled })` reads `queryKeys.clusters.memberList(clusterId)` via `fetchClusterMembers`; returns `{ faces, total, status }`; fetched only for cards in or next to the viewport (current card ± 1). Cap 6 rendered; "+N" opens the rest inline (no dialog).
Acceptance: hook tests for loading, error, truncated (`total > faces.length`) and cache sharing with `useShowAllClusterMembers`.

### Slice S3: evidence-strip-card

Rebuild the ASSIGN card around the strip.
Closes: R1, R2. Canon: HAI-01, HAI-08, HAI-17, HAI-21, CAL-11, FORM-09, PERC-05, VIZ-33.
Design decision (binding): `SuggestionReferenceStrip` renders `DurableFaceThumb` per reference with per-tile load state (sr-007 enum `loading | loaded | failed`); score is rendered only when ≥ 1 tile is `loaded`; otherwise the "Can't verify" state. Remove `requiresStoredFaceReview`, the "Show stored faces" toggle, "Stored face N of M — Image unavailable" text and `storedFaceReviewGate.ts`; `isBulkApprovalBlocked` keys on reference availability instead. Yes uses `aria-disabled` plus an adjacent reason (not HTML `disabled`). One quantity once: drop "(N faces)" and "N more faces not shown" in favour of the strip's "+N".
Acceptance: S1 RED tests green; no percent text in the DOM for card 1's fixture; Yes enabled for card 2's fixture without interaction; keyboard walk reaches strip, "+N", Yes, No, Open face group in reading order.

### Slice S4: low-confidence-disclosure

Move weak matches out of the main list.
Closes: R3. Canon: CAL-02, HAI-08, PERC-07.
Design decision (binding): items below the threshold settled in S1 (default 0.6) are grouped after the rest under "Low confidence (N)" (native disclosure); they keep Yes/No individually, are excluded from select-all and bulk approve, and keep the caution icon + text. The routine card no longer carries a caution flag.
Acceptance: distribution fixture from S1 yields the expected split; select-all count excludes the disclosure items; the queue-position counter still reads "x of N" over the whole set.

### Slice S5: duplicate-pixel-guard (conditional on S1)

Only if S1 confirms same-photo rows reach the queue.
Closes: R2 (score meaning). Canon: EVAL-16, HAI-08, DATA-14.
Design decision (binding): if the producer is the service, suppress the suggestion server-side (same media hash ⇒ not identity evidence) with a rg-015-clean reason; if purely smoke debris on the fir tenant, record "operator purge" in the decision and skip this slice.
Acceptance: either a service/PHP test pinning the suppression, or the decision recording that the cause is fixture-only.

### Slice S6: reference-enrichment (optional)

Only if S2/S3 request-count tests show the member fetch is too heavy, or S1 shows the producer emits a score for an empty reference set.
Closes: R1 (server invariant). Canon: rg-015, API-08.
Design decision (binding): the pending-suggestion payload gains `reference_faces[]` (≤ 6, thumb URLs only) or withholds `similarity` when the reference set is empty; never `count(payload)` guesses. Contract doc and controller test land in the same slice.
Acceptance: contract test plus PHP controller test; client falls back to S2 when the field is absent.

### Slice S7: maps-and-browser-check

Update the docs and verify on screen.
Closes: all above. Canon: LAY-24, INT-22.
Design decision (binding): edit `workbench-review-queue.md` (suggestion card job, evidence strip, low-confidence disclosure) and the 2-pane JSON/`.md` in the same commit; operator-vocabulary words only.
Acceptance: `make lint-ux-maps` green; browser walk of cards 1/2/5 recorded in the handoff decision; slice-complete decision per `docs/workbay/templates/slice-complete-template.md`.
