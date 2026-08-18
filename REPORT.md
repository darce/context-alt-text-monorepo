# UXW2-4-PHP — persons are the single label authority

## Result
`acx_persons` is the only human-label authority. Delete returns faces to the unlabeled queue; label writes bind a person; Library reads cannot show a name Roster cannot reach.

## RED
| Commit | Test | Failure |
| --- | --- | --- |
| 1 | `PersonCrudTest::testDeletePersonClearsHumanLabelAndReturnsClusterToUnlabeledQueue` | `Failed asserting that 'Tory Guzman' is null.` |
| 2 | `ClusterMergeServiceTest::testMergeClusterWithTargetLabelBindsPerson` | 0 person inserts |
| 2 | `ClusterSnapshotMergerTest::testLabelOnlyUpsertBindsPersonForHumanLabel` | empty person inserts |
| 2 | `ClusterLabelServiceTest::testProxyLabelWriteStillCreatesLocalPerson` | 0 person inserts |
| 3 | `IdentityMembersRepositoryTest::testListForMediaIdsDoesNotFallBackToRawHumanLabel` | still `COALESCE(p.name, c.label)` |
| 3 | `PersonLabelBackfillServiceTest` | class not found |

TEST-15: each assertion was watched fail on the old path before implementation.

## GREEN
`composer test` in `apps/prototype-wp-alt-context`: **1773 tests, 8568 assertions, OK**.

## Files
- `src/api/class-api.php` — delete clears `label`, `is_user_confirmed=0`, `curation_state=uncurated`; enqueues `cluster_person_unbound` + `cluster_label_updated`
- `src/api/services/class-cluster-merge-service.php` — target relabel `resolve_or_create` + bind
- `src/api/services/class-cluster-label-service.php` — proxy branch persists a local person
- `src/sovereign/repositories/class-cluster-snapshot-merger.php` — batch backfill
- `src/sovereign/repositories/class-identity-members-read-repository.php` — CASE, no COALESCE fallback
- `src/api/services/class-person-label-backfill-service.php` + `src/cli/class-bind-unbound-labels-command.php` (`wp acx bind-unbound-labels`)
- contracts: `clustering-api.md`, `cluster-snapshot-api.md`, `curation-sync-api.md`

## Canon (grepped)
| ID | File:line | How |
| --- | --- | --- |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | persons own the human name; cluster.label is derived/auto |
| ARCH-02 | `~/uxw2/canon/lexicons/engineering.md:552` | single writer for the label: person bind path |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | Library no longer reads a mirrored raw cluster label |
| FLOW-06 | `~/uxw2/canon/lexicons/engineering.md:268` | snapshot + CLI backfill heal unbound human labels |
| HAI-17 | `~/uxw2/canon/lexicons/interaction-ux.md:226` | Roster can now reach every human label the store holds |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | RED captured before each implement |
| rg-007 | `docs/workbay/constitution.md:42` | backfill stall cap `MAX_STALLS=3` |
| sr-009 | `docs/workbay/constitution.md:26` | merge/label bind inside `run_transactional` |

## Decisions
- `curation_state='uncurated'` (column is NOT NULL), not SQL NULL.
- Reused `cluster_label_updated` (`label=null`) so the backend learns the name is gone; did not invent an op.
- Proxy label path creates a person row (schema allows person without projected clusters). No `roster_bound:false`.
- Snapshot/CLI heal uses a no-op person_created enqueue (persons are local-only).
- `delete_person` kept the existing Api transaction helpers (not converted to `run_transactional`).
- `docs/workbay/contracts/` is gitignored here; the three updated files were force-added.

## Undone
- FE copy `"Just label — don't add to roster"` (PHP-only lane).
- `delete_person` → `run_transactional` refactor.
- Heal of live #6731 (needs `wp acx bind-unbound-labels` on the site).

## Commits
- `2b850d3` `fix(api): UXW2-4 delete_person returns faces to the review queue`
- `4eb8a9b` `fix(sovereign): UXW2-4 label writes always bind a person`
- `2a6775a` `fix(sovereign): UXW2-4 media identities read no longer falls back to raw human labels`

HEAD: 2a6775a9ad94a6db1c50f64bc0cf9e77e81b2e4d (code) + this REPORT commit
