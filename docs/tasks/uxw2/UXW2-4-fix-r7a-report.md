# UXW2-4-R7a — PHP service + contracts + parity scanner

## Result

`create_distinct` returns `acx_db_error` when `$wpdb` is missing and `acx_name_collision` when suffixes 2–99 are taken. Parity now expands `DetectsSystemDefinedLabels` SQL and fails by column name. Contracts match `bind_succeeded()` / `/^cluster[-_]/i` / the label-value tombstone; `acx_db_error` 500 is scoped to the local path.

Final HEAD: recorded by the integrator in the canonical worktree after transplant.

## Gate

`cd apps/prototype-wp-alt-context && composer test`:

```
OK (1836 tests, 8892 assertions)
```

R6 baseline on this tree was `OK (1834 tests, 8814 assertions)`. +2 tests, +78 assertions.

`npx vitest run` skipped — FE untouched. See `## Undone`.

Targeted filters (selected/total so a zero-selected run cannot read as green):

| Filter | Result |
| --- | --- |
| `testCreateDistinctReturnsErrorWhenWpdbUnavailable` | **1 / 1** `OK (1 test, 2 assertions)` |
| `testCreateDistinctReturnsErrorWhenSuffixesExhausted` | **1 / 1** `OK (1 test, 2 assertions)` |
| `testExpandedTraitLabelSqlFragmentsReferenceDeclaredColumns` | **1 / 1** `OK (1 test, 76 assertions)` |
| `ProjectionQueryColumnParityTest` | **10 / 10** `OK (10 tests, 225 assertions)` |

## Closure

| ID | Commit subject | Test | Mutant RED (verbatim) | GREEN |
| --- | --- | --- | --- | --- |
| UXW2-4-R2-12 (a) | `fix(php): UXW2-4-R2-12 guard wpdb and exhaust create_distinct` | `testCreateDistinctReturnsErrorWhenWpdbUnavailable` | `create_distinct must return WP_Error when wpdb is unavailable, not throw: Error: Call to a member function get_row() on null` (`FAILURES! Tests: 1, Assertions: 1, Failures: 1, Warnings: 1.` **1 / 1**) | `OK (1 test, 2 assertions)` |
| UXW2-4-R2-12 (b) | same | `testCreateDistinctReturnsErrorWhenSuffixesExhausted` | `create_distinct must return WP_Error on suffix exhaustion, not throw: TypeError: AltContext\Api\Services\PersonResolutionService::create_distinct(): Return value must be of type WP_Error\|array, none returned` (`FAILURES! Tests: 1, Assertions: 1, Failures: 1.` **1 / 1**) | `OK (1 test, 2 assertions)` |
| UXW2-4-R3-04 | `test(php): UXW2-4-R3-04 scan expanded trait label SQL` | `testExpandedTraitLabelSqlFragmentsReferenceDeclaredColumns` | `Expanded trait label SQL references columns absent from projection DDL. Missing: trait-detects-system-defined-labels.php: clusters.bogus_col_xyz not in declared columns [cluster_uuid, tenant_id, label, curation_state, person_id, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, local_revision, label_cleared_revision, label_cleared_label, created_at, updated_at, last_synced_at, suggested_label, suggested_label_source, suggested_label_confidence, suggested_target_cluster_id]` (`FAILURES! Tests: 1, Assertions: 76, Failures: 1.` **1 / 1**) | `OK (1 test, 76 assertions)` |
| UXW2-4-R5-02 | `docs(contracts): UXW2-4-R5-02 roster_bound local-path truth` | n/a (doc) | n/a | source `file:line` below |
| UXW2-4-R5-03 | `docs(contracts): UXW2-4-R5-03 reserved shape and label tombstone` | n/a (doc) | n/a | source `file:line` below |

R2-12 mutant A is a **failure**, not a PHPUnit error: the test catches `Throwable` and `$this->fail(...)`. Removing the guard does not abort the suite.

## R3-04 pre-fix GREEN (hole was real)

Mutant `OR bogus_col_xyz IS NULL` inside `reserved_label_sql_predicate`, **before** the expanded-fragment scan:

```
OK (9 tests, 149 assertions)
```

`--filter ProjectionQueryColumnParityTest` → **9 / 9**. Trait-body column was invisible. `$this` exclusion kept (`ProjectionQueryColumnParityTest.php:1889`).

Same mutant after the fix: RED line in the table above, names `bogus_col_xyz`. Trait restored (`git diff` clean on `trait-detects-system-defined-labels.php`).

## file:line (re-derived with `sed -n '<N>p'` after last code commit)

| Claim | `sed -n` |
| --- | --- |
| wpdb guard | `class-person-resolution-service.php:251-256` `isset` / `is_object` / `method_exists` → `WP_Error('acx_db_error', …, ['status' => 500])` |
| suffix bound + named failure | `class-person-resolution-service.php:259` `for ( $suffix = 2; $suffix <= 99; … )`; `:270-277` `acx_name_collision` 409 |
| `bind_succeeded` true | `class-cluster-curation-writer.php:249` `BIND_ALREADY_BOUND = -1`; `:254-255` `false !== $bound && 0 !== $bound` |
| `bind_succeeded` false / DB fail | `:264` `Missing cluster row returns 0. DB failure is false.`; `:277-278` missing `$wpdb` → `false`; `:291-292` no row → `0`; `:323` update `false` |
| local-path 500 | `class-cluster-label-service.php:197-198` `false === $bound` → `acx_db_error` 500; `class-cluster-merge-service.php:388-389` same |
| reserved shape | `trait-detects-system-defined-labels.php:13-14` unicode-whitespace trim then `/^cluster[-_]/i`; SQL `:26-28` `LOWER` + `cluster-%%` / `cluster\_%%` |
| tombstone write | `class-cluster-curation-writer.php:347` `label_cleared_label = label` … `label_cleared_revision = snapshot_version` |
| tombstone keep/release | `class-cluster-snapshot-merger.php:110-117` `$keep_cleared = '' !== $cleared_label && $incoming_label === $cleared_label`; match → `label` null, both tombstone fields rewritten; else both cleared; `:121` "Tombstone is decided in PHP (cleared-label match)" |
| contract roster_bound | `clustering-api.md:497-502`, `:523` |
| contract reserved + tombstone | `cluster-snapshot-api.md:100-101` |

## TEST-15 restores

| Mutant | Restore |
| --- | --- |
| A remove wpdb guard | intended guard remains |
| B silent return after suffix loop | `acx_name_collision` return remains |
| trait `bogus_col_xyz` | `git diff` clean on `trait-detects-system-defined-labels.php` |

## Undone

- FE untouched; `npx vitest run` not run.
- UX maps not in ownership; no user-facing surface in this lane.
- Suffix bound stays 99; exhaustion is a named 409, not a wider loop.
- `persons_table()` still reads `$wpdb->prefix` unguarded; both callers (`resolve_or_create`, `create_distinct`) now guard first. Not a third public path.
- Contract 500 is scoped to the **local** path (R5-01 not claimed fail-closed for every writer). Proxy label/merge in this tree also return `acx_db_error` on `false`; that is outside this lane's contract rewrite.
- `workbay_handoff_mcp` is not importable in this overlay (`make context` has no target). Decision recorded in this report only.
- Sibling files (`js/`, `docs/ux-maps/`, `REPORT.md`, `class-life-cycle-manager.php`, `class-identity-members-read-repository.php`) not touched.

## Commits (subjects)

- `fix(php): UXW2-4-R2-12 guard wpdb and exhaust create_distinct`
- `test(php): UXW2-4-R3-04 scan expanded trait label SQL`
- `docs(contracts): UXW2-4-R5-02 roster_bound local-path truth`
- `docs(contracts): UXW2-4-R5-03 reserved shape and label tombstone`
- this report commit
