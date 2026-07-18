# UXP-3. Suggestion Projection Contract + Roster Typeahead + Casing Rider

> **Metadata**
>
> - **Date**: 2026-07-17 (r4 — heuristics-alignment rerun vs canon `b67b484` (runs #458/459, conditional_pass) folds `UXP-3-PR-21..27`: [API-09] citation misuse re-attributed, predicate-flip commit sequencing, duplicate-guard target naming + outcome sample, canon pin. r3 folded run `-r2` conditions `UXP-3-PR-16..20`; r2 revised `UXP-3-PR-01..15` after run `-r1` (fail))
> - **Author**: claude-fable-5
> - **Project**: prototype-wp-alt-context (admin SPA + PHP proxy); recognition service is **read-only context** (no contract changes — FBT-1 wave rule)
> - **Task ID**: `UXP-3`
> - **Target Branch**: `feature/uxp-3`
> - **Review Coverage Target**: 2 (each slice: one local + one remote-grok reviewer)

---

## Objective

Three ordered slices. **Slice 0** binds B10a: one suggestion-projection contract — a client-side read-model with a single eligibility predicate, a per-leg-honest ranking rule, one query-key family, and an enumerated invalidation map — so the surfaces that display a per-identity top match stop disagreeing, and every suggestion action clears every surface. **Slice 1** delivers B5: both naming surfaces draw from roster persons ∪ labeled clusters with source badges (each is single-source today, in opposite directions), and the pin control stops occluding faces. **Slice 2** delivers B6: a case-only rename ("bob"→"Bob") saves instead of silently bailing, on both entry points.

Slice 0 alone unblocks E21-5 ④ (bands as filters over the projection) and UXP-5 (invalidation wiring). It ships first and independently.

## Intake

- **Wave binding**: `docs/scopes/fbt-1-frontend-bug-triage-scope.md` (r2 @`e059d9c5`) — UXP-3 row: slice 0 = B10a contract (5 decisions), slice 1 = B5, slice 2 = B6.
- **Original task scope**: `docs/scopes/uxp-ux-pass-decomposition.md` § UXP-3 (UXA-07 pin, UXA-08 typeahead).
- **Source assessment**: `docs/assessments/current/frontend-workbench-bug-triage-ux-pass-2026-07-17.md` (B5, B6, B10a; on `feature/fbt-1`).
- **Start gate (PA-01)**: batch-list sufficiency probe **passed** — FBT-1 decision `fable_fbt1_batch_list_sufficiency_probe_pass` (#2612), refined in § Probe refinement.
- **Key decisions**: FBT-1 operator intake (`fable_fbt1_intake_and_assessment_v2`); planning-review r1 verdict `fable_planning_review_uxp3_r1_fail` (#2615). Findings referenced by ID only (Review Findings Placement rule).
- **Not-Doing**:
  - **No recognition-service (Python) contract changes.** The wave stops and escalates if one becomes unavoidable. No test-only riders on the service either (PR-15): the client contract is pinned against fixtures only.
  - **E21-9 person write-through: stays out of wave** — the pull-in decision assigned to this authoring is made here: **out**. Rationale: the union chooser (slice 1) is independently shippable and reversible; write-through touches the person projection's write path and server-side same-label grouping that E21-9 owns as a coherent unit. Residual (scope criterion 6): naming via the chooser does not guarantee person-graph write-through; accepted and operator-visible.
  - Band UI, bulk chrome, multi-select (E21-5 ①–④). Slice 0 exports what ④ consumes; it builds no band logic. The **three-real-consumer integration harness is E21-5's proof obligation** (FBT-1 criterion 2 names both owners); UXP-3's proof is the projection unit matrix plus per-consumer hook tests.
  - Overlay surfaces (UXP-5). Slice 1's naming path is what UXP-5's "?" deep-links into.
  - Retiring the per-identity route `GET /identities/{id}/suggestions` and its proxy leg once consumer-less — recorded as a UXP-2-absorbable follow-up, not done here.

## Problem Statement

**B10a — three surfaces, three policies.** The same identity can show different near-miss suggestions (or none) across the inline prompt, the curation dropdown, and the review cards, and acting on one surface does not reliably clear the others.

**B5 — two naming surfaces, each missing the other's source.** The labeling panel offers roster persons only; the save-action/dropdown leg searches labeled clusters only. A known name reliably surfaces on at most one surface.

**B6 — case-only renames are silently dropped** at two entry points (free-text save and suggestion confirm).

**UXA-07 — the pin control occludes faces** on the compact card.

## Current State Analysis

Verified against `main` @`41d9db93` and `feature/uxp-2` @`5dd5cd7b` on 2026-07-17. Line anchors are orientation aids; symbols are the contract.

**Suggestion surfaces (B10a):**

| Surface | Hook | Transport | Read-time eligibility | Order |
| --- | --- | --- | --- | --- |
| Inline prompt | `inlineSuggestionBatch.ts` (main) → **`useInlineSuggestionBatch.ts` (UXP-2)** | pages `GET /suggestions` (main) → **`GET /identities/suggestions` batch, `top_k=1` (UXP-2)** | truthy `cluster_label` (incl. auto labels) | per-identity similarity desc, `created_at` desc — applied **server-side inside the window** (UXP-2 `ROW_NUMBER`) |
| Curation dropdown | `useClusterSuggestionsLoader.ts` → `useClusterSuggestions.ts` | `GET /identities/{id}/suggestions` (`top_k` sent by client but **dead on main** — the route declares no such param; honored only once UXP-2 merges) | truthy label, pending only | similarity desc (route sorts) |
| Review cards | `useSuggestionReviewQueries.ts` (page 25) | `GET /suggestions` | **stricter**: `user_confirmed=True` + human label (no `cluster-*`) + resurrects stale-accepted-without-membership as pending | **page selection**: `confidence_score` desc nulls-last, `created_at` desc; **client presentation**: `buildSuggestionReviewItems` re-sorts by `representative_similarity` and groups **per-cluster** (`suggested_cluster_id`), not per-identity |

Query keys: three independent families (`suggestions.pending`, `suggestions.identityFor`, `suggestions.inlineBatch`) plus `mergePending`/`namePending`. Cross-family invalidation wiring **exists and is live** (inventory in D4) but identity-keyed families are missing from most of it — accept/reject invalidates `pending` + `clusters.all` yet leaves `identityFor`/`inlineBatch` stale.

**Eligibility ground truth (backend, read-only):** suggestion **creation** is gated by `is_eligible_cluster` (`application/suggestions/eligibility.py`; called from `application/suggestions/service.py` and `refresh_service.py`): tenant match + `user_confirmed` + human label (not `cluster-*`). Read paths diverge: the review-queue SQL re-applies the strict filter; the identity-keyed routes check only truthy label. `user_confirmed` is **not** derivable from the label: `update_cluster` (`curation/cluster_mutations.py`) sets `user_confirmed = bool(label)` on the labeling path, but `cluster_merge.py` confirms targets unconditionally (label may remain `None`/auto), `split/executor.py` and `create_cluster_with_label` set it independently, and the auto-labeler writes `"Person N"` labels (default prefix `Person`, `application/settings/clustering.py`) **without** confirming. `user_confirmed` is also absent from every suggestion payload.

**Naming surfaces (B5):** `ClusterLabelingPanel.tsx` builds its Combobox options **exclusively** from `useRosterEntries()` (`personOptions`); `listRecognitionClusters` appears there only inside a duplicate lookup. The save-action/dropdown leg (`useClusterSuggestionsLoader.ts` `labelMatches`) searches **labeled clusters only** and never consults the roster. The panel's "Is this X?" `duplicateMatch` branch is keyed to a 409 conflict the backend never emits — the clusters PATCH (`clusters_topology.py`) has no duplicate-label check — so that branch is dead code.

**Casing (B6):** `useClusterSaveAction.ts` bails via `cancelEditing()` when `currentLabel?.toLowerCase() === trimmed.toLowerCase()`; two later case-insensitive compares route matched clusters. `useClusterConfirmSuggestion.ts` has the same silent case-insensitive no-op before `runMatchedAction`. The server-side label update itself is case-sensitive — the client bails are the only blockers.

**Pin (UXA-07):** `ClusterPreview.tsx` renders the toggle; `IdentityClusterItem.tsx` wires `handleToggleRepresentativePin` / `isPinning={mutations.isPinningRepresentative}` into it.

## Probe refinement (sharpens FBT-1 #2612)

The FBT-1 probe evaluated main's transport. Since then `feature/uxp-2` landed the designed transport: `GET /identities/suggestions` (per-identity top-k, `ROW_NUMBER() OVER (PARTITION BY identity_id ORDER BY representative_similarity DESC, created_at DESC)`, response ≤ `len(ids) × top_k` by construction). Consequences:

1. Identity-keyed reads are bounded per identity by construction; the review-page bound is just its page size.
2. **UXP-2 must merge before slice 0b lands.** Slice 0a (contract module + tests) has no dependency. If UXP-2 has not merged when 0b starts: stop and coordinate — do not re-implement its transport here.
3. UXP-2 deliberately gave the batch endpoint per-card filter parity (truthy label) and recorded eligibility unification as a follow-up. **This plan is that follow-up**, executed client-side under the constraint that the server filters *inside* the `top_k` window (see D2's fetch-depth rule).

## Constraints

- **Greenfield** (CLAUDE.md): delete-over-flag; consumers migrate in the same slice as the contract they consume; dead branches deleted, not preserved.
- **Wave rule**: recognition-service untouched (code *and* tests). Frontend + PHP proxy only.
- **UXP-2 in-flight**: its batch endpoint, `useInlineSuggestionBatch`, cooldown gating, and honored `top_k` are the substrate for slice 0b.
- Eligibility/status values centralized (sr-007); assertion helpers not used on API data (sr-005); badges never color-only (sr-004, [A11Y-06]).
- Envelope fields never fabricated (rg-015) — drives the per-leg comparator rule in D2.

## Workflow Principles

- **One policy module, dumb transports.** Predicate, comparator, keys, and invalidation live in `suggestionProjection.ts`; hooks consume it ([API-10]: the interface is its own artifact).
- **Honesty over symmetry.** Where a leg cannot express the full policy (no `created_at`, no `user_confirmed` on the wire), the contract states what that leg trusts the server for, instead of claiming client-verified parity it cannot deliver (rg-015).
- **Behavior changes are named, tested, and recorded, and never mixed into a restructuring diff** ([REF-05] — two hats: a commit restructures or changes behavior, not both).
- **Characterize before migrating** ([TEST-03]); every new test watched failing once ([TEST-06]).

## Terminology

- **Projection**: the client-side read-model of pending assignment suggestions — one predicate, per-leg ranking rule, one key family, one invalidation map. A module every suggestion consumer goes through; not a cache layer, not a new endpoint.
- **Identity-keyed legs**: transports answering "suggestions for identity X" (UXP-2 batch; legacy per-identity route until 0b-2 retires its last consumer).
- **Review-queue leg**: the row-paginated `GET /suggestions` transport feeding the review cards. A work-queue over rows, **not** a per-identity top-match surface.
- **Human-labeled target** (`isHumanLabeledTarget`): a suggestion row whose `cluster_label` is truthy and does not start with `cluster-`. This is the client-observable slice of `is_eligible_cluster`; it is deliberately **not** claimed equivalent to it (see D2).
- **Top match**: for one identity, the first eligible row in server order from an identity-keyed leg.

## Target Outcome

Every surface that shows a per-identity top match derives it from one projection: same predicate, same fetch depth, same trust in server order — so the inline prompt and the curation dropdown can no longer disagree. The review queue remains a row work-queue with its own stricter server filter, and every accept/reject/label/merge/dismiss action, from any surface, invalidates the shared projection so all surfaces converge within one refetch. Both naming surfaces offer roster persons ∪ labeled clusters with source badges and a pre-save duplicate guard. Case-only renames save with visible feedback from both entry points. E21-5 ④ and UXP-5 consume the exported predicate, keys, invalidation map, and fixture without re-deriving policy.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/backend-php-guidelines.md` (proxy touch), `docs/workbay/rules/component-architecture-patterns.md`.
- Heuristics: `heuristics-canon` `interaction-ux.md` ([COG-02], [PERC-02], [PERC-05], [FORM-05], [HAI-02], [INT-06], [INT-07]), `accessibility.md` ([A11Y-04], [A11Y-06], [A11Y-21], [A11Y-24]), `engineering.md` ([REF-05], [API-10], [TEST-03], [TEST-06]); repo constitution sr-004/005/007, rg-015. Every citation site re-verified against its lexicon row at canon `b67b484` (2026-07-17 adversarial rerun, review runs #458/#459).
- Handoff/MCP: task ref `UXP-3`; planning findings `UXP-3-PR-*`; wave decisions #2612/#2613/#2615 and FBT-1 intake decisions.
- Adjacent plans: UXP-2 task plan (`feature/uxp-2:docs/tasks/uxp/UXP-2-network-discipline-task-plan.md`) §§ batch endpoint, filter parity, wire format.

## Contract and Boundary Impact

| Boundary | Owner | Current | Change | Verification |
| --- | --- | --- | --- | --- |
| `suggestionProjection.ts` (**new**) | frontend | three divergent policies | predicate + per-leg ranking rule + `ProjectedSuggestion` + keys + invalidation map; exported for E21-5 ④ / UXP-5 | projection unit matrix + per-consumer hook tests |
| `queryKeys.suggestions.*` | frontend | `pending`/`identityFor`/`inlineBatch` invalidate independently | assignment reads under one `projection` root; `mergePending`/`namePending` stay separate **but their live cross-family wiring is preserved per D4** | invalidation tests per event |
| Identity-keyed fetch depth | frontend | inline `top_k=1`; dropdown top-5 | one shared `PROJECTION_TOP_K = 5` for **all** identity-keyed reads (PR-01) | depth test + window-residual fixture |
| Dropdown eligibility | frontend | shows any truthy-label target | **deliberate behavior change**: auto-label targets (`cluster-*`) stop rendering on identity-keyed surfaces (greenfield delete-over-flag; reasoning in D2; lands in its own named commit per D5) | dropdown + inline tests with `cluster-*` fixture rows |
| Proxy `threshold` param | proxy (PHP) | `class-suggestions-controller.php` sends `threshold` (default 0.6); the route accepts only `min_confidence` — silently ignored | **drop the dead param** (no behavior change; it never bound) | PHP test: forwarded query contains no `threshold` |
| Recognition service | python | — | **no change, no test riders** | n/a |

## Proposed Solution — Slice 0: the five contract decisions

**D1 — Source of truth, honestly scoped.** Per-identity **top-match truth lives on the identity-keyed legs** (UXP-2's batch endpoint), everywhere a top match is displayed. The **review queue is a work-queue over rows** — cluster-grouped, confidence-paged, server-filtered stricter — and is *not* required to contain any given identity's top match (a confidence-ordered page of 25 cannot guarantee that; PR-02). What unifies it with the rest is not row identity but **policy and reaction**: the same predicate applied idempotently, and every action on it invalidating the shared projection. Two defined, pinned divergences: (a) **stale-accepted repair rows** appear on the review queue only (their `resolution` ≠ pending excludes them from identity-keyed reads; no frontend change can add them, and they are repair affordances, not near-misses); (b) rows beyond the current review page. Both are queue-membership differences, never *conflicting top matches*.

**D2 — Eligibility and ranking.**

- *Predicate*: `isHumanLabeledTarget(row)` — truthy label ∧ not `cluster-`-prefixed — applied on **every** leg. This is deliberately **not** claimed equivalent to the server's `is_eligible_cluster` (PR-06): `user_confirmed` is not on any suggestion payload, and it is not implied by a human label (the auto-labeler writes `"Person N"` without confirming; merge confirms without labeling — see Current State). The design is sound for a narrower reason, stated so review can attack it: **suggestion creation is already gated by `is_eligible_cluster`** (`service.py`, `refresh_service.py`), so rows targeting non-eligible clusters are legacy or label-decay artifacts; and both read predicates (client and review-SQL) independently require a human label, so no surface ever shows what another surface's filter rejects *as its top match* — the client predicate is defense-in-depth over creation-time gating, not a re-derivation of confirmed-ness. Residual, pinned by fixture: a legacy row targeting a labeled-but-unconfirmed cluster (e.g. `"Person 3"`) would show on identity-keyed surfaces and not on the review queue — a queue-membership difference per D1, bounded to rows creation-gating already forbids.
- *Fetch depth* (PR-01): the batch endpoint filters *inside* the `top_k` window with the looser predicate, so post-window client filtering at `top_k=1` could blank a surface whose #1 row is ineligible. Therefore **all identity-keyed reads share `PROJECTION_TOP_K = 5`**: fetch 5, filter client-side, surface top-1 (inline) or the list (dropdown). Residual, stated: an identity whose first 5 server-ranked rows are all ineligible while a 6th is eligible renders no prompt — possible only for rows creation-gating forbids (legacy), pinned by a fixture row and accepted; raising the constant is the tuning knob if it ever fires in practice.
- *Ranking* (PR-05): per-leg. Identity-keyed legs **trust server order** — the window already ranks `representative_similarity DESC, created_at DESC`; the payload has no `created_at`, so the client must not re-derive or fabricate the tie-break (rg-015). The client keeps arrival order after filtering. The review leg, whose rows do carry `created_at`, uses the exported `compareSuggestions` (similarity desc, `created_at` desc) for presentation. The matrix fixture's tied-similarity case asserts: identity legs = server order preserved; review leg = comparator order.
- *Threshold*: none, on any surface (parity with today's visible behavior); bands arrive at E21-5 ④ as filters over the projection. The dead proxy `threshold` param is dropped.
- *Deliberate visible change* (greenfield delete-over-flag, § Constraints; isolated in its own named commit per [REF-05] — see D5): identity-keyed surfaces stop rendering `cluster-*` targets. Reasoned, not waved through: such targets never appear on the review queue (server filter), UXP-2 preserved them only for within-task filter parity and named the unification a follow-up, and "Is this cluster-1234?" is not an actionable curation question. Pinned by test; named in the slice's handoff decision.

**D3 — One query-key family for assignment suggestions.** All assignment-suggestion reads move under `queryKeys.suggestions.projection.*`: `projection.all`, `projection.identityBatch(idsKey)`, `projection.reviewPage(offset)`. `identityFor` and `inlineBatch` are deleted with their consumers; `pending` is deleted after 0b-3 re-keys **both the reads and the optimistic-cache writes** (PR-08). `mergePending` / `namePending` remain separate families (different domain objects) — but *separate keys* does not mean *uncoupled events*: their live cross-family wiring is preserved explicitly in D4 (PR-04).

**D4 — Invalidation map: enumerated events × enumerated targets.** `invalidateSuggestionProjection(queryClient)` invalidates `projection.all`. The map below is the contract; "exact-scope" tests assert the **assignment-projection family** precisely and assert the *presence* of the kept cross-family calls (they never forbid them):

| Event | Assignment projection | Kept cross-family targets (live today, preserved) |
| --- | --- | --- |
| Suggestion accept / reject (exclusive-accept is a **server side-effect** of accept — `resolve_for_identity_exclusive` rejects siblings; there is no separate frontend site (PR-07). This is *why* accept must invalidate the whole projection, not one row) | ✓ | `clusters.all` (`useSuggestionReviewMutations`) |
| Bulk accept | ✓ | `mergePending`, `namePending` (`useSuggestionReviewMutations`) |
| Cluster label set/clear | ✓ | `mergePending`, clusters family (`useClusterMutations`, `ClusterLabelingPanel`) |
| Cluster merge | ✓ | `mergePending`, clusters family (`useClusterMutations`, `TopClustersSection`) |
| Cluster dismiss (`dismissCluster`) | ✓ | `mergePending` (`useClusterMutations` path) |
| Scan / recompute completion | ✓ (replaces `pending` refetch) | `mergePending` + `namePending` refetch (`useJobStateMachineEffects` — E15-23 "findings must visibly refresh" design) |
| Sync trigger | ✓ (via existing `suggestions.all` root, which `projection.*` nests under) | unchanged (`useSyncTrigger`) |

Full site inventory to sweep in 0b-4 (every `queryKeys.suggestions.*` read/write outside `queryKeys.ts`): `useSuggestionReviewQueries.ts` (reads), `useSuggestionReviewMutations.ts` (invalidations **and** optimistic `setQueryData`/`cancelQueries`/rollback on `pending()`), `useClusterMutations.ts:invalidateQueries`, `ClusterLabelingPanel.tsx` (post-merge invalidate), `TopClustersSection.tsx`, `ClusterReviewPanel.tsx`, `useJobStateMachineEffects.ts` (refetch trio + `suggestions.all`), `useSyncTrigger.ts` (×2), `useClusterSuggestionsLoader.ts` (`identityFor` read), `InlineSuggestionPrompt.tsx` (`inlineBatch` read). This table is the input UXP-5 wires "x"/"?" into.

**D5 — Migration order** (each step green before the next):

1. **0a — contract module + tests** (no UXP-2 dependency). `suggestionProjection.ts`: `isHumanLabeledTarget`, `compareSuggestions` (review-leg), `PROJECTION_TOP_K`, `ProjectedSuggestion` + adapters (below), key family, `invalidateSuggestionProjection`, the D4 event map as data. Matrix fixture exported for E21-5 (`suggestionProjection.fixtures.ts`): multi-suggestion identity; `cluster-*`-first-then-human identity (window-depth case); all-ineligible-window identity (residual case); labeled-but-unconfirmed `"Person N"` target (D2 residual); tied similarities (per-leg expectations); stale-accepted row (review-only).
   - `ProjectedSuggestion` (PR-12): `{ suggestionId, identityId, clusterId, label, similarity, identityCount?, createdAt?, enrichment? }` where `enrichment` (review-leg-only) carries media URLs / bboxes / `suggested_label*`; `identityCount` optional (batch has it, review rows may not). Adapters `fromIdentityMatch(identityId, match)` and `fromPendingRow(row)` — total functions, no fabricated fields (rg-015).
2. **0b-1 + 0b-2 — identity legs, one reviewable increment** (post-UXP-2 merge; co-shipped so no intermediate commit has inline filtered while the dropdown is not — PR-19): `useInlineSuggestionBatch` fetches at `PROJECTION_TOP_K`, filters via predicate, keys under `projection.identityBatch`, surfaces top-1; `useClusterSuggestionsLoader` swaps `fetchIdentitySuggestions` for a single-id batch call through the projection at the same depth; `useClusterSuggestions` consumes `ProjectedSuggestion[]`; `identityFor` key deleted. Inline and dropdown share transport, depth, predicate, and order by construction — the PR-01 divergence is structurally closed, tested on the window-depth fixture row. **Two commits inside the increment ([REF-05], PR-22): commit 1 is the structural migration (keys, transport, adapters, depth) preserving today's truthy-label eligibility on both surfaces so characterization tests hold; commit 2 is the named predicate flip to `isHumanLabeledTarget` on both surfaces together — the `cluster-*` visibility change lands and is tested in commit 2.** Both commits keep inline and dropdown consistent, so PR-19's co-ship constraint holds at every commit.
3. **0b-3 — review-queue leg**: `useSuggestionReviewQueries.assignmentQuery` → `projection.reviewPage(0)`; the **cache holds adapted `ProjectedSuggestion[]` (adapter in the `queryFn`), so optimistic filters match on `suggestionId`, not raw `id`** (PR-20); `buildSuggestionReviewItems` consumes `ProjectedSuggestion` (predicate applied idempotently — server already filters stricter) keeping its **per-cluster** grouping (PR-14) with `compareSuggestions` for presentation order; **optimistic paths re-keyed**: `setQueryData`/`cancelQueries`/rollback in `useSuggestionReviewMutations` move from `pending()` to `projection.reviewPage(0)` with a rollback-after-failed-accept test (PR-08); `pending` key deleted.
4. **0b-4 — invalidation sweep**: every site in the D4 inventory routes assignment-family invalidation through `invalidateSuggestionProjection` while keeping the enumerated cross-family calls; per-event tests assert the D4 table row exactly (assignment) and presence (cross-family).
5. **0b-5 — proxy cleanup**: drop the dead `threshold` from `class-suggestions-controller.php` per-identity forward, with a PHP test on the forwarded query args.

## Proposed Solution — Slice 1: two-way union typeahead + pin removal (B5, UXA-07)

Today each naming surface is single-source in opposite directions (Current State; PR-03). Slice 1 gives **both** surfaces the same union source with source badges:

- **Shared option builder** `buildNamingOptions(rosterEntries, labelMatches)` (new, beside the panel): each option is `{ value, label, source: 'person' | 'cluster' }` with **values namespaced by source** — `person:<roster-id>` / `cluster:<cluster-id>` — so an option value can never be mistaken for a bare cluster id (PR-16). The union chooser itself is [COG-02] — recognition over recall: a known name is chosen, not recalled and retyped. Display: deduped case-insensitively **preferring the person entry** (its casing is canonical — product ranking, alongside persons-listed-before-clusters); badges per [PERC-02] — the badge encodes the real behavioral difference: person = names an entity, cluster = merges into an existing cluster. Filter-before-slice: the union is prefix-filtered, then truncated. The builder also returns the **pre-dedupe collision set** (see duplicate guard).
- **Source-gated match pipeline** (PR-16 — the load-bearing rule): the existing save/match path treats option values as cluster ids — `findClusterByLabel` resolves `{id: option.value}` from the option list (`useClusterSuggestions.ts`) and `useClusterMatchAction.runMatchedAction` feeds `match.id` straight into `mutations.merge` / `assignToCluster`. Therefore `findClusterByLabel`, the proactive match, and every merge/assign resolution consider **`source === 'cluster'` options only** (unwrapping the namespace); a person selection is **rename/create-with-canonical-casing only** and never enters the match pipeline. Test: a person-name hit must not produce a merge.
- **Option pipeline, fully named** (PR-17): `useClusterSuggestions.ts : selectClusterSuggestions` remains the dropdown assembly point — group 1 "Suggested" from the identity projection (unchanged semantics), group 2 the `buildNamingOptions` union (persons badged, then labeled clusters); `seen`-dedupe keys on lowercased label **across groups** so a suggested cluster is not repeated below; group order fixed (Suggested → union).
- **Panel** (`ClusterLabelingPanel.tsx`): Combobox options = the same union (today roster-only). Cluster selection routes to the existing merge path via the source gate; person selection keeps canonical casing.
- **Dropdown/save leg** (`useClusterSuggestionsLoader.ts`): `labelMatches` union with roster entries (today clusters-only) via the same builder — one definition, two consumers (sr-007).
- **Duplicate guard** (PR-11, PR-18): the backend never emits a duplicate-label 409 (`clusters_topology.py` has no such check), so the panel's 409-driven `duplicateMatch` "Is this X?" branch is dead code — **deleted** (greenfield). Replaced by a **pre-save** check that runs over the **pre-dedupe universe** (roster ∪ clusters, before person-preferred dedupe — else person "Bob" hides cluster "bob" and the guard can never offer the merge): exact case-insensitive match (excluding the editable cluster) blocks with an inline warning at the field ([FORM-05]) offering explicit *merge* / *rename anyway* / *cancel*. **Action copy names the exact collision target ([INT-06], PR-23) — "Merge into cluster 'Bob'", never a generic "merge into existing cluster"; the deleted 409 branch already named its target and the guard must not regress below it. The merge option is disabled/hidden when the collision set has no unique cluster target, and shows an outcome sample on the same surface before commit ([INT-07], PR-24): target cluster label + member/identity count. Verify the panel merge path surfaces the merge-undo back-out (`MergeUndoBanner` is wired on the card path via `IdentityClusterItem`; add the panel's `lastMerge` state wiring if absent) so back-out exists on both entry points.** No silent create, no silent merge.
- **Pin removal**: `ClusterPreview.tsx` toggle removed **and** its call-site plumbing in `IdentityClusterItem.tsx` (`handleToggleRepresentativePin`, `isPinning`, the `onTogglePin`/`isPinning` props) deleted (PR-10). The `pinRepresentative` mutation and API stay; relocation is a deferred product decision (original UXP-3 scope).
- **A11y**: combobox entries carry accessible names including source ([A11Y-04]); result-count changes and the duplicate warning announced via live region ([A11Y-21]); badges never color-only ([A11Y-06]); roster loading/empty/error degrade to cluster-only options, each state rendering and announcing ([A11Y-24]).

Roster data via existing `useRosterEntries` (60s poll, cooldown-gated) — no new transport.

## Proposed Solution — Slice 2: case-sensitive dirty check, both entry points (B6)

The comparisons get distinct semantics instead of one lowercased blur:

1. **Dirty check** (`useClusterSaveAction`, the bail-out): **exact** compare. "bob"→"Bob" proceeds; "Bob"→"Bob" still no-ops.
2. **Merge-target match**: stays case-insensitive — typing "bob" when another cluster "Bob" exists is legitimately a merge — but a case-only **self**-match (matched label equals current label case-insensitively) is a rename, not a merge: the post-`findClusterByLabel` bail becomes exact-compare against `currentLabel` so a case-only rename falls through to the label PATCH (server label update is case-sensitive; the client bail is the only blocker — [HAI-02]: the correction reaches the stored label).
3. **Confirm path** (PR-09): the same exact-compare fix in `useClusterConfirmSuggestion` (its case-insensitive no-op before `runMatchedAction`), so confirming a suggestion differing only by case applies it.
4. **Feedback**: successful case-only rename shows saved state inline at the field ([PERC-05] — fovea-first post-action status) and is announced ([A11Y-21]); save *errors* stay field-inline per [FORM-05].

Tests characterize current behavior first ([TEST-03]), then pin the grid: "bob"→"Bob" mutates (save path); "Bob"→"Bob" no-ops; "bob" typed with a *different* existing "Bob" cluster routes to merge; case-only confirm applies (confirm path); each new test watched failing once ([TEST-06]).

## Files and Surfaces to Change

| Slice | File : symbol | Change |
| --- | --- | --- |
| 0a | `identity-clusters/suggestionProjection.ts` (**new**): `isHumanLabeledTarget`, `compareSuggestions`, `PROJECTION_TOP_K`, `ProjectedSuggestion`, `fromIdentityMatch`, `fromPendingRow`, `invalidateSuggestionProjection`, event map | contract module |
| 0a | `js/admin/api/queryKeys.ts` : `suggestions` | add `projection.*`; legacy keys deleted per D5 step |
| 0a | `identity-clusters/__tests__/suggestionProjection.fixtures.ts` (**new**) | matrix fixture (exported for E21-5) |
| 0b-1 | `identity-clusters/useInlineSuggestionBatch.ts` (UXP-2's) | depth 5, predicate, projection keys |
| 0b-2 | `identity-clusters/useClusterSuggestionsLoader.ts`, `useClusterSuggestions.ts` | single-id batch via projection; `fetchIdentitySuggestions` consumer removed |
| 0b-3 | `identity-clusters/useSuggestionReviewQueries.ts`, `suggestionReviewItems.ts` : `buildSuggestionReviewItems`, `useSuggestionReviewMutations.ts` (reads, invalidations, **optimistic setQueryData/cancelQueries/rollback**) | projection keys + `ProjectedSuggestion`; per-cluster grouping kept |
| 0b-4 | `useClusterMutations.ts` : `invalidateQueries`; `ClusterLabelingPanel.tsx`; `TopClustersSection.tsx`; `ClusterReviewPanel.tsx`; `hooks/useJobStateMachineEffects.ts`; `hooks/useSyncTrigger.ts`; `useClusterConfirmSuggestion.ts` (action helper — verify, not an invalidation owner) | route assignment invalidation through the helper; keep D4 cross-family calls |
| 0b-5 | `src/api/class-suggestions-controller.php` : per-identity forward | drop dead `threshold` |
| 1 | `identity-clusters/buildNamingOptions.ts` (**new**) ; `ClusterLabelingPanel.tsx` ; `useClusterSuggestionsLoader.ts` ; `useClusterSuggestions.ts` : `selectClusterSuggestions`, `findClusterByLabel` ; `useClusterMatchAction.ts` : `runMatchedAction` | union source with namespaced values + badges; source-gated match resolution (cluster-only); option pipeline groups; pre-dedupe duplicate guard; delete dead 409 `duplicateMatch` branch |
| 1 | `identity-clusters/ClusterPreview.tsx` ; `identity-clusters/IdentityClusterItem.tsx` : `handleToggleRepresentativePin`, pin props | remove control + plumbing |
| 2 | `identity-clusters/useClusterSaveAction.ts` ; `identity-clusters/useClusterConfirmSuggestion.ts` | exact dirty checks; case-only-rename fall-through; feedback |
| tests | TS suites per slice; PHP proxy test (0b-5) | per-slice proof below |

## Related Files (not modified)

| File : symbol | Note |
| --- | --- |
| `recognition/application/suggestions/eligibility.py` : `is_eligible_cluster` | creation-time gate D2's soundness rests on |
| `recognition/.../curation/cluster_mutations.py` : `update_cluster` | labeling path sets `user_confirmed = bool(label)`; **not** a global invariant (see Current State) |
| `recognition/.../cluster_merge.py`, `split/executor.py`, auto-labeler (`application/labeling/auto_labeler.py`) | the paths that break label⟺confirmed equivalence — documented, untouched |
| `recognition/.../repositories/suggestion_repository.py` : `list_pending_with_details` | review-leg semantics (strict filter + stale-accepted resurrection) |
| UXP-2 branch: `routers/suggestions.py` : `list_identities_suggestions` | batch transport consumed post-merge |
| `js/admin/hooks/useRosterHooks.ts` : `useRosterEntries` | slice-1 roster source, unchanged |

## Verification Strategy

- `npm --prefix apps/prototype-wp-alt-context test` (all slices)
- `composer --working-dir=apps/prototype-wp-alt-context test` (0b-5)
- `make check-remote` at each slice's committed HEAD (remote gate; no local full-suite runs)
- **Slice-0 proof split** (PR-13): UXP-3 owns the projection **unit matrix** (fixture: predicate, per-leg order, window-depth, residuals, stale-accepted review-exclusivity) plus **per-consumer hook tests** (inline, dropdown, review render the fixture's expected values) plus **per-event invalidation tests** (D4 table). The **three-real-consumer integration harness is E21-5's** (FBT-1 criterion 2 names both owners); its fixture import is the handshake.
- Manual (dev recognition only): near-miss identity → same suggestion in inline prompt and dropdown; accept on the review card → prompt and dropdown clear without reload; "bob"→"Bob" saves with visible confirmation from both entry points; a name known to either source surfaces on both naming surfaces; duplicate name blocks with the choice UI.

## Slice Delivery

### Slice 0: suggestion-projection contract (B10a)

**Goal**: one predicate, per-leg-honest ranking, one assignment key family, one invalidation map — consumed by all three surfaces; identity-keyed surfaces agree by construction.

Steps 0a → 0b-1..5 per D5. 0a has no UXP-2 dependency; 0b gated on UXP-2 merge (stop and coordinate if unmet — do not re-implement its transport).

Proof: the verification-strategy split above; plus the deliberate `cluster-*` change pinned (inline + dropdown fixture rows) and named in the slice handoff decision; PHP test pinning `threshold` gone.

### Slice 1: two-way union typeahead + pin removal (B5, UXA-07)

**Goal**: any name known to either source surfaces on both naming surfaces before free-text create; duplicates block with an explicit choice; no control occludes a face.

Proof: `buildNamingOptions` unit tests (union, namespaced values, person-preferred case-insensitive dedupe, persons-first ordering, filter-before-slice with a match beyond the slice boundary, pre-dedupe collision set); **source-gate tests: a person-name hit never reaches `mutations.merge`/`assignToCluster`** (PR-16); `selectClusterSuggestions` group-pipeline tests; panel and loader tests consuming the same builder; duplicate-guard grid (existing person / existing cluster / person+cluster same name → block still offers merge-into-cluster (PR-18) / self-case-only → no block; merge action copy names the concrete target and renders its member count, disabled when no unique target — PR-23/PR-24); dead-409-branch deletion compiles with no `duplicateMatch` references; pin control and plumbing absent (`IdentityClusterItem` renders without pin props); a11y assertions ([A11Y-04]/[A11Y-21]/[A11Y-24] states).

### Slice 2: casing rider, both entry points (B6)

**Goal**: case-only renames save with feedback from the free-text and confirm paths; merge semantics unchanged.

Proof: the five-case grid (§ slice 2) with characterization-first ordering; announcement assertion.

## Consolidated Checklist

### Context and Ownership

- [x] Frontend rules + testing-typescript loaded; UXP-2 plan §§ batch endpoint/filter parity/wire format read before touching its surfaces.
- [x] UXP-2 merge state checked at 0b start; coordination decision recorded if unmerged.

### Slice 0

- [x] `suggestionProjection.ts` exports predicate, per-leg comparator rule, `PROJECTION_TOP_K`, `ProjectedSuggestion` + adapters, keys, invalidation helper, event map (sr-007).
- [x] Matrix fixture exported; includes window-depth, all-ineligible-window, `"Person N"` labeled-unconfirmed, tied-similarity (per-leg), and stale-accepted rows.
- [x] 0b-1+0b-2 co-shipped (PR-19) as two commits (PR-22): structural migration preserving truthy-label eligibility first, named predicate-flip second; inline depth 5 + projection key; dropdown single-id batch at same depth; `identityFor` deleted; no consumer left on `fetchIdentitySuggestions`; `cluster-*` change pinned by test in the flip commit; route-retirement follow-up recorded for UXP-2 absorption, not implemented.
- [x] 0b-3 review: projection key + adapted `ProjectedSuggestion[]` cache (adapter in `queryFn`; optimistic filters on `suggestionId` — PR-20); per-cluster grouping kept; **optimistic setQueryData/cancelQueries/rollback re-keyed** with rollback-after-failed-accept test; `pending` deleted.
- [x] 0b-4 sweep: every D4-inventory site routed; per-event tests assert assignment family exactly **and** kept cross-family calls present.
- [x] 0b-5 proxy `threshold` dropped with PHP test.
- [x] Slice handoff decision names the `cluster-*` behavior change.

### Slice 1

- [x] `buildNamingOptions` single definition consumed by panel and loader; namespaced values (`person:`/`cluster:`); persons first; person-preferred case-insensitive dedupe; filter-before-slice; pre-dedupe collision set exposed.
- [x] Match pipeline source-gated (PR-16): `findClusterByLabel`/proactive match/merge resolve `cluster:` options only; person select never merges (test); `selectClusterSuggestions` group pipeline per plan.
- [x] Pre-save duplicate guard over the **pre-dedupe universe** with explicit merge/rename/cancel (person+cluster same-name fixture — PR-18); merge action names its target and shows label + member count before commit, disabled with no unique target (PR-23/PR-24); panel-path merge back-out verified; dead 409 `duplicateMatch` branch deleted.
- [x] Pin control removed from `ClusterPreview` **and** plumbing from `IdentityClusterItem`; mutation/API untouched.
- [x] Combobox a11y: names incl. source, live-region announcements, non-color badges, [A11Y-24] roster state matrix.
- [x] E21-9 pull-in decision (out) recorded in handoff at slice close.

### Slice 2

- [x] Exact dirty checks on both entry points; case-only rename mutates; merge path preserved (five-case grid).
- [x] Inline saved/error feedback + announcement.
- [x] Characterization tests green before the change ([TEST-03]); new tests watched failing ([TEST-06]).

## Review Readiness

- [ ] Each slice: `/branch-review` with findings in MCP; remote grok as second reviewer at slice 0 and before merge.
- [ ] Handoff decision per slice (record + notify), `render_handoff(kind='dashboard')` after writes.
- [ ] Pre-merge gate: `handoff_close_check(enforce=True)` with fresh test evidence at HEAD.

## Success Criteria

- [ ] Inline prompt and curation dropdown derive the same top match for the same identity by construction (shared transport, depth, predicate, server order); accept/reject/label/merge/dismiss from **any** surface (including review cards) invalidates the projection so every surface converges on the next fetch (FBT-1 criterion 2, UXP-3's half; E21-5 owns the three-real-consumer harness).
- [ ] The only review-queue divergences are the two defined ones (stale-accepted repair rows; page membership) — pinned by fixture, never a conflicting top match.
- [ ] No identity-keyed surface shows an auto `cluster-*` target; the change is deliberate, tested, and recorded.
- [ ] E21-5 ④ and UXP-5 consume the exported predicate/keys/invalidation map + fixture without re-deriving policy.
- [ ] A name known to either the roster or labeled clusters surfaces on both naming surfaces, badged, before free-text create (criterion 6; E21-9 write-through residual accepted and recorded).
- [ ] "bob"→"Bob" saves with inline feedback from both entry points (criterion 6).
- [ ] No pin control overlaps a face thumbnail; no dangling pin plumbing.
- [ ] Zero recognition-service changes (code or tests) on this branch.
