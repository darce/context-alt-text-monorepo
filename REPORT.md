# UXW2-2 R2 REPORT

Single report (root `REPORT.md`). `docs/tasks/uxw2/UXW2-2-r1-fix-report.md` is not in this tree. Contract doc `docs/workbay/contracts/clustering-api.md` is tracked and was edited+committed (`git add -f`).

Branch `master`. Suite: **OK (1799 tests, 8654 assertions)** (`cd apps/prototype-wp-alt-context && composer test`). `composer lint` not defined. `python3 scripts/check_shared_contract_fixtures.py` green. `php -l` clean on changed PHP. FE specs for R2-12: 175 passed.

SHAs below are **lane SHA (non-portable)** — cite by subject line after `git am`. HEAD at report time = parent of this commit.

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

| Finding | Commit (subject; lane SHA non-portable) | Test | Mutant / RED |
|---|---|---|---|
| R2-01 / R1-08 | this file (`docs: UXW2-2-R2-01 R1-08 rewrite REPORT.md`) | `git cat-file -e` on every SHA | prior SHAs / false contract-doc tracking claims |
| R2-02 / R1-06 / R1-09 | `fix(sovereign): UXW2-2-R2-02 R1-06 R1-09 drop empty-rep proxy rows` `875289ad6a0fdb0a0c26ff1d9a988a93c6983bbc` | `testProxySuccessGoldenValidatesAgainstSchema` / `testProxyCanonicalEnvelopeGoldenValidatesAgainstSchema` / `testNormalizeTopUnlabeledResponseDropsEmptyRepresentativeRows` | empty `representatives` size 2≠1 |
| R2-03 / R2-10 / R1-07 | `fix(sovereign): UXW2-2-R2-03 R2-10 R1-07 targeted bootstrap dispatch` `25edba14a4db5fec0e5886d7a903b6ec9883dae5` | `testHandleBootstrapSyncWithClusterIdsRunsTargetedSnapshot` / `testHandleBootstrapSyncLogsWhenIdsSuppliedToNonTargetedJob` | revert targeted branch → `targetedCalls []` |
| R2-04 | `fix(sovereign): UXW2-2-R2-04 delete tautological schema golden test` `d67e6b0d8a9b9bda16896f8286d8445022a29cef` | `ClusterTopUnlabeledSchemaConsistencyTest::testMemberlessPayloadFailsMinItems` | tautology `count([]) < 1` deleted |
| R2-05 | `fix(sovereign): UXW2-2-R2-05 restore exact bootstrap event counts` `3ed84ea88b8f342d43d6b57a5f5b77381fc538b8` | `testListTopUnlabeledReadSchedulesAtMostTwoBootstrapEvents` | extra event exceeds `assertCount(2)` |
| R2-06 / R2-09 / R2-11 | `fix(sovereign): UXW2-2-R2-06 R2-09 R2-11 envelope total and repair cap` `ce2f1ae5817742d42d3ba89a1cc3be2ebaf82511` | `testListTopUnlabeledEnvelopeDoesNotReportFilterAsPagingTruncation` / `testListTopUnlabeledCapsAndCollidesOverlappingRepairBatches` / `testListTopUnlabeledMergesOffPageDriftIdsIntoRepairEvent` | total 2≠1; 2 events≠1; drop extra_ids merge |
| R2-07 / R2-08 | `fix(sovereign): UXW2-2-R2-07 R2-08 mapper drop lt2 and stale-truncation count` `d8b289a7d135c7f723e6f9697216e35369784f1b` | `testMapTopUnlabeledDoesNotPublishTruncatedObservedAsExactWhenProjectedIsStaleLow` / `testMapTopUnlabeledDropsSingleObservedMemberWhenNotCapTruncated` | 5≠4; size 1≠0 |
| R2-12 | `fix(sovereign): UXW2-2-R2-12 repair_pending drives resync not drain` `07498b7be812f9c1e17c7fd805f148257fd5cbe4` | `R2-12: repair_pending from the envelope drives the resync gate` / ReviewQueue + panel Resync tests | drain-only while total>served |
| R2-13 | `fix(sovereign): UXW2-2-R2-13 exact top-unlabeled WHERE clause` `9dfeddcd1fb30c2f79ec50fb93cca78f767b00c2` | `testListTopUnlabeledExcludesMemberlessClusterWhenSeeded` | OR-column changes exact WHERE |

R1 mapper/schema commits still on this branch (lane SHA, non-portable): `5e27822486c921ff9a2001a0a73348e36671d12f` R1-01/05; `f70e69f6e64949707255ccfd081f9fedbc854cbc` R1-02/14; `cc5a93219be059a8effc6c56d91db7448ed216ce` R1-03; `ae8c148ac30fc1b851ced2e577641587b4dfef26` R1-04/07/13; `9b4d30016c99caf76773f1dcd882a52036c2d6e4` R1-06 schema; `c9e9015a6b96231f161ed598417d99574c4508a3` R1-10; `d98bd9f4f2ef28c23f7ddb147191c5efa8676248` R1-12; `8cc387ea9018359ecca306652be2bda6a7a40855` R1-13 follow-through.

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

None for this lane.

## HEAD at report time

`07498b7be812f9c1e17c7fd805f148257fd5cbe4` (parent of this report commit; lane SHA, non-portable)
