# REPORT — UXW2-2 FE fix lane

Cite commits by **subject line** only.

## R1 (prior)

| Finding | Subject | Mutant killed |
|---|---|---|
| R1-15 | `fix(fe): UXW2-2-R1-15-26 review-drop tombstone and cache split` | delete NAME tombstone → remount `1 of 2` |
| R1-16 | same | drop `refetchType: 'none'` on review path → observers refetch stale |
| R1-17 | same | remove `dropRetiredMergeCluster` / panel `source_id` drop |
| R1-18 | same | review observers stay no-refetch |
| R1-19 | `fix(fe): UXW2-2-R1-19-20-27-30 top-group-card count and copy` | old `_n` + `(+N more)` |
| R1-20 | same | count `reps.length` over placeholders |
| R1-21 | `fix(fe): UXW2-2-R1-15-26 review-drop tombstone and cache split` | trust raw `source_cluster_id` |
| R1-22 | same | keep `total` untouched |
| R1-23 | same | always-drop mergePending on label |
| R1-24 | same | skip drop in `acceptName` |
| R1-25 | same | no drop on rename/merge `onSuccess` |
| R1-26 | same | filter `item.clusterId` (superseded in R2) |
| R1-27 | `fix(fe): UXW2-2-R1-19-20-27-30 top-group-card count and copy` | `hideMissingLabel = false` |
| R1-28 | `fix(fe): UXW2-2-R1-28-29 review-queue header copy` | revert to `{length}` numeral |
| R1-29 | same | ignore `filtersActive` |
| R1-30 | `fix(fe): UXW2-2-R1-19-20-27-30 top-group-card count and copy` | msgid `%d faces in cluster` |

R1-28/R1-29 live in `fix(fe): UXW2-2-R1-28-29 review-queue header copy`, not a later stamp commit.

---

## R2

Choice **(b)** for R1-26: no PHP/Python emitter for `identity_cluster_id`. Deleted `sourceClusterId` / `identity_cluster_id`. Assignment drops key on `clusterId` (suggested target).

`BulkAcceptResponse` is `{accepted_count, skipped_count}` only — no accepted ids. `bulkAccept` scoped to `name`; assignment/merge reject.

| Finding | Subject | Mutant + RED |
|---|---|---|
| R1-26 + R3-06 | `fix(api): UXW2-2-R1-26 UXW2-2-R3-06 assignment-drop-key-from-raw-payload` | remove drop-key (`return false`) → `expected false to be true` |
| R3-05 | `fix(workbench): UXW2-2-R3-05 restore shared cluster invalidate refetch` | `refetchType: 'none'` on line 50 → `expected "vi.fn()" to be called at least once`. R1-18 stays GREEN. |
| R1-17 + R3-08 | `fix(workbench): UXW2-2-R1-17 UXW2-2-R3-08 merge-drop fixtures and unmount drop` | `source_id` → `clusterId` → `expected [ 'retired-source-id', … ] to deeply equal [ 'panel-cluster-id', … ]`. Delete unmount `dropRetiredMergeCluster` → `expected [ 'cluster-1', 'cluster-2' ] to deeply equal [ 'cluster-2' ]`. |
| R2-12 + R3-03 | `fix(workbench): UXW2-2-R2-12 UXW2-2-R3-03 repair empty does not drain` | drain `<p>` under repair → `expected <p class="acx-review-queue__empty"></p> to be null`. `repair_pending: false` → `expected false to be true`. Delete `topUnlabeledRepairPending` → `expected false to be true`. `Math.max(..., 1)` → `expected 1 to be +0`. |
| R1-20 + R3-07 | `fix(tests): UXW2-2-R1-20 UXW2-2-R3-07 group-size vs shown-count fixture` | `shownFaceCount = reps.length` → `'3 of 7 faces shown'` vs `'7 faces'` |
| R1-22 + R3-09 | `fix(workbench): UXW2-2-R1-22 UXW2-2-R3-09 leave has_clusters untouched` | `has_clusters: filtered.length > 0` → `expected false to be true` (total 10) |
| R1-24 | `fix(workbench): UXW2-2-R1-24 bulkAccept name-only no guessed ids` | delete name drop loop → header/namePending length not 0. assignment/merge `promise resolved "undefined" instead of rejecting`. |
| R1-29 + R3-11/12 | `fix(ux-map): UXW2-2-R1-29 UXW2-2-R3-11 UXW2-2-R3-12 i18n announce and map` | revert announce → `expected '' to be 'Name saved. Back to review suggestions.'` |
| R1-15 verify | no production change | delete NAME-scope `tombstoneReviewGroup` → `expected '1 of 2 on this page' to be '1 of 1 on this page'` |

Canon: rg-015, DATA-14, TEST-15, TEST-06, rg-002, REF-25, RLSE-04, A11Y-21, COG-03, HAI-08, INT-06, NAV-11, REF-09, A11Y-06.

---

## LAST

- Items 1–10 committed. TDD RED lines in commit bodies + table above.
- Follow-ups: `fix(tests): UXW2-2-R2-12 repair empty drops drain asserts`; `fix(workbench): UXW2-2 drop unused assignment drop-mode param`; this report commit.
- `npm test`: **211 files, 2373 passed, 0 failed**. `npm run typecheck` clean. Touched-file `eslint` 0 errors (repo-wide lint still has pre-existing debt).
- Scope: frontend only. No `src/`, `tests/`, contracts, or `UXW2-2-r1-fix-report.md`.
- `sourceClusterId` gone from `js/admin` production.
- Shared invalidate refetches; review path still `refetchType: 'none'`.
- Repair empty: no drain copy. `repairGatedCount(0,0)=0`. Wire `repair_pending` pinned.
- `has_clusters` not rewritten from page length.
- `bulkAccept` name-only; response has no accepted ids.
- UX map: `repair` on header; `rq` on scan; group-card `default,empty`.
- R1-15 remount mutant still RED (`1 of 2` vs `1 of 1`).
- Zero DEAD SHAs (subject lines + labelled lane SHAs only).
