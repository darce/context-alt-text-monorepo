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
