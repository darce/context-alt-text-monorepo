# REPORT — UXW2-2-R1 FE fix lane

Final HEAD: stamped after this commit. Prior commits (all `git cat-file -e` clean):

| SHA | Message |
|---|---|
| `a805b82ea58392a515172c40a50f665694a9fd62` | `fix(fe): UXW2-2-R1-19-20-27-30 top-group-card count and copy` |
| `b37cbb06f47263cb947c7a708d1ba7f28016e95c` | `fix(fe): UXW2-2-R1-28-29 review-queue header copy` |
| `c672a11b5230283f81290dad4ba05e1059a6abed` | `fix(fe): UXW2-2-R1-15-26 review-drop tombstone and cache split` |
| `308974be719ab206ae47df9b79d977f8d5a2d499` | `docs(uxmap): UXW2-2 review-suggestions queue header and top group card zones` |

## Closure table

| Finding | Commit | Test | Mutant killed |
|---|---|---|---|
| R1-15 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `ReviewQueue.test.tsx` `header count decrements after a label commit remount with stale fetchers` | delete `tombstoneReviewGroup` → remount count/position restore (`1 of 2`) |
| R1-16 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `useSuggestionReviewMutations.test.tsx` `R1-18: person-commit four-cache drop survives active observers` | drop `refetchType: 'none'` → observers refetch stale rows |
| R1-17 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `useSuggestionReviewMutations.test.tsx` `R1-17: acceptMerge drops the retired source`; `ClusterLabelingPanel.test.tsx` `R1-17: merge success drops result.source_id` | remove `dropRetiredMergeCluster` / panel `result.source_id` drop → retired id remains |
| R1-18 | `c672a11b5230283f81290dad4ba05e1059a6abed` | same observer test as R1-16 | `setQueryData`-only hook (no observers) stays green; observer + stale `queryFn` goes red |
| R1-19 | `a805b82ea58392a515172c40a50f665694a9fd62` | `TopClusterCard.test.tsx` suggested-label / >4 / empty-reps cases | old `_n('%d faces in cluster', reps.length)` + `(+N more)` → `1 face in cluster (+11 more)` / `0 faces in cluster (+5 more)` |
| R1-20 | `a805b82ea58392a515172c40a50f665694a9fd62` | `TopClusterCard.test.tsx` `does not count image-less representatives as shown faces` | count `reps.length` → `3 faces in cluster` over placeholders |
| R1-21 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `useSuggestionReviewMutations.test.tsx` `R1-21: foreign source_cluster_id does not evict` | trust raw `source_cluster_id` → `innocent` evicted |
| R1-22 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `suggestionProjection.dropCaches.test.ts` total decrement; `ReviewQueue.test.tsx` `R1-22: queue header and findings unlabeled count agree` | keep `total` untouched → findings stay `2 unlabeled groups` after drop |
| R1-23 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `suggestionProjection.dropCaches.test.ts` `label drop keeps a live merge suggestion` | always-drop mergePending on label → `merge-live` gone |
| R1-24 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `useSuggestionReviewMutations.test.tsx` `R1-24: acceptName…` / `R1-24: bulkAccept name type…` | skip drop in `acceptName` / `bulkAccept` → topUnlabeled still holds named group |
| R1-25 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `useClusterLabelMutations.test.tsx` rename + merge `source_id` drops | no drop on rename/merge `onSuccess` → caches unchanged |
| R1-26 | `c672a11b5230283f81290dad4ba05e1059a6abed` | `suggestionProjection.dropCaches.test.ts` `label drop keeps assignment rows whose suggested target is the labelled group` | filter `item.clusterId` → `sugg-target` vanishes |
| R1-27 | `a805b82ea58392a515172c40a50f665694a9fd62` | `TopClusterCard.test.tsx` `hides the missing-state label at 39px cells` | `hideMissingLabel = false` → missing `--hide-missing-label` class (no vacuous `toBeVisible`) |
| R1-28 | `b37cbb06f47263cb947c7a708d1ba7f28016e95c` | remount test `toBe('1 left to review on this page')` | revert to `{length}` numeral → exact-text assert RED (`toHaveTextContent('1')` would stay green) |
| R1-29 | `b37cbb06f47263cb947c7a708d1ba7f28016e95c` | `ReviewQueue.test.tsx` `R1-29: filtered header uses shown copy` | ignore `filtersActive` → `2 left to review on this page` while a kind chip is on |
| R1-30 | `a805b82ea58392a515172c40a50f665694a9fd62` | `TopClusterCard.test.tsx` meta `toBe('3 faces')` / `4 of 12 faces shown` | msgid `%d faces in cluster` or concat `(+N more)` → banned noun / split i18n |

## Suites

- `npm test`: **207 files, 2358 passed, 0 failed** (pre-lane 206 / 2341). New file: `suggestionProjection.dropCaches.test.ts`.
- `npm run typecheck`: clean.
- `npm run lint` on touched production files: **0 errors**. Pre-existing repo lint debt not reintroduced (touched files absent from error list).

## RED / GREEN

- TopClusterCard: RED `6 failed \| 21 passed` (`1 face in cluster (+11 more)`, `0 faces in cluster (+5 more)`, `3 faces in cluster`, missing hide class). GREEN `27 passed`.
- Remount header: RED without tombstone (`1 of 2 on this page`). GREEN with tombstone + `select`.
- Drop-helper / mutations / panel / library-pane tests landed against the defective paths and stay red when the defended line is removed (see table).

## Files

- `TopClusterCard.tsx` + test
- `ReviewQueue.tsx`, `ScanTabContent.tsx` + tests
- `suggestionProjection.ts`, `useSuggestionReviewQueries.ts`, `useSuggestionReviewMutations.ts`
- `ClusterLabelingPanel.tsx`, `useClusterLabelMutations.ts`, `useClusterMutations.ts`
- `types/suggestion.ts` (`identity_cluster_id?` passthrough)
- UX map JSON + ASCII: `workbench-operator-loop.uxmap.json` / `.md`

## Canon IDs (grepped)

- TEST-15 `~/uxw2/canon/lexicons/engineering.md:396` — mutants killed per finding
- REF-09 `engineering.md:328` — count/total derived from shown/removed rows
- DATA-01 `engineering.md:189` — tombstone + `refetchType: 'none'` until post-curation prune
- A11Y-21 `accessibility.md:132` — one live surface (position line); count stays `aria-hidden`
- INT-10 `interaction-ux.md:167` — header tracks the label/commit immediately
- PERC-05 `interaction-ux.md:95` — count update at the queue header
- HAI-01 `interaction-ux.md:210` — group size named; thumbs described separately
- NAV-13 `interaction-ux.md:140` — say/don't-say: faces/people/group; no `cluster`/`(loaded)`
- NAV-11 `interaction-ux.md:138` + RLSE-04 `engineering.md:695` — UX map zones include default/loading/empty/error/filtered
- INT-06 `interaction-ux.md:163` — header scope matches the filtered page

## Decisions

1. Group size is `identity_count`; shown thumbs = reps with a usable `resolveFaceThumbDisplay` hop. `0 faces (+N more)` never renders.
2. Restored E21-20: `hideMissingLabel` at `columnCount > 1` (~39px). Dropped the CSS-less `toBeVisible` assert.
3. Label/commit drops name + topUnlabeled + assignment **source** only. Merge feed stays. Merge-accept uses `authoritativeMergeSurvivor` (`null` → no drop).
4. Tombstones are `WeakMap<QueryClient, scope → ids>`, applied in `select`, pruned on **raw** `queryFn` payloads only (pruning selected/cached data cleared the tombstone too early).
5. Library-pane rename/merge now drop (R1-25). Not deferred.

## Undone

- None required by R1-15…30. Backend suggestion-feed sync after label remains a later-lane concern; the tombstone covers the remount/clobber window.
- Pre-existing lint debt outside touched files.
- `ClusterReviewPanel` still says “Review Cluster” (out of this finding list; ScanTabContent sr-only heading updated).
