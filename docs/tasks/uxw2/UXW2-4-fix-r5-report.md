# UXW2-4-R5 — roster_bound fail-closed + label-authority contract parity

## Result

Proxy label and proxy merge bind failures now return HTTP `500` `acx_db_error` before `roster_bound` is written. No-row-matched stays `200` with `roster_bound: false`. Local merge `roster_bound` is asserted on both outcomes. Contracts match `/^cluster[-_]/i` and the label-value tombstone.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Found as read

**R5-01.** Local label (`class-cluster-label-service.php:197`) already failed closed on `false === $bound`. Proxy label collapsed DB failure through `bind_persisted_person()` → `bind_succeeded()` into `roster_bound: false` on HTTP 200. Proxy merge did the same at `bind_succeeded($bind_result)` with no `false` check.

**R5-04.** Both merge `roster_bound` value asserts (`assertTrue` / `assertFalse`) were on the HTTP-proxy path. Local merge derived the flag but no test read it.

**R5-02 / R5-03.** `clustering-api.md` and `cluster-snapshot-api.md` still said auto labels were `cluster-%`. Shipped detector is `is_reserved_label_shape()` (`trait-detects-system-defined-labels.php:12-15`): unicode-whitespace trim then `/^cluster[-_]/i`. `roster_bound` prose said "bind failed ⇒ false"; code treats no-row as `false` and DB failure as `acx_db_error`. Snapshot tombstone (`label_cleared_label` / `label_cleared_revision`) was undocumented.

## RED (before each fix)

| Item | Test | Failure |
| --- | --- | --- |
| 1 | `testProxyLabelWriteSurfacesBindDatabaseFailureAsServerError` | `Failed asserting that an object is an instance of class WP_Error.` |
| 1 | `testProxyMergeWriteSurfacesBindDatabaseFailureAsServerError` | `Failed asserting that an object is an instance of class WP_Error.` |
| 1 | `testProxyLabelWriteReportsRosterBoundFalseWhenNoClusterRowMatched` | already GREEN (characterization: 0-row must stay 200) |
| 2 | `testLocalMergeReportsRosterBoundFalseWhenBindMatchesNoRow` / `testLocalMergeReportsRosterBoundTrueWhenBindMatches` | already GREEN (local path already derived the flag). Kill is the mutant below. |

Filter confirmed `3 / 3` on the item-1 trio, `1 / 1` on each mutant, `2 / 2` on the local pair.

## TEST-15

| Item | Mutant | Result |
| --- | --- | --- |
| 1 merge | drop `if ( false === $bind_result )` on the proxy merge path | `Failed asserting that an object is an instance of class WP_Error.` (`testProxyMergeWriteSurfacesBindDatabaseFailureAsServerError`, 1 / 1) |
| 1 merge restore | check restored | `git diff` clean on `class-cluster-merge-service.php` |
| 1 label | drop `if ( false === $bound )` inside `bind_persisted_person` | `Failed asserting that an object is an instance of class WP_Error.` (`testProxyLabelWriteSurfacesBindDatabaseFailureAsServerError`, 1 / 1) |
| 1 label restore | check restored | `git diff` clean on `class-cluster-label-service.php` except the intended fail-closed body |
| 2 | `$response_data['roster_bound'] = true;` on the local merge path | `Failed asserting that true is false.` (`testLocalMergeReportsRosterBoundFalseWhenBindMatchesNoRow`, 1 / 1) |
| 2 restore | `$roster_bound` restored | `git diff` clean on `class-cluster-merge-service.php` |

## GREEN

`cd apps/prototype-wp-alt-context && composer test`:

```
OK (1833 tests, 8799 assertions)
```

R4 baseline on this tree was `OK (1829 tests, 8780 assertions)`. +4 tests, +19 assertions. Suite did not shrink.

Item 1 after implement: `OK (3 tests, 13 assertions)`.
Item 2 after tests: `OK (2 tests, 8 assertions)`.

## Files

- `apps/prototype-wp-alt-context/src/api/services/class-cluster-label-service.php`
- `apps/prototype-wp-alt-context/src/api/services/class-cluster-merge-service.php`
- `apps/prototype-wp-alt-context/tests/Unit/ClusterLabelServiceTest.php`
- `apps/prototype-wp-alt-context/tests/Unit/ClusterMergeServiceTest.php`
- `docs/workbay/contracts/clustering-api.md` (tracked; force-added — this mirror also lists the directory in `.gitignore`)
- `docs/workbay/contracts/cluster-snapshot-api.md`
- this file

`bind_succeeded()` was not widened. `class-cluster-curation-writer.php` was not edited.

## file:line (re-derived after last code commit)

| Claim | `sed -n` |
| --- | --- |
| Proxy label returns `WP_Error` before `roster_bound` | `class-cluster-label-service.php:104-108` `$bound = bind_persisted_person(...)`; `is_wp_error` → return; only then `$data['roster_bound'] = $bound` |
| Proxy label missing-`$wpdb` / bind `false` | `class-cluster-label-service.php:250-257` both return `WP_Error('acx_db_error', …, ['status' => 500])` |
| Local label still fail-closed | `class-cluster-label-service.php:197` `if ( false === $bound )` |
| Proxy merge fail-closed | `class-cluster-merge-service.php:126-129` `if ( false === $bind_result )` then `bind_succeeded` |
| Local merge flag from bind | `class-cluster-merge-service.php:193` `$response_data['roster_bound'] = $roster_bound` |
| `bind_succeeded` unchanged | `class-cluster-curation-writer.php:254-255` `false !== $bound && 0 !== $bound` |
| Reserved shape | `trait-detects-system-defined-labels.php:12-14` `/^cluster[-_]/i` after unicode-whitespace trim; SQL `:28` `cluster-%%` / `cluster\_%%` |
| Tombstone decide | `class-cluster-snapshot-merger.php:110-117` `$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label`; `:121` "Tombstone is decided in PHP (cleared-label match)" |
| Tombstone write | `class-cluster-curation-writer.php:347` `label_cleared_label = label, label = NULL, person_id = NULL, … label_cleared_revision = snapshot_version` |
| Contract reserved + roster_bound | `clustering-api.md:445`, `:497-502`, `:523` |
| Contract reserved + tombstone | `cluster-snapshot-api.md:100-101` |

## Canon (grepped) with `file:line`

| ID | Where | How |
| --- | --- | --- |
| RLSE-05 | `~/uxw2/canon/lexicons/engineering.md:696` | proxy bind `false` is 500, not a silent `roster_bound: false` |
| TEST-06 | `engineering.md:387` | item-1 500 tests watched RED first |
| TEST-15 | `engineering.md:396` | merge / label `false ===` drop; local `roster_bound = true` |
| REF-26 | `engineering.md:345` | reserved shape + roster_bound + tombstone in contracts with the code |
| rg-015 | `docs/workbay/constitution.md:48` | `roster_bound` from bind outcome; 500 has no fabricated flag |
| DATA-14 | `engineering.md:202` | tombstone columns are the cleared-label authority |
| FLOW-06 | `engineering.md:268` | snapshot cannot resurrect a user-cleared label |
| HAI-02 | `~/uxw2/canon/lexicons/interaction-ux.md:211` | correction (clear) reaches the source so recompute cannot restore it |
| REF-09 | `engineering.md:328` | `roster_bound` is derived, not hardcoded |

## Decisions

1. **`bind_persisted_person` returns `bool\|WP_Error`.** `bool` cannot express DB failure vs no-row. Missing `$wpdb` and `false === $bound` raise `acx_db_error` 500. Caller writes `roster_bound` only after `is_wp_error` is clear. `bind_succeeded()` stays a boolean helper.
2. **Proxy merge checks `false === $bind_result` before `set_data`.** Same message and status as the local label path. 0-row still becomes `roster_bound: false` on 200.
3. **Fail-closed 500 is documented as holding on every path that sets `roster_bound`** because item 1 landed first. Contracts describe the tree as left, not the pre-fix proxy hole.
4. **Tombstone prose is label-value, not revision-ordered.** Derived from `$keep_cleared` at `class-cluster-snapshot-merger.php:114`, not from `snapshot_version`.

## Undone

- `clustering-api.md:527` still says the merge 200 is a `ClusterResponse`. Local merge body is the six-key object from r3 (`source_cluster_id`, `target_cluster_id`, `moved_identity_count`, `synced`, `status`, `roster_bound`). Not rewritten here.
- Missing `$wpdb` on the merge proxy path is only covered because `bind_person_to_cluster` returns `false`. The writer is still constructed with `$wpdb->prefix` first. No dedicated missing-`$wpdb` test.
- `bind_persisted_person` missing-`$wpdb` 500 is implemented and untested as its own case; the required tests drive `update()` returning `false`.
- FE / ux-map surfaces are another lane.

## Commits (subjects)

- `fix(api): UXW2-4-R5-01 fail-closed roster_bound on proxy bind error`
- `test(api): UXW2-4-R5-04 assert local merge roster_bound from bind`
- `docs(contracts): UXW2-4-R5-02 R5-03 reserved label shape and tombstone`
- this report commit
