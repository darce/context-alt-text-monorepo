# UXW2-4-R3 — PHP + contracts close

## Result

Tombstone is **label-value**, not version-ordered. `roster_bound` is derived from a distinguishable bind outcome. `update_person` is tenant-scoped. Heal cap returns. Report cites **subjects only**.

Root `REPORT.md` was `git rm`'d: it was the FE lane's R1-15..31 record (wrong location, three dead SHAs). Not migrated into any `*-fe-report*.md`.

## RED (before each fix)

| Item | Test | Failure |
| --- | --- | --- |
| 1 | `testClearedLabelSurvivesSnapshotVersion` `"newer than cleared_rev" (14, 15)` | `locally cleared label must not be backfilled from a stale snapshot / actual size 1 matches expected size 0` |
| 1 | same, `"locally created cluster" (0, 1)` | same |
| 2 | `WpdbStubTest::testUpdateReturnsZeroWhenNoRowMatches` | `Failed asserting that 1 is identical to 0` |
| 3 | `testMergeReportsRosterBoundFalseWhenBindMatchesNoRow` | `Failed asserting that true is false` |
| 3 | `testLocalLabelWriteReportsRosterBoundFalseWhenClusterRowVanished` | `Failed asserting that true is false` |
| 4 | `testUpdatePersonDoesNotTouchOtherTenantRow` | expected `Bob`, got `Alice Renamed` |
| 5 | `testDeletePersonSurfacesDatabaseFailureAsServerError` | expected `acx_db_error`, got `acx_person_not_found` |
| 6 | `testCreateLocalClusterBindsResolvedPersonAndStoresItsName` | expected `Ada Lovelace (2)`, got `Ada Lovelace` |
| 7 | `testCreateForIdentitySurfacesNameCollisionAs409` | expected `acx_name_collision`, got `acx_db_error` |
| 8 | `testHealDoesNotRunAgainOnceThePerLoadCapIsHit` | `Failed asserting that 2 is identical to 1` |
| 8 | `testRenderLabelHealNoticeNamesTheRemedyWhenTenantIsUnresolved` | notice lacked `role="status"` |
| 9 | `testListLabelsExcludesReservedAndUnboundLabels` | expected `['Ada Lovelace']`, got `[]` |
| 10 | fixture change to `'Tory Guzman'` | **did not fail** — mapper/controller already nulled unbound humans; fixture is now load-bearing |
| 13 | `testLocalMergeResponseKeysMatchTheContract` | written after local `roster_bound` landed; pins the 6-key body |

## TEST-15

| Item | Mutant | Result |
| --- | --- | --- |
| 1a | `$keep_cleared = false;` | RED all 4 data-sets: `actual size 1 matches expected size 0` |
| 1b | revert to `$cleared_rev > 0 && $snapshot_version <= $cleared_rev` | RED on `>` and local-0: same message |
| 2 | n/a (stub count) | pre-fix RED above |
| 3a at HEAD | `$data['roster_bound'] = true;` | SURVIVED GREEN (`ClusterMergeServiceTest` 8/40) before the new test; after: RED `true is false` at `:233` |
| 3b | `'roster_bound' => true` at label `:220` | RED `true is false` (`testLocalLabelWrite…`) |
| 3c | `return true;` at label `:252` | stayed RED `true is false` (`testProxyLabelWriteReportsRosterBoundFalseWhenBindFails`) |
| 5 | drop `AND tenant_id = %s` on delete SELECT | before fixture rewrite: GREEN; after: RED expected Alice uuid, got Bob uuid |
| 6 | delete `bind_person_to_cluster` block | RED `array has the key 'person_id'` |
| 7 | `return $resolved;` → `return 0;` | RED `acx_name_collision` vs `acx_db_error` |
| 11 at HEAD | delete mapper `if ( '' !== $person ) return $person;` under `--filter testProxyMediaIdentities…` | **SURVIVED GREEN** (OK, 1 test, 4 assertions) — prover reproduced |
| 11 after collapse | same mutant | RED on proxy **and** `testMapAppliesPersonNameOverStaleClusterLabel` (`null` vs `Ada Lovelace`) |

Suites that killed the mapper person-branch **before** collapse: `MemberResponseMapperTest` `:80`/`:128` and local controller test. Proxy filter did **not**. After collapse, proxy filter kills it.

## GREEN

`cd apps/prototype-wp-alt-context && composer test` → **OK (1826 tests, 8763 assertions)**.
Baseline at HEAD was `OK (1810 tests, 8703 assertions)`. +16 tests, +60 assertions. Zero NEW failures vs that baseline.

## Files changed (PHP / tests / docs)

- `class-cluster-snapshot-merger.php`, `class-cluster-curation-writer.php`, `class-life-cycle-manager.php`
- `class-cluster-label-service.php`, `class-cluster-merge-service.php`, `class-cluster-membership-service.php`, `class-person-resolution-service.php`, `class-api.php`
- `class-cluster-projection-writer.php`, `class-clusters-read-repository.php`, `class-clusters-repository.php`, `interface-clusters-repository.php`
- `class-member-response-mapper.php`, `class-media-identities-controller.php`
- `tests/stubs/wp.php`, `tests/stubs/class-null-clusters-repository.php`, `tests/Support/ClusterMutationsTestDoubles.php`
- Unit tests listed in commits; merge golden `tests/fixtures/cluster-mutations/merge_cluster/response.json`
- `docs/tasks/uxw2/UXW2-4-r1-fix-report.md` (dead SHAs purged)
- root `REPORT.md` removed

## Canon (grepped) with `file:line`

| ID | Where | How |
| --- | --- | --- |
| DATA-14 | `class-cluster-snapshot-merger.php:114` | cleared **label** is the authority, not a second write of the name |
| FLOW-06 | `class-cluster-snapshot-merger.php:114` + `class-life-cycle-manager.php:168-201` | snapshot cannot resurrect a user delete; heal is a designed retry |
| TEST-06 | each new test above | watched RED first |
| TEST-15 | mutants table | green can go red |
| RLSE-05 | `class-api.php` delete `false` → `acx_db_error` 500 | crash/error is honest |
| TEST-06 / ARCH-13 | `tests/stubs/wp.php` `update()` | 0-row bind is expressible |
| rg-015 | `class-cluster-merge-service.php:126`, `class-cluster-label-service.php:220` | `roster_bound` from bind outcome |
| REF-09 | `class-cluster-label-service.php:220`, mapper `apply_label_authority` | one authority |
| WEB-08 / ARCH-13 | `class-api.php` `update_person` + `find_by_normalized_name` | tenant on every person query |
| DIAG-01 | delete 500 vs 404; heal notice names CLI | facts before “not found” |
| REF-26 | item 7 + contract diffs below | 409 + reserved shape + tombstone |
| rg-007 / RLSE-04 / OBS-08 | `class-life-cycle-manager.php:168-201`, `:154-165` | cap returns; notice `role="status"` + `wp acx bind-unbound-labels` |
| REF-25 | this report | subjects, not transplanted SHAs |

## Decisions

1. **Tombstone column:** nullable `label_cleared_label` on `wp_acx_clusters`. `reset_curation` copies `label` **before** nulling it. `$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label`. Newer same-name snapshots keep the marker. Different incoming name releases it.
2. **R2-11 measurement:** mapper person-branch already killed by `MemberResponseMapperTest` + local controller; proxy test survived until the controller delegated to the mapper.
3. **Local merge body:** 5 core keys plus `roster_bound` when a label was supplied. Not a `ClusterResponse`. `person_id` stays proxy-only.

**Stub residual (item 1):** `applyInsertOnDuplicateToRows` now keys `(cluster_uuid, tenant_id)` and no longer version-clears `label_cleared_revision`. It still applies `VALUES(label)` unless `is_user_confirmed=1` (that **is** the remaining production SQL). It does **not** evaluate issued `IF()` text.

**Contracts:** `docs/workbay/contracts/` is omitted from version control **in this mirror** (`git ls-files` empty; `.gitignore` line 165). Edited on disk; intended diffs:

```diff
--- clustering-api.md (label authority + merge + create-for-identity)
- auto label (`cluster-%` / unlabeled)
+ auto label (case-insensitive `cluster-` / `cluster_` prefix, or unlabeled)
- Response: `ClusterResponse` for the target cluster (plus person_id / roster_bound …)
+ Local merge 200 keys: source_cluster_id, target_cluster_id, moved_identity_count,
+ synced, status, and roster_bound when a label was supplied. Not a ClusterResponse.
+ roster_bound from real bind: true if updated or already-bound; false if no row.
+ acx_name_collision 409 when suffixes 2..99 exhaust (create-for-identity + revert-merge).

--- cluster-snapshot-api.md
- not `cluster-%`
+ not a reserved `cluster-` / `cluster_` shape
+ label_cleared_revision + label_cleared_label: same-label snapshots do not restore
+ a cleared name, regardless of snapshot_version.
```

`grep -n 'cluster-%' docs/workbay/contracts/clustering-api.md docs/workbay/contracts/cluster-snapshot-api.md` is empty after those edits.

## Undone

- **Item 12 (R3-04):** parity scanner still does not expand trait fragments into a “column only inside the trait, absent from schema” case. `isPlausibleColumnIdentifier` still skips `$this`. Scanner now sees inlined helper calls for `list_labels` / `labeled_only`.
- FE findings R1-15..31 / R2-14..19 (`js/`, `*.scss`, `docs/ux-maps/`) — other lane.

## Commits (subjects)

- `fix(sovereign): UXW2-4-R1-02/R2-02 label-value tombstone`
- `fix(tests): UXW2-4-R3-03 wpdb stub reports 0-row updates`
- `fix(api): UXW2-4-R2-05/R3-05 roster_bound from real bind outcome`
- `fix(api): UXW2-4-R3-02 tenant-scope update_person`
- `fix(api): UXW2-4-R2-07 delete tenant read and db error`
- `fix(sovereign): UXW2-4-R2-08 bind resolved person name on create`
- `fix(api): UXW2-4-R2-12 surface acx_name_collision as 409`
- `fix(api): UXW2-4-R3-01/R2-09/R1-03 heal cap and notice remedy`
- `fix(sovereign): UXW2-4-R1-12 list_labels drops reserved and unbound`
- `fix(tests): UXW2-4-R1-11 local media-identities label authority`
- `fix(api): UXW2-4-R2-11 collapse label authority onto the mapper`
- `fix(tests): UXW2-4-R2-13 pin local merge response keys`
- `fix(tests): UXW2-4 seed tenant rows and keep list SQL literal` (also removed root `REPORT.md`)
- this report commit

Final HEAD: recorded by the integrator in the canonical worktree after transplant.
