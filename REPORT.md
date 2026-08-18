# UXW2-2-PHP REPORT

PHP-only B5: projection `identity_count` drift + memberless top-unlabeled.

## RED

Slice 1 (`composer`/phpunit, pre-impl):
- `testMapTopUnlabeledReturnsObservedCountOnNonTruncatedShortfall`: `3 !== 2`
- `testMapClusterListLogsWhenObservedBelowPreviewLimit`: `9 !== 2`
- `testFindClustersMissingProjectedMembersIncludesNonTruncatedShortfall`: missing `cluster-drift-3-2`
- `requested_repair_cluster_ids()` undefined (truncated case)

Slice 2:
- `testListTopUnlabeledRequiresObservedMemberRows`: SQL had no `wp_acx_identity_members`

TEST-15 (post-GREEN mutations, then restored):
- return `$projected_count` → `Failed asserting that 3 is identical to 2`
- drop members `COUNT(*)` predicate → SQL lacks `` `wp_acx_identity_members` ``

## GREEN

`cd apps/prototype-wp-alt-context && composer test`
**OK (1769 tests, 8536 assertions)**

Targeted: mapper+sync+read 46/46; repo+parity 31/31.

## Files

- `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php`
- `apps/prototype-wp-alt-context/src/api/services/class-cluster-projection-sync-service.php`
- `apps/prototype-wp-alt-context/src/api/services/class-cluster-read-service.php`
- `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-read-repository.php`
- tests: `ClusterResponseMapperTest.php`, `ClusterProjectionSyncServiceTest.php`, `ClustersReadRepositoryTest.php`, `ClustersRepositoryTest.php`
- `tests/fixtures/clusters-read/get_cluster_detail_local_projection/response.json` (`identity_count` 2→1)
- `packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json`
- disk-only (gitignored): `docs/workbay/contracts/clustering-api.md`, `recognition-clustering.md`

## Canon IDs

| ID | file:line | how |
|---|---|---|
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | return observed count on non-truncated shortfall |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | members table is SoR; projected column not republished as truth |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | 3/2 and memberless SQL tests; mutations went red |
| RES-12 | `~/uxw2/canon/lexicons/engineering.md:123` | one correlated `COUNT(*)` on `cluster_identity` index; no PHP N+1 |
| HAI-01 | `~/uxw2/canon/lexicons/interaction-ux.md:210` | queue count/list backed by observed member rows |

rg-007 / rg-015 are constitution guards, not canon lexicon rows (grep of `~/uxw2/canon` empty). Applied: repair id list = current page; no invented envelope fields.

## Decisions

- Mapper returns observed when `observed < projected` and not cap-hit truncation; records repair UUIDs.
- `find_clusters_missing_projected_members` now flags non-truncated shortfalls (preview default 4). Repair remains async schedule (`repair_targeted_projection` still returns false; BR-07).
- `list_top_unlabeled` keeps `c.identity_count >= 2` prefilter + `COUNT(m) >= 2` subquery (indexed `cluster_uuid`).
- Contract prose written under gitignored `docs/workbay/contracts/`; tracked schema carries the invariant.

## Undone

- Frontend B5 (count from shown thumbs / hide missing tiles) — other lane.
- Sync heal still async; request serves honest observed count immediately.
- Cluster with 2+ real members but stale `identity_count < 2` still excluded by the column prefilter.

## Commits

- `41b54bd4447e37aab460c85fc8f3afdbce967473` `fix(sovereign): UXW2-2 identity_count reflects observed members`
- `5463596c7e7b770e6e55b874c0295bbfdf41bb9e` `fix(sovereign): UXW2-2 exclude memberless clusters from top-unlabeled`
- `4324a9a69c88f5d6682619ea17393cb942196446` `fix(sovereign): UXW2-2 golden identity_count matches observed members`
- `9e076ac7ba2c431c3acd089bcac039d095891aca` `docs: UXW2-2 REPORT.md` (this file; HEAD if no follow-up)


---

# REPORT — LANE UXW2-2-FE (honest review counts, frontend)

Final HEAD: output of `git rev-parse HEAD` on this commit (self-referential; last lane commit before this report: `b085d572b5bd561842b617b3c3c44a3ee038c040`)

## Slice 1 — TopClusterCard face count matches what is shown (B5)

Commit: `e90fc5dcc0f32068b572b1b3f854b0cb960e3c76` `fix(workbench): UXW2-2 face count reflects rendered faces`

- RED: `TopClusterCard.test.tsx` — new test "counts rendered faces and reports unrendered members as '+N more'"
  (`identity_count=3`, 2 usable reps → wanted `2 faces in cluster` + `+1 more`) failed: count text was
  `3 faces in cluster` (derived from `identity_count`). Updated missing-label test failed: 39px cells carried
  `acx-durable-face-thumb--hide-missing-label` (blank tile). RED run: `2 failed | 22 passed`.
- GREEN: `TopClusterCard.tsx` — count text now `_n('%d face in cluster','%d faces in cluster', reps.length)`
  plus `(+N more)` when `identity_count > reps.length` (ClusterPreview `+N` pattern); `hideMissingLabel` fixed to
  `false` so an image-less representative renders the DurableFaceThumb missing state WITH its visible "No image"
  label at every cell size. GREEN run: `24 passed (24)`; pre-existing `identity_count === representatives.length`
  test (was ~L172-200) still passes unchanged.
- Decision (brief offered two options): render the missing state WITH its visible label rather than dropping the
  rep from `reps`. Rationale: dropping would under-report loaded member rows and contradict PRINCIPLES §11
  (unknown is a designed state — say "No image", don't blank or vanish); it also keeps the tile grid aligned with
  the server-provided representative list.
- Wording: no new "cluster" string introduced; `(+%d more)` is face-count only.

## Slice 2 — queue header count tracks labelling (B6, frontend)

Commit: `b085d572b5bd561842b617b3c3c44a3ee038c040` `fix(workbench): UXW2-2 drop labelled cluster from review caches`

- RED: `useSuggestionReviewMutations.test.tsx` — "person-commit drops the committed cluster from all four review
  caches" failed (`sugg-x` survived in reviewPage). `ReviewQueue.test.tsx` — "header count decrements after a
  label commit panel round-trip without a refetch" failed (count stayed 2 after `updateClusterLabel` resolved).
- GREEN: one shared helper `dropClusterFromReviewCaches(queryClient, clusterId)` in `suggestionProjection.ts`
  optimistically filters: assignment `reviewPage(0)` items by `clusterId`, `namePending` by `cluster_id`,
  `mergePending` rows where either side matches, and `topUnlabeled` rows (tenant-prefix `setQueriesData`).
  Wired into: `executePersonCommit` (replaces narrower `removeNameSuggestionForCluster`, now deleted),
  `ClusterLabelingPanel.handleLabelSuccess` and `handleMergeSuccess`, and merge-accept success in
  `useSuggestionReviewMutations` (held-commit path + `acceptMergeMutation`, only when the response carries an
  authoritative `source_cluster_id` — never the client-rank fallback, rg-015). All existing invalidations kept
  (incl. namePending `refetchType:'none'`, S2-02).
- Header (`ReviewQueue.tsx`): all four feeds are capped pages (25/10/25/20) with no envelope total, so the count
  now reads "%d left to review (loaded)" — honest loaded scope, no invented total (rg-015). Stays
  `aria-hidden`; the position line remains the `aria-live` surface (A11Y-21 preserved).
- GREEN run: both files `115 passed (115)`.

## Full suite / gates

- `npm test` (frontend, full): **206 files, 2341 passed, 0 failed**.
- `npm run typecheck`: clean.
- `npm run lint`: 117 errors + 1 warning — proven pre-existing: identical count on stashed baseline; none of the
  six files I touched appear in the error list. Not introduced by this lane.

## Files changed

- `identity-clusters/TopClusterCard.tsx`, `__tests__/TopClusterCard.test.tsx` (slice 1)
- `identity-clusters/suggestionProjection.ts` (`dropClusterFromReviewCaches`)
- `identity-clusters/useSuggestionReviewMutations.ts` (person-commit + merge-accept wiring)
- `identity-clusters/ClusterLabelingPanel.tsx` (label/merge success wiring)
- `identity-clusters/ReviewQueue.tsx` (header count copy)
- `__tests__/useSuggestionReviewMutations.test.tsx`, `__tests__/ReviewQueue.test.tsx` (slice 2 tests)

## Canon IDs satisfied (verified by grep)

- REF-09 derived-data drift — `~/uxw2/canon/lexicons/engineering.md:328` (count/cache now derived from rendered/loaded rows)
- DATA-01 consistency model stated — `engineering.md:189` (optimistic drop + documented curation-lag window; existing invalidations reconcile)
- TEST-15 prove green can go red — `engineering.md:396` (both slices landed RED first; old count test could not fail for the reported case)
- HAI-01 evidence before label — `interaction-ux.md:210` (count no longer claims faces with no tile)
- INT-10 status–predict–stop — `interaction-ux.md:167` (header count tracks the labelling action immediately)
- PERC-05 fovea-first feedback — `interaction-ux.md:95` (count at the queue header updates at the point of action)
- A11Y-21 announce status — `accessibility.md:132` (count stays aria-hidden; live position line unchanged)
- PRINCIPLES §11 unknown is a designed state — `~/uxw2/canon/PRINCIPLES.md:260` (missing image renders labelled "No image", never blank)
- rg-015 — no fabricated totals: header labelled "(loaded)"; merge drop only on authoritative `source_cluster_id`.

## Decisions

1. Missing-image rep: render missing state with visible label (not dropped from `reps`) — see Slice 1.
2. Label-success wiring placed in `ClusterLabelingPanel.handleLabelSuccess`/`handleMergeSuccess` (the panel's own
   mutations), not `useClusterMutations`/`useClusterLabelMutations` — the panel does not use those hooks for
   label/merge; wiring them would have changed library-pane behaviour outside this lane's scope.
3. Header copy "(loaded)" chosen over inventing a server total (no envelope total exists; COR-3/rg-015).
4. Existing "+N" phrasing rendered as `(+N more)` inside the meta line — text, not a styled badge, to avoid new
   CSS surface in a 30-min lane.

## Undone / out of scope

- B6 backend half (PHP/python synchronously resolving pending suggestions on label/commit) — cross-lane; the
  frontend optimistic drop covers the visible symptom, refetches after curation reconcile.
- Pre-existing lint debt (117 errors) untouched per scope rules.
- True remaining-count total would need envelope totals (COR-3) — deliberately not fabricated.
