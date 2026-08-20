# REPORT — UXW2-2 fix r10b (FE invalidation proof)

Cite commits by subject line. No SHAs. File:line cites re-derived with `sed -n '<N>p' <file>` after the last code commit (`test(fe): UXW2-2 pin review-queue invalidation header and key proofs`).

Production on the two hooks was not edited.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Closures

| Finding | Subject | Test | Mutant + RED (verbatim) | GREEN |
|---|---|---|---|---|
| R5-07 | `test(fe): UXW2-2 pin review-queue invalidation header and key proofs` | `R5-07: the queue header count decrements after a full bulk accept` | delete `namePendingKey` invalidate in `bulkAcceptMutation.onSuccess` → `AssertionError: expected <span …(2)></span> to be null` / Received `<span class="acx-review-queue__count">2 left to review on this page</span>` | `-t 'R5-07: the queue header count decrements after a full bulk accept'` → `Tests  1 passed \| 93 skipped (94)` (paired with R1-24: `Tests  2 passed \| 92 skipped (94)`) |
| R1-24 | same | `R1-24: acceptName mutation decrements the rendered queue header` | delete `dropClusterFromReviewCaches(...)` in `acceptNameMutation.onSuccess` → `AssertionError: expected '3 left to review on this page' to be '2 left to review on this page'` | same paired `-t` as R5-07 |
| R7-05 | same | `R5-01: a partial accept refetches instead of guessing` | delete `top-unlabeled` invalidate → `AssertionError: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'clusters', …(1) ] } ]` (Received 1st call `suggestions`/`name` only; missing `clusters`/`top-unlabeled`) | `-t 'R5-01: a partial accept refetches instead of guessing'` → `Tests  1 passed \| 49 skipped (50)` |
| R5-06 identities | same | `R3-05: a non-review cluster mutation refetches a mounted identities list` | `refetchType: 'none'` on `media.identities()` → `AssertionError: media.identities: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'media', …(1) ] } ]` / 1st call `+"refetchType": "none"` | `-t 'R3-05: a non-review cluster mutation refetches a mounted identities list'` → `Tests  1 passed (1)` |
| R5-06 / R8-04 labels | same | same | `refetchType: 'none'` on `clusters.labels()` → `AssertionError: clusters.labels: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'clusters', …(1) ] } ]` / 2nd call `clusters`/`labels` + `+"refetchType": "none"` | same GREEN as identities |
| R5-06 clusters.all | same | same | `refetchType: 'none'` on `clusters.all` → `AssertionError: clusters.all: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ 'clusters' ] } ]` / 3rd call `+"refetchType": "none"` | same |
| R5-06 projection | same | same | `refetchType: 'none'` on `suggestions.projection.all` → `AssertionError: suggestions.projection.all: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ …(2) ] } ]` / 4th call `suggestions`/`projection` + `+"refetchType": "none"` | same |
| R5-06 mergePending | same | same | `refetchType: 'none'` on `suggestions.mergePending()` → `AssertionError: suggestions.mergePending: expected "invalidateQueries" to be called with arguments: [ { queryKey: [ …(2) ] } ]` / 5th call `suggestions`/`merge` + `+"refetchType": "none"` | same |
| R7-06 | `docs(uxw2): UXW2-2-R7-06 correct r3 R5-07 header-row citations` | r3 R5-07 row now cites the ReviewQueue header test | `length >= 0` re-run on `R5-07` → `AssertionError: expected <span …(2)></span> to be null` / Received span `0 left to review on this page` (same RED on `R7-06`) | r3 row rewritten; no assertion weakened |

## Item 1 — R5-07 + R1-24

Header is `filteredQueue.length` (`ReviewQueue.tsx:447`) gated into `.acx-review-queue__count` (`:988-989`).

ReviewQueue exposes no bulk-accept affordance (`ReviewQueue.test.tsx:1074`, `:1104`; `useBulkReviewCommit.ts:6` "Zero calls to legacy bulk-accept"). Tests mount `ReviewMutationDriver` on the same QueryClient as the rendered queue and call the real mutations — not a second isolated `renderHook`, not a cache-length labelled as header.

- Bulk path (`:3277`): seed 2 name suggestions, assert `2 left to review on this page`, point the namePending fetcher at the post-accept empty list, `bulkAccept.mutateAsync({ suggestion_type: 'name', min_confidence: 0.8 })` with `{accepted_count:2,skipped_count:0}`, wait for the span to unmount. Decrement is refetch-driven (`useSuggestionReviewMutations.ts:1024`).
- acceptName path (`:3333`): seed 2 names + 2 evidenced top-unlabeled clusters (header 4), call `acceptName.mutateAsync('name-1')` (the mutation at `:986-996`, not `scheduleAcceptName` / `applySuccessSideEffects`). `dropClusterFromReviewCaches` (`:992`) drops name-1 and cluster-1; header becomes 2. Without the drop, `removeNameSuggestionFromCache` only removes the name row (header 3).

Existing `R7-06` (`:3215`) still covers the UI hold path; it does not kill mutant B.

## Item 2 — R7-05

`R5-01: a partial accept refetches instead of guessing` (`useSuggestionReviewMutations.test.tsx:1813`) now spies both `{ queryKey: namePendingKey }` and `{ queryKey: [...queryKeys.clusters.all, 'top-unlabeled'] }`, mounts `useQuery` observers on both keys, and asserts `fetchName` / `fetchTop` after the mutate. Partial branch is `accepted_count: 1, skipped_count: 1` so `invalidateReviewCachesWithoutRefetch` is not reached (`:1029-1030`).

## Item 3 — R5-06 + R8-04

`useClusterMutations.ts:50-57` still invalidates the five keys with `{ queryKey }` only. `R3-05` (`useClusterMutations.test.tsx:41`) keeps the `media.identities()` refetch observer (`:123`) and adds exact `toHaveBeenCalledWith({ queryKey: <key> })` per key (`:106-120`), with a message that names the key. Adding `refetchType: 'none'` to any one call fails that key's assertion and only that key's assertion. All five mutants went RED; the labels observer still refetches via the `clusters.all` prefix, which is why the argument layer is required (R8-04).

## Item 4 — R7-06 report truth

Rewrote the r3 R5-07 row. It no longer claims a hook-only cache assertion is a header decrement. The `length >= 0` RED was re-run (not copied): the `…(2)` in `expected <span …(2)></span> to be null` is vitest's child count, not leftover queue length; the Received text is `0 left to review on this page`. Same mutant also REDs `R7-06`.

## Suite

From `apps/prototype-wp-alt-context`:

```
npx vitest run
Test Files  212 passed (212)
      Tests  2403 passed (2403)
```

`npm run typecheck` — clean.

PHP untouched; `composer test` skipped.

## Cites (sed after last code commit)

- `ReviewQueue.tsx:447` `const length = filteredQueue.length;`
- `ReviewQueue.tsx:988` `{length > 0 ? (`
- `ReviewQueue.tsx:989` `<span className="acx-review-queue__count"`
- `useSuggestionReviewMutations.ts:986` `acceptNameMutation`
- `useSuggestionReviewMutations.ts:992` `dropClusterFromReviewCaches(...)`
- `useSuggestionReviewMutations.ts:1024` namePending invalidate on bulk accept
- `useSuggestionReviewMutations.ts:1026` top-unlabeled invalidate
- `useClusterMutations.ts:50-57` five `invalidateQueries` calls
- `useBulkReviewCommit.ts:6` `Zero calls to legacy bulk-accept`
- `ReviewQueue.test.tsx:1104` `queryByText('Bulk accept')` is null
- `ReviewQueue.test.tsx:3277` / `:3333` header cases
- `useSuggestionReviewMutations.test.tsx:1813` partial-accept observer case
- `useClusterMutations.test.tsx:106-120` exact argument assertions

## Undone

- ReviewQueue still has no Bulk-accept chrome. The R5-07 header case drives `mutations.bulkAccept` from a sibling hook instance on the same QueryClient, not from a control inside ReviewQueue. `useBulkReviewCommit.ts:6` still says zero calls to legacy bulk-accept.
- The UI accept-name path (`scheduleAcceptName` → `applySuccessSideEffects` at `useSuggestionReviewMutations.ts:353`) is a separate `dropClusterFromReviewCaches` from `acceptNameMutation.onSuccess` (`:992`). Mutant B only kills the mutation-driven header case. `R7-06` still covers the UI path.
- `refetchType: 'none'` on `clusters.labels()` still leaves `fetchLabels` called, because `clusters.all` (`['clusters']`) prefix-matches `['clusters','labels']`. The labels kill is the exact-options assertion, not the observer.
- PHP untouched; `composer test` not run.
- UX maps not edited (lane ownership). No user-facing surface change.
