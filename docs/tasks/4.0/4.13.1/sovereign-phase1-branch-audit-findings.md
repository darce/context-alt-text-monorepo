# Branch Audit — `task/4.13.1-package-for-web-delivery` (Sovereign Phase 1)

> **Date:** 2026-02-10
> **Commit:** `db9e072` (HEAD)
> **Scope:** 68 files changed, +7354 / −534 lines vs `main`
> **Review Focus:** Sovereign Phase 1 local projection implementation compliance with [wp-sovereign-phase1-local-projection-task-plan.md](wp-sovereign-phase1-local-projection-task-plan.md)
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity   | Count  |
| ---------- | ------ |
| **HIGH**   | 1      |
| **MEDIUM** | 5      |
| **LOW**    | 4      |
| **Total**  | **10** |

## Remediation Verification (2026-02-11)

| Finding                            | Fix Verification                                                                                                                                                                                                 |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| H-1 Similarity NULL sentinel       | `normalize_similarity_value()` now returns `''` instead of `'NULL'`; `NULLIF('', '')` correctly yields SQL `NULL`. Test confirms `NULLIF('NULL', '')` absent.                                                    |
| M-1 Confirmed-cluster member skip  | `AND c.is_user_confirmed = 0` removed from `WHERE EXISTS` subquery. Test explicitly asserts it is absent from INSERT SQL.                                                                                        |
| M-2 FIND_IN_SET UUID injection     | Both repos switched to `NOT IN ($placeholders)` with individual `%s` per ID. `sanitize_uuid_list()` validates IDs via `/^[A-Za-z0-9-]+$/`. Tests assert `FIND_IN_SET` is absent.                                 |
| M-3 Duplicated `prepare_query`     | Extracted to `trait-prepares-sql-queries.php`; all three repositories now `use PreparesSqlQueries` and local copies were removed.                                                                                |
| M-4 Orphaned member cleanup        | `delete_orphan_rows()` added with `LEFT JOIN ... WHERE c.cluster_uuid IS NULL`, invoked in `merge_snapshot_for_tenant()`. Test verifies SQL pattern.                                                             |
| M-5 Contract gaps                  | `cluster-snapshot-api.md` now includes `Accept`/`Content-Type`, timeout expectations, retry/backoff semantics, rate-limit contract, and pagination contract sections.                                            |
| L-1 Missing `use function implode` | Added explicit imports in both repositories (alongside `array_fill`, `array_merge`, `array_unique`).                                                                                                             |
| L-2 Silent `tenant_id` guard       | Repositories now call `$this->log_empty_tenant_id_guard(__METHOD__)` via shared trait. Projector has dedicated warning dispatch (`acx_sovereign_warning`) + `_doing_it_wrong()`. Test verifies warning dispatch. |
| L-3 `WPDBStub` `has_cap`           | Added `has_cap(string $cap): bool` returning true for `identifier_placeholders`, so tests exercise native `%i` path.                                                                                             |
| L-4 Integration test depth         | Test renamed to `testFixtureSnapshotProjectionWritesExpectedReadModelRowPayloads` and now asserts concrete cluster/member/sync INSERT payload values.                                                            |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result                                             |
| --------------------------------------- | -------------------------------------------------- |
| `make check` (ruff + mypy + pytest)     | N/A — no Python files in diff                      |
| `composer test` (PHPUnit)               | :white_check_mark: 108 tests, 352 assertions       |
| `composer cs-check` (PHPCS)             | :white_check_mark:                                 |
| `npm run typecheck`                     | :white_check_mark:                                 |
| `npm run test -- --run`                 | :white_check_mark: 30 files, 153 tests             |
| `npm run lint` (ESLint)                 | :white_check_mark:                                 |
| `check-architecture-compliance.js`      | :white_check_mark: (0 violations, 98 files)        |
| `composer phpstan`                      | N/A — not configured (no PHPStan in `require-dev`) |
| Cyclomatic complexity (radon, grade C+) | N/A — no Python files in diff                      |

---

## HIGH Severity

### H-1 · `similarity` column stores string `'NULL'` instead of SQL `NULL`

|              |                                                                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L206-L211) |
| **Category** | ANTIPATTERN                                                                                                                                             |

`normalize_similarity_value()` returns the literal string `'NULL'` when no similarity is present. This value is bound via `%s` in `$wpdb->prepare()`, producing the quoted string `'NULL'` in SQL. The `NULLIF(%s, '')` wrapper (line 100) checks against empty string, not the sentinel `'NULL'`, so the expression evaluates to the **string** `'NULL'` instead of SQL `NULL`.

The `similarity` column is declared as `double NULL` in the schema. MySQL in strict mode will error; in non-strict mode it silently stores `0`. Neither outcome matches the intent (store database `NULL` when similarity is unavailable).

**Fix:** Change `normalize_similarity_value()` to return `''` (empty string) instead of `'NULL'`, so `NULLIF(%s, '')` correctly produces SQL `NULL`. Alternatively, conditionally construct the SQL fragment with a literal `NULL` keyword when similarity is absent.

---

## MEDIUM Severity

### M-1 · `WHERE EXISTS` guard prevents member insertion for confirmed clusters

|              |                                                                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L103-L112) |
| **Category** | GAP                                                                                                                                                     |

The `INSERT INTO ... SELECT ... FROM DUAL WHERE EXISTS (...)` guard on member upserts includes `c.is_user_confirmed = 0`. This means member rows for user-confirmed clusters are **silently not inserted or updated**.

The task plan's curation-first policy (Pattern B) protects cluster-level fields (`label`, `curation_state`, `is_user_confirmed`) from overwrite, and the stale-row deletion correctly excludes confirmed clusters. However, skipping member inserts entirely prevents new identity data (new face detections, updated bboxes) from being projected for confirmed clusters.

The contract doc says non-authoritative fields on clusters (`identity_count`, `representative_thumb_path`, `snapshot_version`, `last_synced_at`) may refresh — the same principle should extend to member rows, which are raw identity data without curation semantics.

**Impact:** A confirmed cluster will never receive new members until it is un-confirmed, creating a stale read model for confirmed clusters.

### M-2 · `FIND_IN_SET` with unsanitized UUIDs allows logic corruption

|              |                                                                                                                                                                                                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Files**    | [class-clusters-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php#L206-L214), [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L196-L207) |
| **Category** | ANTIPATTERN                                                                                                                                                                                                                                                                                      |

Both stale-row deletion methods use `FIND_IN_SET(cluster_uuid, %s)` where the set is built via `implode(',', $incoming_ids)`. UUIDs from the snapshot payload are only `trim()`ed, not validated against a UUID format pattern.

A UUID containing a comma (e.g., `"abc,target-uuid"`) would cause `FIND_IN_SET` to match `target-uuid` as a separate set member, **preventing deletion of rows that should be stale**. While `$wpdb->prepare()` prevents SQL injection (the entire imploded string is a single quoted parameter), the data integrity risk remains.

**Fix:** Either validate UUID format with a regex (`/^[0-9a-f-]+$/i`) before including in the set, or switch from `FIND_IN_SET` to a `NOT IN (...)` clause with individual `%s` placeholders per ID.

### M-3 · `prepare_query` + `escape_identifier` duplicated across three repositories

|              |                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-clusters-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php#L318-L353), [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L320-L355), [class-sync-state-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php#L93-L130) |
| **Category** | COMPLEXITY                                                                                                                                                                                                                                                                                                                                                                                                                                   |

Character-for-character identical `prepare_query()` (~30 lines) and `escape_identifier()` (~5 lines) methods are copy-pasted across all three repository classes. This is ~105 total lines of duplicated code.

The branch review guide §3.4 states: "Shared repository utilities — UUID coercion, media-identity bootstrap, etc. live in `_helpers.py`, not copy-pasted." The PHP equivalent would be a trait (e.g., `PreparesSqlQueries`) or a shared abstract base.

**Fix:** Extract into a `trait PreparesSqlQueries` in `src/sovereign/repositories/` and `use` it from each repository.

### M-4 · Orphaned member rows are never cleaned up

|              |                                                                                                                                                         |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L157-L197) |
| **Category** | GAP                                                                                                                                                     |

`delete_stale_non_curated_rows()` uses an `INNER JOIN` against `wp_acx_clusters` for tenant scoping. Member rows whose `cluster_uuid` references no cluster (deleted or never existed) are invisible to this join and will never be cleaned up. Over time, after backend cluster restructuring, orphan member rows accumulate unbounded.

**Fix:** Add a periodic orphan cleanup mechanism:

```sql
DELETE m FROM wp_acx_identity_members m
LEFT JOIN wp_acx_clusters c ON c.cluster_uuid = m.cluster_uuid
WHERE c.cluster_uuid IS NULL
```

Phase 2 note: current implementation runs orphan cleanup on every `merge_snapshot_for_tenant()` invocation. This is acceptable for v0.1.0 scale; if profiling shows large-table overhead, move to cadence-gated or background cleanup in roadmap Phase 2.

### M-5 · Contract doc missing pagination, retry, and rate-limit semantics

|              |                                                                                 |
| ------------ | ------------------------------------------------------------------------------- |
| **Files**    | [cluster-snapshot-api.md](../../../agentic/contracts/cluster-snapshot-api.md) |
| **Category** | GAP                                                                             |

The snapshot contract is `draft` status. It documents error HTTP statuses (4xx/5xx) and a one-line retry note, but is missing:

- **Retry semantics:** No backoff strategy, no `Retry-After` header contract, no max retry count, no transient vs. permanent failure distinction.
- **Rate limiting:** No `429` status, no `X-RateLimit-*` header contract.
- **Pagination:** Full cluster + member payload in a single response with no cursor or chunked delivery — scalability gap for large tenants.
- **Content-Type:** Implied JSON but not explicitly required.
- **Request timeout:** No expectation documented.

Acceptable for v0.1.0 draft but should be tracked for the contract evolution before the backend route is implemented.

---

## LOW Severity

### L-1 · Missing `use function implode` declaration

|              |                                                                                                                                                                                                                                                                                        |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-clusters-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php#L213), [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L205) |
| **Category** | ANTIPATTERN                                                                                                                                                                                                                                                                            |

Both files declare explicit `use function` imports for all other PHP builtins (`array_map`, `array_filter`, `trim`, `sprintf`, etc.) but omit `use function implode;`. Works at runtime via namespace fallback but is inconsistent with the file's own style convention.

### L-2 · Silent early return on empty `tenant_id` without logging

|              |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [class-snapshot-projector.php](../../../../apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php#L42-L44), [class-clusters-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php#L49-L51), [class-identity-members-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php#L51-L53), [class-sync-state-repository.php](../../../../apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php#L37-L39) |
| **Category** | ANTIPATTERN                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |

All sovereign classes silently return/no-op when `tenant_id` is empty. Per the branch review guide §3.5 spirit: masked failures should at minimum produce a log warning. An empty `tenant_id` reaching the projector indicates a configuration or integration bug in the caller.

### L-3 · `WPDBStub` missing `has_cap` method

|              |                                                                                    |
| ------------ | ---------------------------------------------------------------------------------- |
| **Files**    | [tests/stubs/wp.php](../../../../apps/prototype-wp-alt-context/tests/stubs/wp.php#L1422) |
| **Category** | GAP                                                                                |

The `prepare_query` polyfill in all three repositories calls `method_exists($wpdb, 'has_cap')` to detect `%i` identifier placeholder support. The `WPDBStub` does not implement `has_cap()`, causing the polyfill fallback path to always execute in tests. This means tests never exercise the native `%i` path, reducing coverage of the mainline code path in modern WordPress (6.2+).

Adding `public function has_cap(string $cap): bool { return $cap === 'identifier_placeholders'; }` to `WPDBStub` would exercise the native path.

### L-4 · Integration test verifies SQL strings but not actual data assertion

|              |                                                                                                                                 |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| **Files**    | [SovereignProjectionIntegrationTest.php](../../../../apps/prototype-wp-alt-context/tests/Unit/SovereignProjectionIntegrationTest.php) |
| **Category** | GAP                                                                                                                             |

The "integration" test (`testFixtureSnapshotProjectionWritesAllLocalReadModelTables`) asserts only that SQL strings contain certain keywords (`INSERT INTO`, `COMMIT`). It does not verify actual data in the projected tables because the test uses a `WPDBStub` that doesn't simulate a real database.

This is naming misaligment: it's labeled as an integration test but functions as a SQL-generation verification test. The task plan Phase 4 calls for "plugin integration test that ingests fixture snapshot and verifies local read-model rows" — achieving true read-model verification requires either a real database or a more sophisticated stub that tracks inserted rows.

---

## Task Plan Compliance Matrix

| Checklist Item                      | Status                      | Notes                                                                            |
| ----------------------------------- | --------------------------- | -------------------------------------------------------------------------------- |
| **Phase 0: Scaffolding**            | :white_check_mark: Complete | Interfaces, class shells, test stubs, contract doc all present                   |
| **Phase 1: Schema Foundation**      | :white_check_mark: Complete | `dbDelta` creates all 3 tables with roadmap-accurate columns and indexes         |
| **Phase 2: Local Repository Layer** | :warning: Mostly complete   | H-1 (similarity NULL), M-1 (confirmed-cluster member skip), M-2 (FIND_IN_SET)    |
| **Phase 3: Snapshot Projector**     | :white_check_mark: Complete | Transaction boundary, curation-safe merge, fixture-based tests                   |
| **Phase 4: Integration Readiness**  | :warning: Partial           | Integration test is SQL-string-only (L-4); smoke procedure documented in runbook |
| **Snapshot Contract Doc**           | :warning: Draft with gaps   | M-5 (missing retry/pagination/rate-limit)                                        |
| **Lifecycle Symmetry**              | :white_check_mark: Complete | Create/drop symmetric, idempotent activation, uninstall cleanup tested           |
| **Endpoint Resolution**             | :white_check_mark: Complete | `SnapshotClient` uses filterable path, no hardcoded backend URL                  |

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-1** — Fix similarity NULL sentinel to use empty string instead of `'NULL'` literal

### Phase 2 — Robustness (soon after merge)

2. **M-1** — Re-evaluate `WHERE EXISTS ... is_user_confirmed = 0` guard on member inserts
3. **M-2** — Validate UUID format or switch from `FIND_IN_SET` to `NOT IN` with individual placeholders
4. **M-3** — Extract `prepare_query`/`escape_identifier` into shared trait

### Phase 3 — Maintainability (tech debt backlog)

5. **M-4** — Add orphan member cleanup mechanism
6. **M-5** — Flesh out snapshot contract with retry, pagination, and rate-limiting semantics
7. **L-1** — Add missing `use function implode` declarations
8. **L-2** — Add logging for empty `tenant_id` guard clauses
9. **L-3** — Add `has_cap` to `WPDBStub` for full path coverage
10. **L-4** — Upgrade integration test to verify actual row data (requires richer stub or real DB)

---

## Consolidated Checklist

### Phase 1 — Correctness (before merge)

- [x] **H-1** — Change `normalize_similarity_value()` return from `'NULL'` to `''` so `NULLIF(%s, '')` yields SQL `NULL`

### Phase 2 — Robustness

- [x] **M-1** — Remove `is_user_confirmed = 0` from `WHERE EXISTS` in member insert (allow member refresh for confirmed clusters)
- [x] **M-2** — Add UUID format validation or replace `FIND_IN_SET` with parameterized `NOT IN` clause
- [x] **M-3** — Extract `prepare_query`/`escape_identifier` into `trait PreparesSqlQueries`

### Phase 3 — Maintainability

- [x] **M-4** — Add orphan member cleanup (LEFT JOIN delete for member rows with no matching cluster)
- [x] **M-5** — Expand snapshot contract with retry/backoff, pagination, rate-limit, and content-type sections
- [x] **L-1** — Add `use function implode;` to clusters and identity-members repositories
- [x] **L-2** — Log warning on empty `tenant_id` in projector and repository guard clauses
- [x] **L-3** — Add `has_cap()` method to `WPDBStub` test stub
- [x] **L-4** — Enhance integration test with row-level data verification

## Success Criteria

- [x] Zero HIGH findings remaining
- [x] `composer test` passes
- [x] `npm run typecheck` passes with zero new errors
- [x] All existing tests continue to pass
- [x] Branch audit re-run shows no regressions
