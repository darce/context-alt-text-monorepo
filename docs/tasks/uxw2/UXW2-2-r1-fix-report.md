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
| R1-11 | disk-only `docs/workbay/contracts/clustering-api.md` (gitignored, harvested) | n/a (contract prose) | — |
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
- disk-only: `docs/workbay/contracts/clustering-api.md` (R1-11)

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
- Contract docs stay gitignored here; edited in place for harvest.

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
