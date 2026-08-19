# UXW2-2 R1 REPORT

Adversarial-review close-out. Branch `master`. Full suite: **OK (1790 tests, 8624 assertions)** (`cd apps/prototype-wp-alt-context && composer test`). `composer lint` not defined.

## RED

| Finding | RED proof |
|---|---|
| R1-01 | `testListTopUnlabeledRequiresObservedMemberRows` still contained `c.identity_count >= 2`. Seeded evaluator: stale-low (3 members, column=1) returned `[]`. |
| R1-02 | `testMapClusterListReturnsObservedCountWhenObservedExceedsProjected` / top-unlabeled twin: `2 !== 4`. |
| R1-03 | Mapper returned 2 rows; controller served `identity_count=0` / `representatives=[]`. |
| R1-04 / R1-07 | `repair_targeted_projection` scheduled `[tenant]` only; mapper upward-drift scheduled 0 events. |
| R1-05 | Stale-high (column=3, 1 member) singleton count `0 !== 1`. |
| R1-06 | Schema lacked `minItems: 1`; `testMemberlessPayloadFailsMinItems` throws `minItems` once present. |
| R1-10 | Injected `custom_cluster_projection` queried itself as members table, not `wp_acx_identity_members`. |
| R1-12 | 5 members + projected 9 kept `5`; 4 members + projected 9 kept `9`. Const `PREVIEW_IDENTITIES_FETCH_LIMIT` undefined. |
| R1-13 | Non-positive preview treated as cap-hit until mapper test required observed. |
| R1-14 | Rename-only; no RED. |

## TEST-15 (mutants killed, then restored)

- Return `$projected_count` on upward drift → `2 !== 4` (`testMapTopUnlabeledReturnsObservedCountWhenObservedExceedsProjected`).
- Keep `c.identity_count >= 2` → stale-low queue empty (`testStaleLowIdentityCountWithThreeMembersIsQueuedNotSingleton`).
- Drop `COUNT(m) >= 2` or add `OR 1=1` → memberless seed survives (`testListTopUnlabeledExcludesMemberlessClusterWhenSeeded`).
- Skip mapper drop of observed-0 → characterization/controller serves empty `representatives` (schema `minItems` fails).
- Fetch cap not +1 → `observed==4` still treated as truncation (`testMapTopUnlabeledTreatsObservedEqualToCapAsExactCount`).

## GREEN

`cd apps/prototype-wp-alt-context && composer test`
**OK (1790 tests, 8624 assertions)**

## Closure

| Finding | Commit | Test | Mutant killed |
|---|---|---|---|
| R1-01 | `5e27822486c921ff9a2001a0a73348e36671d12f` | `testListTopUnlabeledExcludesMemberlessClusterWhenSeeded` | `OR 1=1` / drop `COUNT(m)>=2` includes memberless |
| R1-02 | `f70e69f6e64949707255ccfd081f9fedbc854cbc` | `testMapTopUnlabeledReturnsObservedCountWhenObservedExceedsProjected` | return projected → `2 !== 4` |
| R1-03 | `cc5a93219be059a8effc6c56d91db7448ed216ce` | `testMapTopUnlabeledDropsZeroObservedMembersWhenMembersLoaded` | skip `continue` → empty reps served |
| R1-04 | `ae8c148ac30fc1b851ced2e577641587b4dfef26` | `testListTopUnlabeledSchedulesRepairFromMapperRequestedIds` | `find_clusters_missing` missed upward drift |
| R1-05 | `5e27822486c921ff9a2001a0a73348e36671d12f` | `testStaleLowIdentityCountWithThreeMembersIsQueuedNotSingleton` / `testStaleHighIdentityCountWithOneMemberIsSingletonNotQueued` | column predicate misclassifies size |
| R1-06 | `9b4d30016c99caf76773f1dcd882a52036c2d6e4` | `testContractGoldenValidatesAgainstSchema` / `testMemberlessPayloadFailsMinItems` | empty `representatives` passes without `minItems` |
| R1-07 | `ae8c148ac30fc1b851ced2e577641587b4dfef26` | `testRepairTargetedProjectionSchedulesClusterIdsAndDoesNotPullInline` / `testPerformBootstrapSyncWithClusterIdsRunsTargetedSnapshot` | schedule `[tenant]` only; ids discarded |
| R1-08 | (this file) | `git cat-file -e` on every SHA below | prior REPORT SHAs did not exist |
| R1-10 | `c9e9015a6b96231f161ed598417d99574c4508a3` | `testListTopUnlabeledResolvesMembersTableFromWpdbPrefix` | `str_replace` silent-empty when name lacks `acx_clusters` |
| R1-11 | `docs/workbay/contracts/clustering-api.md` (tracked, committed) | n/a (contract prose) | — |
| R1-12 | `d98bd9f4f2ef28c23f7ddb147191c5efa8676248` | `testMapTopUnlabeledTreatsObservedEqualToCapAsExactCount` | `observed==cap` treated as truncation |
| R1-13 | `ae8c148ac30fc1b851ced2e577641587b4dfef26` + `8cc387ea9018359ecca306652be2bda6a7a40855` | `testRepairTargetedProjectionNoopsOnEmptyIds` / `testMapClusterListNonPositivePreviewLimitIsNotTruncation` | empty/whitespace ids still scheduled; `preview=0` as cap |
| R1-14 | `f70e69f6e64949707255ccfd081f9fedbc854cbc` | `testMapClusterListReturnsObservedCountAndLogsWhenObservedBelowPreviewLimit` | rename |

## Files

- `src/sovereign/mappers/class-cluster-response-mapper.php`
- `src/sovereign/repositories/class-clusters-read-repository.php`
- `src/sovereign/repositories/trait-resolves-identity-members-table-name.php`
- `src/sovereign/repositories/interface-identity-members-repository.php`
- `src/sovereign/class-cluster-facade.php`
- `src/api/services/class-cluster-read-service.php`
- `src/api/services/class-cluster-projection-sync-service.php`
- `src/api/class-clusters-controller.php`
- `packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json`
- `packages/shared-contracts/schemas/recognition-cluster-list-response.schema.json`
- `docs/workbay/contracts/clustering-api.md` (R1-11, tracked)

## Canon IDs

| ID | file:line | how |
|---|---|---|
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | observed member count is SoR in both drift directions |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | members table is SoR; projected column not republished |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | seeded SQL evaluator + upward-drift count; mutants went red |
| RES-12 | `~/uxw2/canon/lexicons/engineering.md:123` | correlated `COUNT(*)` / one drift scan; no PHP N+1 |
| HAI-01 | `~/uxw2/canon/lexicons/interaction-ux.md:210` | queue count/list backed by observed member rows |

## Decisions

- Mapper is the single repair accumulator (R1-04). Dedicated SQL `list_unlabeled_identity_count_drift` covers clusters excluded from the served page (R1-07).
- `repair_targeted_projection` stays async (BR-07) but cron args now include cluster ids; handler runs `perform_targeted_snapshot`.
- Preview/detail fetch is cap+1; `observed > cap` is truncation; `observed == cap` is exact.
- Contract doc `docs/workbay/contracts/clustering-api.md` is tracked and committed.

## Undone

(empty)

## Commits (lane, `git rev-parse`)

- `41b54bd4447e37aab460c85fc8f3afdbce967473` `fix(sovereign): UXW2-2 identity_count reflects observed members`
- `5463596c7e7b770e6e55b874c0295bbfdf41bb9e` `fix(sovereign): UXW2-2 exclude memberless clusters from top-unlabeled`
- `4324a9a69c88f5d6682619ea17393cb942196446` `fix(sovereign): UXW2-2 golden identity_count matches observed members`
- `d282abe33e8e807f1bca04750369c4fc24455ecb` `docs: UXW2-2 REPORT.md` (superseded)
- `f70e69f6e64949707255ccfd081f9fedbc854cbc` `fix(sovereign): UXW2-2-R1-02 R1-14 bidirectional identity_count`
- `d98bd9f4f2ef28c23f7ddb147191c5efa8676248` `fix(sovereign): UXW2-2-R1-12 cap-hit fetch limit plus one`
- `cc5a93219be059a8effc6c56d91db7448ed216ce` `fix(sovereign): UXW2-2-R1-03 drop memberless top-unlabeled rows`
- `5e27822486c921ff9a2001a0a73348e36671d12f` `fix(sovereign): UXW2-2-R1-01 R1-05 member count is sole size predicate`
- `c9e9015a6b96231f161ed598417d99574c4508a3` `fix(sovereign): UXW2-2-R1-10 resolve identity members table via prefix`
- `e794dbe050b240cf93878a5ed7161ab234fa5647` `fix(sovereign): UXW2-2-R1-10 resolve identity members table via prefix trait`
- `ae8c148ac30fc1b851ced2e577641587b4dfef26` `fix(sovereign): UXW2-2-R1-04 R1-07 R1-13 mapper-owned targeted repair`
- `9b4d30016c99caf76773f1dcd882a52036c2d6e4` `fix(sovereign): UXW2-2-R1-06 schema minItems and golden validation`
- `8cc387ea9018359ecca306652be2bda6a7a40855` `fix(sovereign): UXW2-2-R1-07 R1-13 targeted heal test follow-through`
- `09efde7c3ef75a8962dc7ab86a428f0a7ffd06dd` `fix(sovereign): UXW2-2-R1-07 R1-06 plugin-load targeted heal and minItems`
- `6c741dbbbd5eb678a64cdf0a9b7ccf853c155579` `docs: UXW2-2-R1-08 REPORT.md`
- `da15978a1465019ed03c62368089006d75833ea2` `docs: UXW2-2-R1-08 pin REPORT HEAD SHA`
- `316ea93964e2c225bf8db1bc7fb4f93beb24f395` `docs: UXW2-2-R1-08 rewrite REPORT.md`
- `002767d655764ac56ff5c621205ad9b2328c1c89` `docs: UXW2-2-R1-08 complete commit list`

HEAD: `ba3e343171f1264808ffe249c96cb6bde2aaaaf6`

---

# UXW2-2 R2 REPORT

Folded from root `REPORT.md` (removed). Canonical branch `feature/uxw2-2`; this lane commits on `master` as specified. Contract `docs/workbay/contracts/clustering-api.md` is tracked and was edited+committed.

Suite: **OK (1799 tests, 8654 assertions)** (`cd apps/prototype-wp-alt-context && composer test`). `python3 scripts/check_shared_contract_fixtures.py` green. Cite by subject; SHAs below are from `git log --format=%H` on this tree.

## RED

| Finding | RED proof |
|---|---|
| R2-02 / R1-06 / R1-09 | `testProxySuccessGoldenValidatesAgainstSchema`: `UnexpectedValueException: $.clusters[0] required tenant_id`. `testNormalizeTopUnlabeledResponseDropsEmptyRepresentativeRows`: `Failed asserting that actual size 2 matches expected size 1.` |
| R2-03 / R1-07 | Revert `:110-121`: `Failed asserting that two arrays are identical` — expected `targetedCalls[tenant-1, cluster-a]`, actual `[]`. |
| R2-04 | Deleted `TopUnlabeledSchemaGoldenTest::testEmptyRepresentativesViolateMinItems` (`0 < 1` tautology). |
| R2-05 | Restored `assertCount(2,$events)` + args-shape. `testListTopUnlabeledReadSchedulesAtMostTwoBootstrapEvents` pins ceiling. |
| R2-06 | `testListTopUnlabeledEnvelopeDoesNotReportFilterAsPagingTruncation`: `Failed asserting that 2 is identical to 1.` |
| R2-07 | `testMapTopUnlabeledDoesNotPublishTruncatedObservedAsExactWhenProjectedIsStaleLow`: `Failed asserting that 5 is identical to 4.` |
| R2-08 | `testMapTopUnlabeledDropsSingleObservedMemberWhenNotCapTruncated`: `Failed asserting that actual size 1 matches expected size 0.` |
| R2-09 | `testListTopUnlabeledCapsAndCollidesOverlappingRepairBatches`: `Failed asserting that actual size 2 matches expected size 1.` |
| R2-10 | Negative case: `Failed asserting that '' contains "cluster ids"`. |
| R2-11 | `testListTopUnlabeledMergesOffPageDriftIdsIntoRepairEvent` carries `cluster-off-page` + mapper id. Removing extra_ids merge turns it red. |
| R2-12 | Empty served + `total:5` + `repair_pending` must mount Resync; drain-only copy forbidden. |
| R2-13 | Exact WHERE string; OR-column mutant `COUNT(m)>=2 OR c.identity_count>=2` changes the string and the simulator includes memberless. |
| R1-08 | Prior report SHAs / false contract-doc tracking claims. This file is the rewrite. |

## GREEN

`cd apps/prototype-wp-alt-context && composer test`
**OK (1799 tests, 8654 assertions)**

FE: `useWorkbenchFindings` / `WorkbenchFindingsPanel` / `ReviewQueue` / `representativeVocabulary.source` — 175 passed.

## Closure

| Finding | Commit (subject) | Test | Mutant / RED |
|---|---|---|---|
| R2-01 / R1-08 | `docs: UXW2-2-R2-01 R1-08 rewrite REPORT.md` | `git cat-file -e` on every SHA | prior SHAs / false contract-doc tracking claims |
| R2-02 / R1-06 / R1-09 | `fix(sovereign): UXW2-2-R2-02 R1-06 R1-09 drop empty-rep proxy rows` | `testProxySuccessGoldenValidatesAgainstSchema` / `testProxyCanonicalEnvelopeGoldenValidatesAgainstSchema` / `testNormalizeTopUnlabeledResponseDropsEmptyRepresentativeRows` | empty `representatives` size 2≠1 |
| R2-03 / R2-10 / R1-07 | `fix(sovereign): UXW2-2-R2-03 R2-10 R1-07 targeted bootstrap dispatch` | `testHandleBootstrapSyncWithClusterIdsRunsTargetedSnapshot` / `testHandleBootstrapSyncLogsWhenIdsSuppliedToNonTargetedJob` | revert targeted branch → `targetedCalls []` |
| R2-04 | `fix(sovereign): UXW2-2-R2-04 delete tautological schema golden test` | `ClusterTopUnlabeledSchemaConsistencyTest::testMemberlessPayloadFailsMinItems` | tautology `count([]) < 1` deleted |
| R2-05 | `fix(sovereign): UXW2-2-R2-05 restore exact bootstrap event counts` | `testListTopUnlabeledReadSchedulesAtMostTwoBootstrapEvents` | extra event exceeds `assertCount(2)` |
| R2-06 / R2-09 / R2-11 | `fix(sovereign): UXW2-2-R2-06 R2-09 R2-11 envelope total and repair cap` | `testListTopUnlabeledEnvelopeDoesNotReportFilterAsPagingTruncation` / `testListTopUnlabeledCapsAndCollidesOverlappingRepairBatches` / `testListTopUnlabeledMergesOffPageDriftIdsIntoRepairEvent` | total 2≠1; 2 events≠1; drop extra_ids merge |
| R2-07 / R2-08 | `fix(sovereign): UXW2-2-R2-07 R2-08 mapper drop lt2 and stale-truncation count` | `testMapTopUnlabeledDoesNotPublishTruncatedObservedAsExactWhenProjectedIsStaleLow` / `testMapTopUnlabeledDropsSingleObservedMemberWhenNotCapTruncated` | 5≠4; size 1≠0 |
| R2-12 | `fix(sovereign): UXW2-2-R2-12 repair_pending drives resync not drain` | `R2-12: repair_pending from the envelope drives the resync gate` / ReviewQueue + panel Resync tests | drain-only while total>served |
| R2-13 | `fix(sovereign): UXW2-2-R2-13 exact top-unlabeled WHERE clause` | `testListTopUnlabeledExcludesMemberlessClusterWhenSeeded` | OR-column changes exact WHERE |

R1 mapper/schema commits still on this branch (subject): `fix(sovereign): UXW2-2-R1-01 R1-05 member count is sole size predicate`; `fix(sovereign): UXW2-2-R1-02 R1-14 bidirectional identity_count`; `fix(sovereign): UXW2-2-R1-03 drop memberless top-unlabeled rows`; `fix(sovereign): UXW2-2-R1-04 R1-07 R1-13 mapper-owned targeted repair`; `fix(sovereign): UXW2-2-R1-06 schema minItems and golden validation`; `fix(sovereign): UXW2-2-R1-10 resolve identity members table via prefix`; `fix(sovereign): UXW2-2-R1-12 cap-hit fetch limit plus one`; `fix(sovereign): UXW2-2-R1-07 R1-13 targeted heal test follow-through`.

## Files

- `src/sovereign/mappers/class-cluster-response-mapper.php`
- `src/api/services/class-cluster-read-service.php`
- `src/api/services/class-cluster-response-envelope-service.php`
- `src/api/class-api.php`
- `packages/shared-contracts/schemas/recognition-cluster-top-unlabeled-response.schema.json`
- `docs/workbay/contracts/clustering-api.md`
- FE: `useWorkbenchFindings.ts`, `ReviewQueue.tsx`, `WorkbenchFindingsPanel.tsx`, `clusterApiQueries.ts`, `types/cluster.ts`, `representativeVocabulary.ts`
- tests + goldens as in commits

## Canon IDs

| ID | file:line | how |
|---|---|---|
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | observed vs projected; truncated observed is not exact |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | members table SoR; mapper drop `< 2` matches SQL |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | RED then GREEN; mutants killed |
| TEST-06 | `~/uxw2/canon/lexicons/engineering.md:387` | predicted failure messages captured |
| REF-25 | `~/uxw2/canon/lexicons/engineering.md:344` | closed remaining R1 gaps instead of leaving them |
| OBS-08 | `~/uxw2/canon/lexicons/engineering.md:478` | log when ids supplied to non-targeted job |
| RLSE-04 | `~/uxw2/canon/lexicons/engineering.md:695` | repair is a designed state, not silent drain |
| A11Y-06 | `~/uxw2/canon/lexicons/accessibility.md:74` | live-region names repair, not drain-only |

## Decisions

- Proxy: filter empty-rep rows (not a schema carve-out).
- Truncation + stale-low projected: republish projected column, request repair.
- Mapper and SQL share threshold `< 2`.
- `truncated` is paging only (`fetched_page >= limit`). `total` subtracts mapper drops.
- Repair batch: sort + cap 25 so overlapping reads collide; skip drift scan when mapper already filled the ceiling; otherwise merge off-page ids.
- FE Resync keys off `repair_pending` (envelope) plus empty-served-with-remaining-total.

## Undone

Closed in R3 below.

---

# UXW2-2 R3 REPORT

Lane cwd. Branch `master` (canonical `feature/uxw2-2`). Cite by subject; SHAs from `git log --format=%H` on this tree. Root `REPORT.md` removed.

Suite: **OK (1807 tests, 8691 assertions)** (`cd apps/prototype-wp-alt-context && composer test`). `python3 scripts/check_shared_contract_fixtures.py` green. `php -l` clean on changed PHP. `test ! -f REPORT.md`.

R2-04 verify: `test ! -f apps/prototype-wp-alt-context/tests/Unit/TopUnlabeledSchemaGoldenTest.php` — absent. Replacement: `ClusterTopUnlabeledSchemaConsistencyTest::testMemberlessPayloadFailsMinItems`.

## RED

| Finding | RED proof |
|---|---|
| R3-01 / R2-01 / R1-08 | Root `REPORT.md` gone; contract-tracking falsehoods deleted. |
| R2-02 / R1-06 / R1-09 / R2-12 backend | Mutant A `representatives=[]` on served proxy golden: `UnexpectedValueException: $.clusters[0].representatives minItems`. Mutant B delete `repair_pending`: `Failed asserting that null is true.` (`testTopUnlabeledProxyDropSetsRepairPending`) |
| R2-06 residual | `testListTopUnlabeledFullLastPageIsNotTruncated`: `Failed asserting that true is false.` |
| R2-07 residual | `testMapTopUnlabeledTruncatedCountNeverBelowPreviewLength`: `Failed asserting that 1 is equal to 4 or is greater than 4.` |
| R2-11 residual | Mutant delete `\|\| $dropped > 0`: `Failed asserting that false is true.` |
| R2-09 | Mutant merge→sort→slice: `Failed asserting that two arrays are identical.` Mutant delete `sort( $top_up )`: `Failed asserting that two arrays are identical.` Mutant delete skip-scan guard: `Failed asserting that 1 is identical to 0.` |
| R3-04 | `testListTopUnlabeledTotalIsPreFilterQualifyingCount`: `Failed asserting that 1 is identical to 2.` |
| R3-02 | Same commits as the code that implements each rule. `even if stale-low` / `fetched_page >= limit` gone. |
| R2-05 | Duplicate `schedule_repair_from_mapper` stayed GREEN (dedupe). Mutant extra `wp_schedule_single_event` (same tenant args): `Failed asserting that actual size 3 matches expected size 2.` |
| R2-04 | Verify only. File absent. |

## GREEN

`cd apps/prototype-wp-alt-context && composer test`
**OK (1807 tests, 8691 assertions)**

## Closure

| Finding | Commit (subject) | Test | Mutant / RED |
|---|---|---|---|
| R3-01 / R2-01 / R1-08 | `docs: UXW2-2-R3-01 R2-01 R1-08 fold report and drop root REPORT.md` | `git cat-file -e`; `test ! -f REPORT.md` | dead SHAs / contract-tracking falsehoods |
| R2-02 / R1-06 / R1-09 / R2-12 backend | `fix(api): UXW2-2-R2-02 R1-06 R1-09 R2-12 proxy goldens and repair_pending` | `testProxySuccessGoldenValidatesAgainstSchema` / `testTopUnlabeledProxyDropSetsRepairPending` | `minItems`; `null is true` |
| R2-06 residual | `fix(api): UXW2-2-R2-06 truncated is total_count greater than fetched_page` | `testListTopUnlabeledFullLastPageIsNotTruncated` | `true is false` |
| R2-07 residual | `fix(sovereign): UXW2-2-R2-07 truncated identity_count never below preview` + `fix(contracts): UXW2-2-R2-07 restore truncated clustering-api.md tail` | `testMapTopUnlabeledTruncatedCountNeverBelowPreviewLength` | `1 is equal to 4 or is greater than 4` |
| R2-11 residual | `fix(tests): UXW2-2-R2-11 drop without mapper id sets repair_pending` | `testListTopUnlabeledDropWithoutMapperRepairIdSetsRepairPending` | `false is true` |
| R2-09 | `fix(api): UXW2-2-R2-09 mapper ids take the repair-batch ceiling` | eviction / sort / skip-scan tests | arrays not identical; `1 is identical to 0` |
| R3-04 | `fix(api): UXW2-2-R3-04 total is pre-filter qualifying count` | `testListTopUnlabeledTotalIsPreFilterQualifyingCount` | `1 is identical to 2` |
| R3-02 | same commits as items 2/3/4/7 | contract grep | `even if stale-low` / `fetched_page >= limit` gone |
| R2-05 | `fix(tests): UXW2-2-R2-05 prove bootstrap event ceiling via call log` | `testListTopUnlabeledReadSchedulesAtMostTwoBootstrapEvents` | call-log size 3≠2 |
| R2-04 | (verify only) | `test ! -f …/TopUnlabeledSchemaGoldenTest.php` | tautology already gone |

## Decisions

- Proxy goldens carry ≥1 schema-valid served row; empty-rep upstream rows set `repair_pending` on both legs.
- `truncated` = `total_count > fetched_page` (full last page is not truncated).
- Truncated `identity_count = max(projected, representatives.length)`.
- Mapper ids take the repair-batch ceiling; extras top up sorted; skip drift scan at 25 mapper ids.
- `total` is pre-filter `COUNT(*) OVER()`. Drops (identity_count/member mismatch after SQL `COUNT(m) >= 2`) set `repair_pending` and do not shrink `total`.
- Event ceiling is the append-only `wp_schedule_single_event` call log, not the keyed cron map.

## Canon IDs

| ID | how |
|---|---|
| REF-09 | observed vs projected; one envelope rule both legs |
| REF-25 | closed remaining R1/R2 gaps |
| DATA-14 | members SoR; drop still possible after SQL `COUNT(m) >= 2` |
| TEST-15 | every mutant RED with pasted line |
| TEST-06 | predicted failure messages captured |
| RLSE-04 | `repair_pending` is a designed state |
| OBS-08 | skip-scan + event-volume spy |
| rg-015 | envelope metadata matches behaviour |
| rg-005 | `total` / `total_count` column semantics documented |

## Commits (R3, `git log --format=%H`)

- `7d3cd7ce77634819a3e333c114ffa3581854266b` `docs: UXW2-2-R3-01 R2-01 R1-08 fold report and drop root REPORT.md`
- `f500a5aef59d9e10b598fba79a649c05e205a77a` `fix(api): UXW2-2-R2-02 R1-06 R1-09 R2-12 proxy goldens and repair_pending`
- `0f4fdbe91a04831aa669c28078a986935bf5cb58` `fix(api): UXW2-2-R2-06 truncated is total_count greater than fetched_page`
- `489b10e0fa80d442f7d99ab23371104b6cc3874f` `fix(sovereign): UXW2-2-R2-07 truncated identity_count never below preview`
- `718f1910648c6ca90bdd8f91e79511695acac12a` `fix(contracts): UXW2-2-R2-07 restore truncated clustering-api.md tail`
- `a3d98ba77c38c55d4e6698576c80e9e7ac460b34` `fix(tests): UXW2-2-R2-11 drop without mapper id sets repair_pending`
- `05a1bd77df841dc43e09ab6ed6e48966084bcb35` `fix(api): UXW2-2-R2-09 mapper ids take the repair-batch ceiling`
- `5fe62c00b4fceb5483ea070137e30ec477030abf` `fix(api): UXW2-2-R3-04 total is pre-filter qualifying count`
- `28e3a2423c9de81c25ee37b18b92dace5ea63946` `fix(tests): UXW2-2-R2-05 prove bootstrap event ceiling via call log`

HEAD at report time (parent of this report commit): `28e3a2423c9de81c25ee37b18b92dace5ea63946`

## Undone

(empty) 
