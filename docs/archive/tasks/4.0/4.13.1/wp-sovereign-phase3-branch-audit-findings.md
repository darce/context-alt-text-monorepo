# Branch Audit — `refactor/4.13.1-wp-sovereign` (Phase 3 Dual-Write Slice)

> **Date:** 2026-02-14
> **Scope:** 20 files changed, ~+550 / −30 lines vs `main`
> **Categories:** ANTIPATTERN · DEAD_CODE · COMPLEXITY · GAP

---

## Summary

| Severity   | Count |
| ---------- | ----- |
| **HIGH**   | 1     |
| **MEDIUM** | 2     |
| **LOW**    | 2     |
| **Total**  | **5** |

---

## Automated Check Results (reported by submitter)

| Check                                   | Result                |
| --------------------------------------- | --------------------- |
| `make check` (ruff + mypy + pytest)     | N/A (no Python in scope) |
| `npm run typecheck`                     | N/A (no TS in scope)  |
| `npm run test -- --run`                 | N/A (no TS in scope)  |
| `npm run lint`                          | N/A (no TS in scope)  |
| `check-architecture-compliance.js`      | N/A (no TS in scope)  |
| `composer phpstan`                      | :white_check_mark: (reported by submitter) |
| `composer test`                         | :white_check_mark: (reported by submitter) |
| Cyclomatic complexity (radon, grade C+) | N/A (no Python in scope) |

---

## Manual Review Checklist

### 3.1 — Correctness

- [x] **Migration ↔ Model parity** — No new migrations in this slice; mutation methods write to columns already created by `LifecycleManager::maybe_create_projection_tables()`.
- [x] **No unreachable code** — All branches reachable. `is_retryable_error()` correctly falls through to default `true`. _(Note: retry/backoff loop and `is_retryable_error()` are being removed — see H-1 resolution.)_
- [x] **No duplicate field declarations** — No duplication.
- [x] **API contract alignment** — Dual-write mutations follow the task plan contract (Pattern A). `SyncPullJob` will be simplified to fail-fast (no retry) per updated task plan.

### 3.2 — Type Safety

**PHP:**

- [x] `SyncPullJob` constructor accepts concrete `SnapshotClient` and `SnapshotProjectorInterface` — no `object` or untyped parameters.
- [x] All new repository methods are typed: `string` params, `void` returns.
- [x] `ClustersRepositoryInterface` mutation methods have docblocks.

### 3.3 — Architecture Boundaries

- [x] **No raw SQL in the application layer** — All SQL is in `ClustersRepository` (infrastructure layer).
- [x] **No presentation DTOs in domain layer** — Mutations operate on primitive types, no response shaping.
- [x] **No default-instantiating settings** — ~~**Finding L-1**: `sync_pull_snapshot()` in `Api` constructs `SyncPullJob` with all dependencies inline.~~ Resolved: `Api::sync_pull_snapshot()` is being deleted entirely as part of H-1 cron removal. `SyncPullJob` will be injected into `ClustersController` via nullable DI instead.
- [x] **No cross-layer exception duplication** — N/A for this slice.
- [x] **No redundant router/dependency wiring** — `ClustersRepository` instantiated once in `RecognitionController` and passed to `ClusterMutationsController`.
- [x] **No time-based gates on curated state** — Curation guard is data-driven (`is_user_confirmed = 1`).

### 3.4 — Code Duplication

- [x] **Shared repository utilities** — Mutation methods reuse `PreparesSqlQueries` trait.
- [ ] **Shared test stubs** — **Finding L-2**: `ClustersRepositoryInterface` is implemented as anonymous classes in 3 locations in `ClustersControllerTest` and as named spies in 2 other test files. Five distinct stubs total for one interface.
- [x] **One canonical fake per protocol** — The two named spies (`SnapshotProjectorClustersSpy`, `ClusterMutationsRepositorySpy`) serve different purposes (read-spy vs mutation-spy). Acceptable.
- [x] **No duplicate methods** — No aliased methods.

### 3.5 — Error Handling

- [x] **No bare exception suppression** — No `catch(Exception)` in new code.
- [x] **Scoped exception clauses** — No try/catch in new code; repository methods guard on `$wpdb` availability.
- [x] **Consistent gate fallbacks** — Empty-string guards in both controller and repository are congruent; repository also `trim()`s.

### 3.6 — Frontend Specific

N/A — no frontend files in this slice.

### 3.7 — PHP / WordPress

- [x] **Superglobal sanitization** — `sanitize_text_field()` applied to all `$request->get_param()` values before use.
- [x] **One transport per parameter** — `cluster_id` comes from route param only.
- [x] **Nonce verification** — Handled by existing route registration (`permission_callback`); not changed in this slice.
- [x] **Capability checks** — Existing `can_manage_recognition()` callback applies; not changed here.

### 3.8 — Tests

- [x] **No permanently skipped tests** — All new tests execute.
- [x] **No empty test bodies** — All assert meaningful state.
- [x] **No false-positive fakes** — `ClusterMutationsRepositorySpy` records calls; `SyncPullJobSnapshotClient` is configurable.
- [x] **Single injection strategy** — Constructor injection used consistently.
- [ ] **Adequate coverage for new components** — Two `SyncPullJob` tests (success + non-retryable error). After H-1 simplification (retry removal), the retry/exhaustion scenarios become moot. Remaining gap: empty `$tenant_id` edge case, non-array return. Deferred to Phase 3 hardening checklist.

### 3.9 — Documentation & Cleanup

- [x] **No stale comments** — No TODOs or "will verify" comments.
- [x] **No duplicate imports** — Clean.
- [x] **Docstrings complete** — Interface methods have docblocks; implementation methods inherit.
- [x] **Function-level imports justified** — All imports at file scope.

### 3.10 — Bug-Finding Heuristics

#### Variable identity after normalization

- [x] `ClustersRepository::update_label()`: `$cluster_uuid` → `$normalized_cluster_uuid`, `$label` → `$normalized_label`. Both guard and SQL binding use normalized variables. Correct.
- [x] `dismiss()` / `undismiss()`: Same pattern. Only `$normalized_cluster_uuid` reaches SQL. Correct.
- [x] `ClusterMutationsController` methods: `$cluster_id` comes from `sanitize_text_field()` and is passed directly to both repository and proxy. No raw/normalized mismatch.

#### Data-flow through SQL binding

- [x] `update_label`: 4 placeholders (`%i`, `%s`, `%s`, `%s`) match 4 args (`table_name`, `label`, `now_utc`, `cluster_uuid`). Positional order correct.
- [x] `dismiss`: 4 placeholders match 4 args (`table_name`, `'dismissed'`, `now_utc`, `cluster_uuid`). Correct.
- [x] `undismiss`: 4 placeholders match 4 args (`table_name`, `'active'`, `now_utc`, `cluster_uuid`). Correct.
- [x] No sentinel/default value issues — all bound values are concrete strings.

#### Guard condition vs business rule alignment

- [x] Empty-string guards in repository methods match the business rule: "do nothing on missing input" — no side effects, no exceptions.
- [x] `is_user_confirmed = 1` is set unconditionally on all three mutation methods — aligns with curation-first principle.
- [x] The `ON DUPLICATE KEY UPDATE` guard in `merge_snapshot_for_tenant` (existing code) protects `label`, `curation_state`, `is_user_confirmed` when `is_user_confirmed = 1`. The new mutations set this flag, so curated rows are protected on next sync. Correct end-to-end.

#### SQL function semantic correctness

- [x] No `FIND_IN_SET`, `GREATEST`, `LEAST`, or `IF()` in new SQL. Simple `UPDATE ... SET ... WHERE` with bound values.
- [x] Existing `ON DUPLICATE KEY UPDATE` guard (not changed in this slice) was audited in Phase 1/2 reviews.

#### Cross-method contract bugs

- [x] `ClusterMutationsController` calls `$this->clusters_repository->update_label($cluster_id, $label)` — matches `ClustersRepositoryInterface::update_label(string, string): void`. Types and format match.
- [x] `SyncPullJob::perform()` calls `$this->projector->project($tenant_id, $snapshot)` — matches `SnapshotProjectorInterface::project(string, array): void`. Correct.
- [x] Return value of `fetch_snapshot()` is checked for `is_wp_error()` before `is_array()` before passing to projector.

#### Boundary value sweep

- [x] **Empty input** — `update_label('', 'x')` returns early at trim guard. `dismiss('')` returns early. `SyncPullJob::perform('')` would pass empty tenant to client — client/projector handle this (projector has its own empty-tenant guard).
- [x] **Single element** — `$delays` array with 4 elements; first iteration uses delay 0. Single-attempt path works correctly. _(Retry loop being removed — see H-1.)_
- [x] **Large input** — Mutations are single-row `UPDATE ... WHERE cluster_uuid = %s`. No unbounded queries.

---

## HIGH Severity

### H-1 · Automatic remote sync scheduled without user consent gate

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `src/api/class-api.php` L49, L52–65; `src/support/class-life-cycle-manager.php` L51–55 |
| **Category** | ANTIPATTERN                                |
| **Status**   | **Fix in this branch** (implement before merge) |

The WP-Cron hook `acx_sync_pull_snapshot` is registered unconditionally in `Api::init()` (L49) and scheduled on plugin activation in `LifecycleManager::activate()` (L51–55). This causes the plugin to make outbound HTTP requests to the recognition backend every hour with zero user opt-in.

**Root cause:** Cron-based background sync is unnecessary in this architecture. The dual-write pattern already syncs both databases on every user mutation. New clusters only appear after user-initiated analysis jobs. Hourly background HTTP traffic provides no value, runs without auth context, and fires unreliably via WP-Cron's page-visit trigger.

**Accepted fix — replace cron with on-demand sync:**

1. **Remove** `wp_schedule_event()` from `LifecycleManager::activate()` (L51–55). Keep the `SNAPSHOT_SYNC_HOOK` constant for `deactivate()`/`uninstall()` cleanup.
2. **Remove** `add_action('acx_sync_pull_snapshot', ...)` from `Api::init()` (L49) and delete `Api::sync_pull_snapshot()` (L52–65). This also resolves L-1 (inline DI construction).
3. **Simplify** `SyncPullJob::perform()`: remove retry/backoff delay loop. Fail fast on error — caller is a user-interactive request.
4. **Add stale-check gate** in `ClustersController` read path: inject `SyncPullJobInterface`, check `SyncStatusController::STALE_THRESHOLD_SECONDS`, call `perform()` before returning local projection if stale. Serve stale data on sync failure.
5. **Update tests**: remove `testActivateSchedulesSnapshotSyncHook`, add stale-check trigger and graceful degradation tests.

Sync triggers after fix:

| Trigger | Where | Mechanism |
|---|---|---|
| User opens clusters UI (stale projection) | `ClustersController` read path | Stale-check → `SyncPullJob::perform()` |
| Clustering/analysis job completes | Post-job projection | Backend returns fresh state; project locally |
| User clicks "Sync Now" (optional, future) | Admin UI action | Explicit pull for diagnostics |

Every remote call is now traceable to a user action. No unsolicited background HTTP traffic.

---

## MEDIUM Severity

### M-1 · Debug log files committed to version control

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `apps/prototype-description-service/logs/recognition.log`; `apps/prototype-description-service/logs/scan_worker.log` |
| **Category** | DEAD_CODE                                  |

Two runtime log files were committed in this branch. These contain timestamped debug output, SQL error details, and tenant UUIDs. The root `.gitignore` only excludes `logs/mcp-server*.log` — it does not cover the `apps/prototype-description-service/logs/` directory.

**Recommended fix:**
1. `git rm --cached` both files.
2. Add `apps/prototype-description-service/logs/` to `.gitignore` (or broaden the existing `logs/` pattern).

### M-2 · Five independent `ClustersRepositoryInterface` test stubs

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `tests/Unit/ClustersControllerTest.php` L87, L156, L210 (3 anonymous classes); `tests/Unit/SnapshotProjectorTest.php` L119 (`SnapshotProjectorClustersSpy`); `tests/Unit/ClusterMutationsControllerDualWriteTest.php` L45 (`ClusterMutationsRepositorySpy`) |
| **Category** | COMPLEXITY                                 |

`ClustersRepositoryInterface` now has 8 methods. Every test file that needs a stub must implement all 8. There are currently 5 independent implementations (3 anonymous, 2 named spies). Adding a new interface method requires updating all 5 locations — this already happened in this branch (3 rounds of test fixes to add `update_label`, `dismiss`, `undismiss` stubs).

**Recommended fix:** Extract a single `NullClustersRepository` (or `ClustersRepositoryStub`) into `tests/stubs/` that returns empty/null defaults for all read methods and no-ops for all mutations. Test files that need spy behavior can extend it and override specific methods. This collapses the 5 locations to 1 canonical definition + targeted overrides.

---

## LOW Severity

### ~~L-1 · Inline DI construction in `sync_pull_snapshot()`~~ — RESOLVED by H-1

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `src/api/class-api.php` L52–65             |
| **Category** | ANTIPATTERN                                |
| **Status**   | **Resolved** — method deleted as part of H-1 cron removal |

`Api::sync_pull_snapshot()` and its inline DI construction are being deleted entirely. `SyncPullJob` will be injected into `ClustersController` via nullable DI (consistent with the existing pattern in `ClusterMutationsController`).

### L-2 · SyncPullJob test coverage gaps

|              |                                            |
| ------------ | ------------------------------------------ |
| **Files**    | `tests/Unit/SyncPullJobTest.php`           |
| **Category** | GAP                                        |
| **Status**   | **Defer** to Phase 3 hardening checklist   |

Current coverage: success path (valid snapshot projected) and failure path (non-retryable 400 error).

After H-1 simplification (retry/backoff removal), the retry-then-success and max-retries-exhausted scenarios become moot. Remaining gaps:

- `fetch_snapshot` returns non-array, non-WP_Error value.
- Empty `$tenant_id`.
- Stale-check integration: `ClustersController` triggers sync when stale, serves stale data when sync fails.

Deferred to Phase 3 hardening checklist. Not blocking for this slice.

---

## Recommended Fix Order

### Phase 1 — Correctness (before merge)

1. **H-1** — Remove cron scheduling, delete `Api::sync_pull_snapshot()`, simplify `SyncPullJob` (remove retry loop), add stale-check gate to `ClustersController`. _(Resolves L-1 as side effect.)_
2. **M-1** — Remove committed log files and update `.gitignore`.

### Phase 2 — Robustness (soon after merge)

3. **M-2** — Extract shared `NullClustersRepository` test stub.

### Phase 3 — Maintainability (deferred)

4. **L-2** — Expand `SyncPullJobTest` with non-array return, empty-tenant, and stale-check integration scenarios.

---

# Consolidated Checklist

## Phase 1 — Correctness (before merge)

- [x] **H-1a** — Remove `wp_schedule_event()` from `LifecycleManager::activate()`. Keep `SNAPSHOT_SYNC_HOOK` constant for cleanup paths.
- [x] **H-1b** — Remove `add_action('acx_sync_pull_snapshot', ...)` from `Api::init()` and delete `Api::sync_pull_snapshot()` method.
- [x] **H-1c** — Simplify `SyncPullJob::perform()`: remove retry/backoff delay loop. Fail fast on error.
- [x] **H-1d** — Inject `?SyncPullJobInterface` into `ClustersController`. Add stale-check gate: if stale, call `perform()` before returning local projection.
- [x] **H-1e** — Remove `testActivateSchedulesSnapshotSyncHook` test. Add tests: stale-check triggers sync; stale-check serves stale data on sync failure.
- [x] **M-1** — `git rm --cached` both log files. Add `apps/prototype-description-service/logs/` to root `.gitignore`.

## Phase 2 — Robustness

- [ ] **M-2** — Extract `NullClustersRepository` into `tests/stubs/` and refactor 5 test stubs to extend it.

## Phase 3 — Maintainability (deferred)

- [ ] **L-2** — Add non-array return, empty-tenant, and stale-check integration tests to `SyncPullJobTest`.

## Success Criteria

- [x] Zero HIGH findings remaining
- [x] No unsolicited background HTTP traffic — every remote call traceable to user action
- [x] `composer test` passes with zero failures
- [x] `composer phpstan` reports zero errors
- [x] All existing tests continue to pass
