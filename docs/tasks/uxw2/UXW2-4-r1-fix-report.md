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
