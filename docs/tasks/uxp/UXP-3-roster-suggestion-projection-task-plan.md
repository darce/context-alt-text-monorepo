# UXP-3. Suggestion Projection Contract + Roster Typeahead + Casing Rider

> **Metadata**
>
> - **Date**: 2026-07-17
> - **Author**: claude-fable-5
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy); recognition service is **read-only context** (no contract changes — FBT-1 wave rule)
> - **Task ID**: `UXP-3`
> - **Target Branch**: `feature/uxp-3`
> - **Review Coverage Target**: 2 (each slice: one local + one remote-grok reviewer)

---

## Objective

Three ordered slices. **Slice 0** binds B10a: one suggestion-projection contract — a client-side read-model with a single eligibility predicate, a single ranking comparator, one query-key family, and an enumerated invalidation map — so {inline prompt, curation dropdown, review cards} stop disagreeing about the same identity. **Slice 1** delivers B5: the "Name this person" typeahead draws from roster persons ∪ labeled clusters with source badges, and the pin control stops occluding faces. **Slice 2** delivers B6: a case-only rename ("bob"→"Bob") saves instead of silently bailing.

Slice 0 alone unblocks E21-5 ④ (bands as filters over the projection) and UXP-5 (invalidation wiring). It ships first and independently.

## Intake

- **Wave binding**: `docs/scopes/fbt-1-frontend-bug-triage-scope.md` (r2 @`e059d9c5`) — UXP-3 row: slice 0 = B10a contract (5 decisions), slice 1 = B5, slice 2 = B6.
- **Original task scope**: `docs/scopes/uxp-ux-pass-decomposition.md` § UXP-3 (UXA-07 pin, UXA-08 typeahead).
- **Source assessment**: `docs/assessments/current/frontend-workbench-bug-triage-ux-pass-2026-07-17.md` (B5, B6, B10a; on `feature/fbt-1`).
- **Start gate (PA-01)**: batch-list sufficiency probe **passed** — FBT-1 decision `fable_fbt1_batch_list_sufficiency_probe_pass` (#2612). Refinement recorded below (§ Probe refinement).
- **Key decisions**: FBT-1 operator intake (`fable_fbt1_intake_and_assessment_v2`): B10b bands only, no numeric slider; overlays scope; media table always visible. Findings referenced by ID only (Review Findings Placement rule).
- **Not-Doing**:
  - **No recognition-service (Python) contract changes.** The wave stops and escalates if one becomes unavoidable. One deliberate exception class: *test-only* additions pinning existing behavior (flagged per site below, adjudicated at planning review).
  - **E21-9 person write-through: stays out of wave** — the pull-in decision assigned to this authoring is made here: **out**. Rationale: the chooser surfacing roster names (slice 1) is independently shippable and reversible; write-through touches the person projection's write path and same-label grouping server work that E21-9 already owns as a coherent unit. Residual (scope criterion 6): naming via the chooser does not guarantee person-graph write-through; accepted and operator-visible.
  - Band UI, bulk chrome, multi-select (E21-5 ①–④). Slice 0 exports what ④ consumes; it builds no band logic.
  - Overlay surfaces (UXP-5). Slice 1's naming path is what UXP-5's "?" deep-links into.
  - Retiring the per-identity route or its proxy leg after migration — recorded as a UXP-2-absorbable follow-up, not done here.

## Problem Statement

**B10a — three surfaces, three answers.** The same identity can show different near-miss suggestions (or none) across the inline prompt, the curation dropdown, and the review cards, and acting on one surface does not clear the others. Static recon (assessment, confirmed against the tree):

| Surface | Hook | Transport (main today) | Eligibility applied | Ranking |
| --- | --- | --- | --- | --- |
| Inline prompt | `inlineSuggestionBatch.ts` (main) → **`useInlineSuggestionBatch.ts` after UXP-2** | pages `GET /suggestions` (main) → **`GET /identities/suggestions` batch (UXP-2)** | truthy `cluster_label` (incl. auto `cluster-*`) | top-1 by similarity |
| Curation dropdown | `useClusterSuggestionsLoader.ts` → `useClusterSuggestions.ts` | `GET /identities/{id}/suggestions` `top_k=5` | truthy label (incl. `cluster-*`), pending only | similarity desc |
| Review cards | `useSuggestionReviewQueries.ts` (page 25) | `GET /suggestions` | **stricter**: `user_confirmed=True` + human label (no `cluster-*`) + resurrects stale-accepted rows | `confidence_score` desc nulls-last, `created_at` desc |

Three query-key families (`suggestions.pending`, `suggestions.identityFor`, `suggestions.inlineBatch`) invalidate independently; accept/reject on one surface leaves the others stale.

**B5 — the naming flow ignores the roster.** `ClusterLabelingPanel` label search hits `listRecognitionClusters({labeled_only: true})` only; `useRosterEntries` (`useRosterHooks.ts:14`) is never consulted. A person the operator already curated does not surface when naming a new cluster; free-text create wins by default. Duplicate labels fall through silently.

**B6 — case-only renames are silently dropped.** `useClusterSaveAction.ts` bails with `cancelEditing()` when `currentLabel?.toLowerCase() === trimmed.toLowerCase()` (the dirty check at the top of the save action), so "bob"→"Bob" exits with no mutation, no feedback. Two later case-insensitive comparisons (the matched-cluster bail and the merge-target match) conflate "same label, different case" with "no change".

**UXA-07 — the pin control occludes faces.** `ClusterPreview.tsx` renders a pin toggle over the compact card's face thumbnail with no dedicated styling.

## Probe refinement (supersedes nothing; sharpens #2612)

The FBT-1 probe evaluated main's transport (client paging of `GET /suggestions`, 500×4 backstop). Since then, **`feature/uxp-2` landed the designed transport**: `GET /identities/suggestions` (per-identity top-k, `ROW_NUMBER` partitioned by identity, response ≤ `len(ids) × top_k` by construction) through slices 3a/3b (`b7da9655`…`5dd5cd7b`). Consequences for this plan:

1. The identity-keyed legs are bounded per identity by construction — the 2000-row completeness bound in #2612 applies **only** to the review-queue leg, where it is the page size the user asked for, not a correctness risk.
2. **UXP-2 must merge before slice 0b (consumer migration) lands.** Slice 0a (contract module + tests) has no dependency. If UXP-2 has not merged when 0b starts: stop and coordinate — do not re-implement its transport on this branch.
3. UXP-2's plan deliberately gave the batch endpoint *per-card filter parity* (truthy label, `cluster-*` passes) and recorded the eligibility unification as a follow-up. **This plan is that follow-up**: the projection applies the stricter predicate client-side (D2), which is expressible on every leg.

## Constraints

- **Greenfield** (CLAUDE.md): delete-over-flag; consumers migrate in the same slice as the contract they consume.
- **Wave rule**: recognition-service contract untouched. Frontend + PHP proxy only.
- **UXP-2 in-flight**: its batch endpoint, `useInlineSuggestionBatch`, cooldown gating, and honored `top_k` are the substrate for slice 0b. Ordering per § Probe refinement.
- Status/eligibility values centralized (sr-007); assertion helpers not used on API data (sr-005).
- Prefer symbol names over line anchors — lines drift across the UXP-2 merge.

## Terminology

- **Projection**: the client-side read-model of pending assignment suggestions — one predicate, one comparator, one key family. Not a cache layer, not a new endpoint: a module that every suggestion consumer goes through.
- **Eligibility predicate**: which suggestion rows any surface may show.
- **Identity-keyed legs**: transports answering "suggestions for identity X" (batch + per-identity routes).
- **Review-queue leg**: the row-paginated `GET /suggestions` transport feeding the review cards.

## Contract and Boundary Impact

| Boundary | Owner | Current | Change | Verification |
| --- | --- | --- | --- | --- |
| `suggestionProjection` module (**new**) | frontend | three divergent policies | single predicate + comparator + keys + invalidation map; exported for E21-5 ④ and UXP-5 | contract tests + three-surface matrix fixture |
| `queryKeys.suggestions.*` | frontend | `pending`/`identityFor`/`inlineBatch` invalidate independently | all assignment-suggestion reads keyed under one projection root; merge/name families stay separate (different domain objects) | invalidation tests per event |
| Curation dropdown eligibility | frontend | shows auto `cluster-*` targets | **deliberate behavior change**: converges on curated targets (API-09 reasoning below) | dropdown test: `cluster-*` fixture row excluded |
| Proxy `threshold` param on per-identity route | proxy (PHP) | proxy sends `threshold`; route accepts `min_confidence` — silently ignored (UXP-2 follow-up finding) | **drop the dead param** (proxy-only; no behavior change since it never bound) | PHP test: forwarded query contains no `threshold` |
| Recognition service | python | — | **no change**. Optional test-only rider: pin `user_confirmed = bool(label)` labeling invariant (`cluster_mutations.py` § `apply_label`) | flagged for planning review; drop if contested |

## Proposed Solution — Slice 0: the five contract decisions

**D1 — Source of truth: a client-side projection over two sanctioned legs.** The projection module owns policy; transports stay dumb. Identity-keyed legs use UXP-2's batch endpoint (dropdown migrates to it with a single-id call — one route family for identity-keyed asks); the review-queue leg keeps row pages (its cards need row enrichment — media URLs, bboxes, suggested-label inference — that the match shape lacks; UXP-2's plan established these are different domain questions, [API-10]). No recognition-service change. The projection is where the two legs' rows are normalized into one `ProjectedSuggestion` type.

**D2 — Eligibility and ranking: the server's own canonical rule, applied client-side everywhere.** Predicate = `is_eligible_cluster` semantics (v4.12.0, `application/suggestions/eligibility.py`): human label — truthy AND not `cluster-`-prefixed. `user_confirmed` is not in any response payload, and is not needed client-side: labeling sets `user_confirmed = bool(label)` (`cluster_mutations.py`), and suggestion *creation* is already gated by `is_eligible_cluster` (`service.py`, `refresh_service.py`) — so human-label is the client-observable projection of confirmed-ness; divergence is possible only on legacy rows, which the predicate excludes anyway. Ranking comparator = `representative_similarity` desc, `created_at` desc tie-break — identical to UXP-2's `ROW_NUMBER` ordering and the per-identity route's stable sort, so client ranking agrees with server ranking on every leg. **No threshold**: no client-side confidence floor (parity with today's visible behavior); bands arrive at E21-5 ④ as *filters over* the projection. The dead proxy `threshold` param is dropped.

- *Deliberate visible change* ([API-09] — changed behavior needs reasoning, not waving through): inline prompts and dropdown entries targeting auto-labeled `cluster-*` clusters stop rendering. That is the point of B10a — those targets never appear on the review queue, and "Is this cluster-1234?" is not an actionable question (the per-identity route's own docstring says so). UXP-2 preserved them for filter-parity within a network-discipline task and named the unification a follow-up; this is it.
- *Stale-accepted repair rows* (review-queue leg resurrects accepted-without-membership as pending): **review-queue-exclusive by decision.** Identity-keyed legs cannot see them (resolution ≠ pending) and no frontend/proxy change can add them without a service change. They are repair affordances, not near-miss suggestions; criterion 2 parity is scoped to pending suggestions. A contract test pins the exclusion so it stays chosen rather than accidental.

**D3 — One query-key family.** All assignment-suggestion reads move under a projection root (`queryKeys.suggestions.projection.*`): `identityBatch(ids)` and `reviewPage(offset)` leaves. `mergePending` / `namePending` remain separate families — different domain objects with their own lifecycles. `identityFor` and `inlineBatch` keys are deleted with their consumers (greenfield).

**D4 — Invalidation events, enumerated.** Every event below invalidates the projection root (one rule, no per-surface lists). Events: suggestion accept; suggestion reject; exclusive accept (accept-one-reject-rest); bulk accept; cluster label set/clear (eligibility flips); cluster merge; cluster dismiss (`dismissCluster`); scan/recompute completion (new suggestion rows). Cross-family: label set/clear and merge also invalidate the clusters family (existing behavior, kept). Contract tests fire each mutation and assert exactly the projection root invalidates. This enumerated map is the input UXP-5 wires "x"/"?" into.

**D5 — Migration order** (each step green before the next):
1. **0a — contract module + tests.** `suggestionProjection.ts`: `ProjectedSuggestion` type, `isEligible`, `compareSuggestions`, key family, invalidation map + `invalidateSuggestionProjection(queryClient)` helper. Three-surface matrix fixture (rows: multi-suggestion identity; `cluster-*` target; unlabeled target; tied similarities; stale-accepted row) exported for reuse by E21-5's consumer harness (scope criterion 2 owner).
2. **0b-1 — inline leg** (post-UXP-2 merge): `useInlineSuggestionBatch` adopts projection keys + predicate (client-side `cluster-*` exclusion — the visible change) + comparator.
3. **0b-2 — dropdown leg**: `useClusterSuggestionsLoader` swaps `fetchIdentitySuggestions` for a single-id batch call through the projection; `useClusterSuggestions` consumes `ProjectedSuggestion`; `identityFor` key deleted.
4. **0b-3 — review-queue leg**: `useSuggestionReviewQueries.assignmentQuery` moves to `projection.reviewPage`; `buildSuggestionReviewItems` applies predicate (idempotent — server already filters stricter-or-equal) + comparator for per-identity grouping.
5. **0b-4 — invalidation sweep**: all accept/reject/bulk/label/merge/dismiss mutation sites route through `invalidateSuggestionProjection`.

## Proposed Solution — Slice 1: roster-union typeahead + pin removal (B5, UXA-07)

One suggestion source for "Name this person": **roster persons ∪ labeled clusters**, deduped case-insensitively, roster entries listed first ([COG-02] — recognition over recall: the operator sees known names instead of re-typing them). Each entry carries a source badge (person vs cluster label) — same look only for same behavior ([PERC-02]). Filter before slicing (the full union is filtered by the typed prefix, then truncated — no "known name missing because the slice happened first"). Selecting a roster person routes through the existing naming path with the person's canonical casing. Duplicate-label handling in `ClusterLabelingPanel` becomes **blocking-with-warning**: an exact-duplicate label surfaces "this name is in use" inline at the field ([FORM-05]) with an explicit merge-or-rename choice — no silent fallback to create.

Pin control: removed from `ClusterPreview` compact card (it overlaps the face thumbnail and has no styling — a control occluding the content it acts on). The `is_pinned` data and mutation stay; relocation to cluster detail is a product decision explicitly deferred (original UXP-3 scope). No dangling prop plumbing left behind (greenfield).

A11y: the typeahead is a combobox with accessible names on entries incl. their source ([A11Y-04]); result-count changes announced via live region ([A11Y-21]); badges never color-only ([A11Y-06], sr-004).

Roster data via existing `useRosterEntries` (60s poll, cooldown-gated) — no new transport.

## Proposed Solution — Slice 2: case-sensitive dirty check (B6)

The save action's three comparisons get distinct semantics instead of one lowercased blur:

1. **Dirty check** (bail-out): becomes **exact** compare. "bob"→"Bob" is dirty and proceeds; "Bob"→"Bob" still no-ops.
2. **Merge-target match** (does the typed label name another existing cluster?): stays case-insensitive — merging into "Bob" when typing "bob" is correct linking behavior — but **excludes case-only self-match**: when the matched cluster IS the editable cluster's label differing only by case, the action is a rename, not a merge (the `filterEditableClusterMatch` exclusion already covers the same-id case; the fix makes the post-`findClusterByLabel` bail exact-compare against `currentLabel` so a case-only rename falls through to the label PATCH).
3. **Feedback**: a successful case-only rename shows the saved state inline at the field ([PERC-05] — feedback at the fovea; [FORM-05]) and is announced ([A11Y-21]). The correction reaches the stored label, not just the display ([HAI-02]).

Tests characterize current behavior first ([TEST-03]), then pin: "bob"→"Bob" issues the label mutation; "Bob"→"Bob" no-ops; "bob" typed while a *different* cluster "Bob" exists routes to the merge path unchanged; each new test watched failing once ([TEST-06]).

## Files and Surfaces to Change

| Slice | File : symbol | Change |
| --- | --- | --- |
| 0a | `js/admin/pages/workbench/identity-clusters/suggestionProjection.ts` (**new**) | predicate, comparator, `ProjectedSuggestion`, invalidation helper |
| 0a | `js/admin/api/queryKeys.ts` : `suggestions` | add `projection.*`; `pending`/`identityFor`/`inlineBatch` deleted in 0b as consumers migrate |
| 0a | `identity-clusters/__tests__/suggestionProjection.fixtures.ts` (**new**) | three-surface matrix fixture (exported) |
| 0b | `identity-clusters/useInlineSuggestionBatch.ts` (UXP-2's) | projection keys + predicate + comparator |
| 0b | `identity-clusters/useClusterSuggestionsLoader.ts`, `useClusterSuggestions.ts` | single-id batch via projection; `fetchIdentitySuggestions` consumer removed |
| 0b | `identity-clusters/useSuggestionReviewQueries.ts`, `suggestionReviewItems.ts` | projection keys; predicate + comparator in item building |
| 0b | mutation sites: `useSuggestionReviewMutations.ts`, `useClusterConfirmSuggestion.ts`, `clusterApiMutations.ts` consumers (label/merge/dismiss), scan-completion invalidators | route through `invalidateSuggestionProjection` |
| 0b | `src/api/class-suggestions-controller.php` : per-identity forward | drop dead `threshold` param |
| 1 | `identity-clusters/useClusterSuggestionsLoader.ts` : label search leg | union with roster entries + badges, filter-before-slice |
| 1 | `identity-clusters/ClusterLabelingPanel.tsx` | combobox union render, badges, blocking duplicate warning |
| 1 | `identity-clusters/ClusterPreview.tsx` | remove pin toggle + its props |
| 2 | `identity-clusters/useClusterSaveAction.ts` | exact dirty check; case-only-rename fall-through; saved feedback |
| tests | TS suites per slice; PHP proxy test for `threshold` removal; optional Python test-only invariant rider | per-slice proof below |

## Related Files (not modified)

| File : symbol | Note |
| --- | --- |
| `recognition/application/suggestions/eligibility.py` : `is_eligible_cluster` | the canonical predicate the client mirrors; source of D2 |
| `recognition/.../curation/cluster_mutations.py` : `user_confirmed = bool(label)` | the invariant making human-label ⟺ confirmed client-observable |
| `recognition/.../repositories/suggestion_repository.py` : `list_pending_with_details` | review-queue leg semantics (stricter filter + stale-accepted resurrection) |
| UXP-2 branch: `routers/suggestions.py` : `list_identities_suggestions` | the batch transport slice 0b consumes after merge |
| `js/admin/hooks/useRosterHooks.ts` : `useRosterEntries` | slice 1's roster source, unchanged |

## Verification Strategy

- `npm --prefix apps/prototype-wp-alt-context test` (all slices)
- `composer --working-dir=apps/prototype-wp-alt-context test` (slice 0b `threshold` drop)
- `make test` only if the optional Python invariant rider survives planning review
- `make check-remote` at each slice's committed HEAD (remote gate; no local full-suite runs)
- Contract proof (slice 0): the three-surface matrix — for every fixture identity, all three consumers derive the **same** top suggestion (or same absence); each invalidation event clears exactly the projection root; stale-accepted row appears on the review leg only (pinned as chosen).
- Manual (dev recognition only): one identity with a near-miss → same suggestion visible in inline prompt, dropdown, review card; accept in review card → prompt and dropdown clear without reload; "bob"→"Bob" saves with visible confirmation; roster person surfaces in typeahead before free-text create.

## Slice Delivery

### Slice 0: suggestion-projection contract (B10a)

**Goal**: one predicate, one comparator, one key family, one invalidation rule — consumed by all three surfaces.

Steps 0a → 0b-1..4 per D5 (0a has no UXP-2 dependency; 0b gated on UXP-2 merge — stop and coordinate if unmet).

Proof: contract tests over the matrix fixture (multi-suggestion identity, `cluster-*` exclusion on every surface, tie-break agreement, stale-accepted review-only); invalidation tests per D4 event; dropdown test pinning the deliberate `cluster-*` disappearance; PHP test pinning `threshold` gone from the forwarded query.

### Slice 1: roster-union typeahead + pin removal (B5)

**Goal**: known names always surface before free-text create; no control occludes a face.

Proof: union ordering (roster first), case-insensitive dedupe, filter-before-slice (fixture where the match is beyond the slice boundary), blocking duplicate warning path, badge + combobox a11y assertions, pin control absent, roster-empty and roster-error states degrade to today's cluster-only search ([A11Y-24] state matrix: loading/empty/error each render and announce).

### Slice 2: casing rider (B6)

**Goal**: case-only renames save with feedback; merge semantics unchanged.

Proof: the four-case test grid (§ slice 2) + characterization-first ordering; announcement assertion.

## Consolidated Checklist

### Context and Ownership

- [ ] Frontend rules + testing-typescript loaded; UXP-2 plan §§ batch-endpoint/filter-parity read before touching its surfaces.
- [ ] UXP-2 merge state checked at 0b start; coordination decision recorded if unmerged.

### Slice 0

- [ ] `suggestionProjection.ts` exports predicate, comparator, type, keys, invalidation helper (sr-007: one canonical definition).
- [ ] Matrix fixture exported for E21-5 reuse.
- [ ] All three consumers migrated; `identityFor` + `inlineBatch` keys deleted; no consumer left on `fetchIdentitySuggestions`.
- [ ] Every D4 event routes through the invalidation helper; tests assert exact key scope.
- [ ] Deliberate `cluster-*` visibility change pinned by test and named in the slice's handoff decision.
- [ ] Proxy `threshold` param dropped with PHP test.
- [ ] Route-retirement follow-up (per-identity route consumer-less) recorded for UXP-2 absorption, not implemented.

### Slice 1

- [ ] Union source with badges; roster preferred; filter-before-slice.
- [ ] Duplicate label blocks with inline warning + explicit choice; no silent create.
- [ ] Pin control removed with its prop plumbing; mutation/API untouched.
- [ ] Combobox a11y: names, live-region count announcements, non-color badges.
- [ ] E21-9 pull-in decision (out) recorded in handoff at slice close.

### Slice 2

- [ ] Exact dirty check; case-only rename mutates; merge path preserved (four-case grid).
- [ ] Inline saved/error feedback + announcement.
- [ ] Characterization tests green before the change ([TEST-03]); new tests watched failing ([TEST-06]).

## Review Readiness

- [ ] Each slice: `/branch-review` with findings in MCP; remote grok as second reviewer at slice 0 and before merge.
- [ ] Handoff decision per slice (record + notify), `render_handoff(kind='dashboard')` after writes.
- [ ] Pre-merge gate: `handoff_close_check(enforce=True)` with fresh test evidence at HEAD.

## Success Criteria

- [ ] Same identity ⇒ same near-miss suggestion (or none) across inline prompt, curation dropdown, review cards; accept/reject on any surface clears the others (scope criterion 2; matrix fixture is the evidence).
- [ ] No surface shows an auto `cluster-*` suggestion target; the change is deliberate, tested, and recorded.
- [ ] E21-5 ④ and UXP-5 can consume the projection (exported predicate/keys/invalidation map + fixture) without re-deriving policy.
- [ ] Roster persons appear in "Name this person" and are preferred over free-text create (criterion 6; write-through residual accepted and recorded).
- [ ] "bob"→"Bob" saves with inline feedback (criterion 6).
- [ ] No pin control overlaps a face thumbnail.
- [ ] Zero recognition-service contract changes on this branch.

## Heuristics cited

Canon @`bcc23fa`+ (`~/Development/heuristics-canon/lexicons/`): [COG-02], [PERC-02], [PERC-05], [FORM-05], [INT-06], [HAI-02], [A11Y-04], [A11Y-06], [A11Y-21], [A11Y-24] (interaction-ux/accessibility); [API-09], [API-10], [TEST-03], [TEST-06] (engineering); sr-004/005/007 (repo constitution). Each ID verified against the lexicon row before citation.
