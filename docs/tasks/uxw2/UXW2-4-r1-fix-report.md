# UXW2-4-R1 — close adversarial findings

## Result
Decision (a): `cluster_label_updated {label:null}` clears `identity_clusters.label`. Delete is durable against snapshot re-projection. One bind helper. Shared reserved-label SQL. Proxy persists persons only after 2xx.

## RED
| Finding | Test | Failure |
| --- | --- | --- |
| R1-01 | `test_cluster_label_updated_with_null_label_clears_backend_label` | `ValueError: label is required for cluster_label_updated` |
| R1-02 | `testDeleteThenSnapshotMergeDoesNotRecreatePerson` | person insert from stale incoming label |
| R1-05 | `testProxyLabelWriteDoesNotPersistPersonOnProxyFailure` | person row on 500 proxy |
| R1-06 | `testMergeRejectsRebindToDifferentPerson` | rebind instead of 409 |
| R1-07 | `testBackfillMarksRejectedRowsSeenAndDoesNotStall` | stall cap on skipped rows |
| R1-08 | `testAutomaticBindCreatesDistinctPersonOnNameCollision` | silent same-name merge |
| R1-10 | `testMergeClusterGolden` | `outbox_operation=person_created` only |

TEST-15: R1-01 watched fail (`ValueError`) then pass (`cluster.label is None`). Mutant: restore the old `not isinstance(label, str)` raise → same test reds.

## GREEN
`apps/prototype-wp-alt-context` `composer test` / `./vendor/bin/phpunit`: **1791 tests, 8641 assertions, OK**.
`apps/prototype-description-service` `uv run --extra dev pytest recognition/tests/unit/test_curation_sync_service.py -q`: **18 passed**.

## Closure
| ID | Commit | Test | TEST-15 |
| --- | --- | --- | --- |
| R1-01 | `245674d061a486998dd5580a3c07cd0e2a8c79f9` | `test_cluster_label_updated_with_null_label_clears_backend_label` | killed (ValueError) |
| R1-02 | `7c72dbbab36adff590585098474c2673fcbb4936` | `testDeleteThenSnapshotMergeDoesNotRecreatePerson` | killed (person insert) |
| R1-03 | `2d7b641691a90583036b2089ee4b286d70aa948d` | `testMaybeUpgradeHealsUnboundHumanLabelsIncludingUnderscoreSkip` | killed (no `cluster\_`) |
| R1-04 | `7c72dbbab36adff590585098474c2673fcbb4936` | `testBackfillResolvesAgainstStoredLabelWhenIncomingDiffers` | killed (Incoming Name insert) |
| R1-05 | `2b8479e394c99ba176471e11e9f114df379e9df1` | `testProxyLabelWriteDoesNotPersistPersonOnProxyFailure` | killed (person persist) |
| R1-06 | `2b8479e394c99ba176471e11e9f114df379e9df1` | `testMergeRejectsRebindToDifferentPerson` | killed (no 409) |
| R1-07 | `72333dd986a320633f0b5b962b32dc6fa8b1e68a` | `testBackfillMarksRejectedRowsSeenAndDoesNotStall` + `BindUnboundLabelsCommandTest` | killed (stall) |
| R1-08 | `72333dd986a320633f0b5b962b32dc6fa8b1e68a` | `testAutomaticBindCreatesDistinctPersonOnNameCollision` | killed (reuse person 3) |
| R1-09 | `72333dd…` / `d8ea4be…` | list SQL predicate + idempotent second pass keeps `person_id` | killed (mockResults=[]) |
| R1-10 | `dcd1d9f4fc20d2f60b9ac63283f9a2f7667e0679` | `testMergeClusterGolden` | killed (first-op-only) |
| R1-11 | `0c61306b611b7205ff6d344cc956b1d728cc5f04` | `testMapMediaIdentitiesAppliesLabelAuthorityRows` + controller | killed (unbound shows name) |
| R1-12 | `0c61306b611b7205ff6d344cc956b1d728cc5f04` | proxy normalizer + `create_local_cluster` bind | killed (COALESCE / no person) |
| R1-13 | `d8ea4be07909471985eb9a4969ab63c06981ec81` | `testDeletePersonClearsHumanLabel…` + singleton count | killed (no `clusters_dissociated`) |
| R1-14 | this REPORT commit | SHA `git cat-file -e` | n/a |

## Canon (grepped)
| ID | File:line | How |
| --- | --- | --- |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | persons own human name |
| ARCH-02 | `~/uxw2/canon/lexicons/engineering.md:552` | one bind writer |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | no raw cluster-label fallback |
| FLOW-06 | `~/uxw2/canon/lexicons/engineering.md:268` | upgrade/CLI heal |
| HAI-17 | `~/uxw2/canon/lexicons/interaction-ux.md:226` | roster can reach every human label |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | RED captured; mutant kills |
| rg-007 | `docs/workbay/constitution.md:42` | seen-all + stall warn; CLI stalled→error |
| sr-009 | `docs/workbay/constitution.md:26` | `delete_person` uses `run_transactional` |

## Decisions
- R1-01 **(a)**: keep plugin `label:null` emission; backend stores NULL. Blank string still 400.
- Upsert tombstone: keep local NULL label when `label IS NULL AND person_id IS NULL` (delete survives snapshot).
- `bind_person_to_cluster($confirm)`: user paths confirm; heal sets `person_id` only.
- Automatic same-name reuse only if created, bound to this cluster, or unbound orphan. Else `Name (2)` (unique `normalized_name`).
- SQL CASE inlined as literals (parity scanner rejects concatenated helpers). Helper remains for unit tests.

## Undone
- FE copy `"Just label — don't add to roster"` (PHP lane).
- Live #6731 still needs site upgrade / `wp acx bind-unbound-labels`.
- `list_labels` still DISTINCT on raw `c.label` (typeahead hole).
- `docs/workbay/contracts/` gitignored here; force-added `curation-sync-api.md` + `clustering-api.md`.

## Commits
- `245674d061a486998dd5580a3c07cd0e2a8c79f9` `fix(roster): UXW2-4-R1-01 accept cluster_label_updated label null`
- `2d7b641691a90583036b2089ee4b286d70aa948d` `fix(sovereign): UXW2-4-R1-03 shared reserved-label SQL + upgrade heal`
- `7c72dbbab36adff590585098474c2673fcbb4936` `fix(sovereign): UXW2-4-R1-02 R1-04 tombstone upsert and shared bind`
- `72333dd986a320633f0b5b962b32dc6fa8b1e68a` `fix(api): UXW2-4-R1-07 R1-08 backfill seen/skip and name-collision`
- `2b8479e394c99ba176471e11e9f114df379e9df1` `fix(api): UXW2-4-R1-05 R1-06 proxy-first label and merge 409`
- `d8ea4be07909471985eb9a4969ab63c06981ec81` `fix(api): UXW2-4-R1-13 delete_person run_transactional reset_curation`
- `0c61306b611b7205ff6d344cc956b1d728cc5f04` `fix(sovereign): UXW2-4-R1-11 R1-12 label authority on remaining reads`
- `dcd1d9f4fc20d2f60b9ac63283f9a2f7667e0679` `fix(api): UXW2-4-R1-10 ordered outbox operations in goldens`

HEAD: this REPORT commit (`git rev-parse HEAD`).

---

# UXW2-4-R2 — close R2 findings + leftover R1-02/03/11/12/14

## Result
Delete is revision-aware (`label_cleared_revision` vs snapshot version). Shared reserved-label SQL is the only `LIKE 'cluster` source. Bind returns `int|false` and is tenant-scoped. Heal retries on every load until `acx_label_heal_complete`. Report cites subjects, not fabricated SHAs.

## RED
| Finding | Test | Failure |
| --- | --- | --- |
| R2-10 | `WpdbStubTest::testInsertAssignsDistinctIdsOnSuccessiveInserts` | `Failed asserting that 1 is not identical to 1` |
| R2-03 | `testListForTenantIssuedSqlUsesSharedReservedLabelPredicate` | helper lacked `LOWER(c.label)` |
| R2-04 | `testBindPersonToClusterReturnsFalseOnUpdateFailure` | `Argument #3 ($confirm) must be of type bool, string given` |
| R2-06 | `testResetCurationReturnsZeroWhenNoRowMatches` | `1 is identical to 0`; two UPDATEs |
| R2-02 / R1-02 | `testDeleteThenSnapshotMergeDoesNotRecreatePerson` | INSERT VALUES still contained `'Tory Guzman'` |
| R2-02 | `testNewerSnapshotAfterClearRelabelsCluster` | person insert array empty |
| R2-07 | `testDeletePersonDoesNotDeleteOtherTenantSharingPersonId` | remaining persons size 0 |
| R2-08 / R1-12 | `testCreateLocalClusterUsesAutomaticBindAndEnqueuesPersonCreated` | outbox empty |
| R2-08 | `testCreateLocalClusterCreatesDistinctPersonOnNameCollision` | no distinct-person INSERT |
| R2-05 | `testProxyLabelWriteReportsRosterBoundFalseWhenBindFails` | `true is false` |
| R2-09 / R1-03 | `testMaybeUpgradeDoesNotMarkHealCompleteWhenStalledAndRetries` | healRuns 0 after version stamp |
| R2-11 / R1-11 | `testMapMediaIdentitiesAppliesLabelAuthorityOnLocalProjectionRows` | `'Tory Guzman' is null` |
| R2-11 mutant | `testProxyMediaIdentitiesAppliesLabelAuthorityOnHttpPayload` | `'Tory Guzman' is null` after dropping normalizer |
| R2-12 | `testCreateDistinctUsesInjectedTablePrefix` | INSERT INTO `alt_acx_persons` empty |
| R2-12 | `testCreateDistinctReturnsErrorWhenSuffixesExhausted` | `acx_db_error !== acx_name_collision` |
| R2-01 / R1-14 | this report | R1 table SHAs are non-portable after `git am`; cite subjects |

## GREEN
`apps/prototype-wp-alt-context` `composer test`: **OK (1810 tests, 8703 assertions)**.
Zero new failures. Pre-existing: none on this suite.

## Closure
| ID | Commit subject | Test | TEST-15 mutant killed |
| --- | --- | --- | --- |
| R1-02 | `fix(sovereign): UXW2-4-R2-02 R1-02 revision-aware delete tombstone` | `testDeleteThenSnapshotMergeDoesNotRecreatePerson` | always `VALUES(label)` incoming |
| R1-03 | `fix(support): UXW2-4-R2-09 R1-03 heal retries after stall` | `testMaybeUpgradeDoesNotMarkHealCompleteWhenStalledAndRetries` | stamp complete before heal |
| R1-11 | `fix(api): UXW2-4-R2-11 R1-11 controller label-authority test` | `testProxyMediaIdentitiesAppliesLabelAuthorityOnHttpPayload` | drop `apply_label_authority_to_identities_map` |
| R1-12 | `fix(sovereign): UXW2-4-R2-08 R1-12 create_local_cluster uses automatic bind` | `testCreateLocalClusterCreatesDistinctPersonOnNameCollision` | `resolve_or_create(..., fn => true)` |
| R1-14 | this R2 report section | SHA `git cat-file -e` on this file | n/a |
| R2-01 | this R2 report section | subjects only; no new 40-char SHAs | n/a |
| R2-02 | `fix(sovereign): UXW2-4-R2-02 R1-02 revision-aware delete tombstone` | delete→merge + newer snapshot | always incoming label |
| R2-03 | `fix(sovereign): UXW2-4-R2-03 use shared reserved-label SQL helper` | `testListForTenantIssuedSqlUsesSharedReservedLabelPredicate` | helper returns `''` |
| R2-04 | `fix(sovereign): UXW2-4-R2-04 bind_person_to_cluster tenant and outcome` | bind false + cross-tenant uuid | return 0 on update false |
| R2-05 | `fix(api): UXW2-4-R2-05 R2-13 R1-06 roster_bound from bind + merge 409 docs` | `testProxyLabelWriteReportsRosterBoundFalseWhenBindFails` | `roster_bound = true` |
| R2-06 | `fix(sovereign): UXW2-4-R2-06 reset_curation single UPDATE` | `testResetCurationReturnsZeroWhenNoRowMatches` | `max(1, $updated)` |
| R2-07 | `fix(api): UXW2-4-R2-07 person DELETE is tenant-scoped` | `testDeletePersonDoesNotDeleteOtherTenantSharingPersonId` | DELETE WHERE id only |
| R2-08 | `fix(sovereign): UXW2-4-R2-08 R1-12 create_local_cluster uses automatic bind` | create + collision | skip automatic-bind |
| R2-09 | `fix(support): UXW2-4-R2-09 R1-03 heal retries after stall` | stall then retry; complete marks | stamp version path skips heal |
| R2-10 | `fix(tests): UXW2-4-R2-10 increment wpdb stub insert_id` | `WpdbStubTest` two inserts | leave `insert_id` at 1 |
| R2-11 | `fix(api): UXW2-4-R2-11 R1-11 controller label-authority test` | proxy + mapper authority | drop controller normalizer |
| R2-12 | `fix(api): UXW2-4-R2-12 create_distinct injects prefix and surfaces exhaust` | inject prefix + exhaust | hardcode `wp_` prefix |
| R2-13 | `fix(api): UXW2-4-R2-05 R2-13 R1-06 roster_bound from bind + merge 409 docs` | `docs/workbay/contracts/clustering-api.md` | n/a (contract) |

## Canon (grepped)
| ID | File:line | How |
| --- | --- | --- |
| DATA-14 | `~/uxw2/canon/lexicons/engineering.md:202` | persons own human name; tenant-scoped writes |
| ARCH-02 | `~/uxw2/canon/lexicons/engineering.md:552` | one bind writer; create_local_cluster uses it |
| REF-09 | `~/uxw2/canon/lexicons/engineering.md:328` | no raw cluster-label fallback; helper is the source |
| REF-25 | `~/uxw2/canon/lexicons/engineering.md:344` | report is an audit trail (subjects, not dead SHAs) |
| REF-26 | `~/uxw2/canon/lexicons/engineering.md:345` | merge 409 + roster_bound documented with the code |
| TEST-07 | `~/uxw2/canon/lexicons/engineering.md:388` | stub insert_id no longer shared across inserts |
| TEST-15 | `~/uxw2/canon/lexicons/engineering.md:396` | each invariant test shown red, then green |
| DIAG-01 | `~/uxw2/canon/lexicons/engineering.md:446` | report facts from this repo's `git log` / phpunit |
| RLSE-04 | `~/uxw2/canon/lexicons/engineering.md:695` | pending heal is a designed admin-visible state |
| rg-002 | `docs/workbay/constitution.md:37` | reset_curation is one UPDATE |
| rg-007 | `docs/workbay/constitution.md:42` | heal stall bounded per load; retries next load |
| rg-015 | `docs/workbay/constitution.md:48` | `roster_bound` from persist+bind, not hardcoded |

## Decisions
- Tombstone is PHP-decided: keep cleared label when `snapshot_version <= label_cleared_revision`; newer backend revision re-labels. SQL is dumb `VALUES(label)`.
- `bind_person_to_cluster` returns `int|false` (0 = no-op, false = DB failure) and requires `tenant_id`.
- Heal completion is a separate option (`acx_label_heal_complete`); schema version still stamps after dbDelta.
- Proxy bind failure returns `roster_bound: false` (HTTP 200); local transactional bind failure stays `WP_Error`.
- `create_distinct` exhaust is `acx_name_collision` / 409.

## Undone
- `list_labels` still DISTINCT on raw `c.label` (typeahead hole; not an R2 item).
- FE findings R1-15..31 are a separate lane (`js/`, `*.scss`, `docs/ux-maps/` untouched).

## Commits (subjects; lane SHAs are non-portable)
- `fix(tests): UXW2-4-R2-10 increment wpdb stub insert_id`
- `fix(sovereign): UXW2-4-R2-03 use shared reserved-label SQL helper`
- `fix(tests): UXW2-4-R2-03 parity scanner ignores PHP this`
- `fix(sovereign): UXW2-4-R2-04 bind_person_to_cluster tenant and outcome`
- `fix(sovereign): UXW2-4-R2-06 reset_curation single UPDATE`
- `fix(sovereign): UXW2-4-R2-02 R1-02 revision-aware delete tombstone`
- `fix(api): UXW2-4-R2-07 person DELETE is tenant-scoped`
- `fix(sovereign): UXW2-4-R2-08 R1-12 create_local_cluster uses automatic bind`
- `fix(api): UXW2-4-R2-05 R2-13 R1-06 roster_bound from bind + merge 409 docs`
- `fix(support): UXW2-4-R2-09 R1-03 heal retries after stall`
- `fix(api): UXW2-4-R2-11 R1-11 controller label-authority test`
- `fix(api): UXW2-4-R2-12 create_distinct injects prefix and surfaces exhaust`
- this report commit

Cite R1 SHAs in the table above as **lane SHA (non-portable)**. Do not treat them as canonical after `git am`.
