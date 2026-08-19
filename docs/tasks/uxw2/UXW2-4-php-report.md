# UXW2-4-PHP — persons are the single label authority

Recovered PHP-lane section from the historical root `REPORT.md` blob. That object does not resolve in this clone (`git show` of the named commit is invalid here). Body is the PHP section only — the FE half is omitted because it already lives at `docs/tasks/uxw2/UXW2-4-fe-report.md`. Root `REPORT.md` is not restored (its removal was intentional). Any 40-hex tokens from the lane-mirror record are replaced with commit subject lines.

## Result

`acx_persons` is the only human-label authority. Delete returns faces to the unlabeled queue; label writes bind a person; Library reads cannot show a name Roster cannot reach.

## RED

| Commit (historical numbering) | Test | Failure |
| --- | --- | --- |
| 1 | `PersonCrudTest::testDeletePersonClearsHumanLabelAndReturnsClusterToUnlabeledQueue` | `Failed asserting that 'Tory Guzman' is null.` |
| 2 | `ClusterMergeServiceTest::testMergeClusterWithTargetLabelBindsPerson` | 0 person inserts |
| 2 | `ClusterSnapshotMergerTest::testLabelOnlyUpsertBindsPersonForHumanLabel` | empty person inserts |
| 2 | `ClusterLabelServiceTest::testProxyLabelWriteStillCreatesLocalPerson` | 0 person inserts |
| 3 | `IdentityMembersRepositoryTest::testListForMediaIdsDoesNotFallBackToRawHumanLabel` | still `COALESCE(p.name, c.label)` |
| 3 | `PersonLabelBackfillServiceTest` | class not found |

TEST-15: each assertion was watched fail on the old path before implementation.

## GREEN

**1773 tests, 8568 assertions.**

## Files

- `src/api/class-api.php` — `delete_person` clears via `reset_curation` (`label = NULL`, `is_user_confirmed = 0`, `curation_state = uncurated`) and enqueues `cluster_person_unbound` + `cluster_label_updated` with `label => null`. Historical note: this write used existing Api transaction helpers (not `run_transactional`); later slices converted it.
- `src/api/services/class-cluster-merge-service.php` — target relabel `bind_person_to_cluster`.
- `src/api/services/class-cluster-label-service.php` — proxy branch `resolve_or_create` + bind.
- `src/sovereign/repositories/class-cluster-snapshot-merger.php` — batch backfill.
- `src/sovereign/repositories/class-identity-members-read-repository.php` — CASE, no COALESCE.
- `src/api/services/class-person-label-backfill-service.php` + `src/cli/class-bind-unbound-labels-command.php` (`wp acx bind-unbound-labels`).
- contracts: `clustering-api.md`, `cluster-snapshot-api.md`, `curation-sync-api.md` (force-added in the lane mirror; `docs/workbay/contracts/` was gitignored there).

## Canon

DATA-14, ARCH-02, REF-09, FLOW-06, HAI-17, TEST-15, rg-007, sr-009.

## Decisions

- `curation_state='uncurated'` (column is NOT NULL), not SQL NULL.
- Reused `cluster_label_updated` (`label=null`).
- Proxy label path creates a person row.
- Snapshot/CLI heal uses a no-op `person_created` enqueue.
- `delete_person` kept existing Api transaction helpers (not converted to `run_transactional`).
- Contract gitignore; three updated files force-added.

## Undone

- FE copy `"Just label — don't add to roster"`.
- `delete_person` → `run_transactional` (done on later slices; left here as the historical undone row).
- Heal of live #6731 — operator `wp acx bind-unbound-labels` if the option never stamped.

## Commits

- `fix(api): UXW2-4 delete_person returns faces to the review queue`
- `fix(sovereign): UXW2-4 label writes always bind a person`
- `fix(sovereign): UXW2-4 media identities read no longer falls back to raw human labels`
