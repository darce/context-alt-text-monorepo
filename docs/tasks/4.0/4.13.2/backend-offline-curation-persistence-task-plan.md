# 4.13.2 Backend Task Plan — Offline Curation Persistence & Reconciliation

## Problem Statement
Manual smoke confirms a regression: if cluster labeling happens while backend is down, curation does not persist after reload/restart. The system currently dual-writes local rows, but read-path gating and sync wiring prevent those rows from being reliably served and reconciled.

## Workflow Principles

- Local curation must be durable and visible immediately, independent of backend reachability.
- Read-path authority must not depend on backend availability once local curation exists.
- Reconciliation is best-effort and must never erase locally confirmed curation.
- Follow TDD: add failing tests for the reported repro before implementation.

## Terminology

- **Projection gate**: The condition deciding whether cluster reads use local sovereign tables or backend proxy.
- **Local curation marker**: Tenant-scoped sync-state row proving local projection should be considered authoritative.
- **Reconciliation pull**: Snapshot fetch + project cycle to align local tables with backend state.

## Current State Analysis

- [HIGH][GAP] `ClustersController` read-path only uses local projection when sync-state exists, not when local curation exists. `should_use_local_projection_gate()` checks only `acx_sync_state` (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php:165`).
- [HIGH][GAP] Dual-write mutations persist local cluster rows but do not touch sync-state, so projection gate can remain false after offline curation (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php:181`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php:199`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php:215`).
- [HIGH][GAP] `update_label`, `dismiss`, `undismiss` are bare `UPDATE … WHERE cluster_uuid = %s` returning `void` — they affect **zero rows** when no prior sync has populated local tables. Touching sync-state after a zero-row UPDATE opens the projection gate onto empty tables, returning zero clusters instead of proxying. Fix: change to `int` return type (affected row count), gate-touch conditional on return value `> 0`.
- [HIGH][GAP] No bootstrap path for initial sync. `should_use_local_projection()` only fires sync when the gate is already `true` (sync-state exists). Without an existing sync-state row the gate returns `false`, the proxy is used, and no sync ever occurs. Fix: after successful proxy-read fallback (2xx) in `ClustersController`, perform an **inline** `SyncPullJob::perform_bypass_cooldown()` call (fail-closed) to seed local tables immediately while the backend is still reachable. The call bypasses the sync cooldown because the successful proxy-read proves the backend is reachable right now, making any active cooldown stale. If the inline attempt fails, schedule `acx_bootstrap_sync` via `wp_schedule_single_event` as a safety-net retry. The inline call is synchronous and adds one-time latency to the first proxy-read response (snapshot fetch + projection); this is an acceptable trade-off vs. the risk of never seeding local tables. Bootstrap must NOT fire when the proxy-read itself fails (4xx/5xx/WP_Error).
- [HIGH][GAP] `RecognitionController` default wiring constructs `ClustersController` without a `SyncPullJob`, so stale projections do not reconcile on standard runtime path (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php:46`).
- [HIGH][BUG] `SyncPullJob::perform()` has a bool contract but does not guard projector exceptions; `SnapshotProjector::project()` can throw, causing request-time failures instead of graceful stale-serving (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php:19`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-clusters-controller.php:340`).
- [HIGH][BUG] `undismiss()` writes `curation_state='active'` with `is_user_confirmed=1`. Two compounding bugs: (a) `'active'` is non-canonical — `normalize_curation_state` only accepts `uncurated|confirmed|dismissed`; (b) `is_user_confirmed=1` activates the merge guard `IF(is_user_confirmed = 1, curation_state, …)`, making the non-canonical state **permanent**. Fix must align with backend semantics: backend undismiss clears `dismissed_at` and keeps `user_confirmed=False`, emitting `curation_state="active"` + `is_user_confirmed=false` in the snapshot (clusters.py:169, responses.py:386). Plugin maps backend `"active"` to `"uncurated"`. Therefore undismiss should write `curation_state='uncurated'` with `is_user_confirmed=0` — this matches the backend state AND allows the merge guard to overwrite freely on next sync reconciliation (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php:374`, `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php:469`).
- [MEDIUM][GAP] Mutation handlers return `$this->proxy_request(…)` directly. When backend is down the frontend receives a `WP_Error` even though the local write succeeded, contradicting the "visible immediately" principle. Accepted limitation for this task; tracked for future improvement.
- [MEDIUM][SCOPE] `merge_cluster`, `split_cluster`, `reassign_cluster_identity`, `create_cluster_for_identity`, `revert_merge_cluster` are proxy-only — no local writes. These are intentionally out of scope for this plan; they require backend availability and are not curation-preservation operations.
- [MEDIUM][GAP] New dual-write tests verify method calls, but do not cover the failing smoke flow (offline label, reload, post-restart reconciliation) (`/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/ClusterMutationsControllerDualWriteTest.php:27`).

## Proposed Solution

1. Add a dedicated `touch_local_curation_marker()` method to `SyncStateRepositoryInterface` that opens the projection gate **and forces staleness** via `INSERT … ON DUPLICATE KEY UPDATE updated_at = '1970-01-01 00:00:00'`, ensuring reconciliation fires on next read whether the row is new or pre-existing.
2. Change `ClustersRepositoryInterface` mutation methods (`update_label`, `dismiss`, `undismiss`) from `void` to `int` return type, returning `$wpdb->rows_affected`. Guard gate-touch on `$affected > 0` at the controller layer, avoiding reliance on global mutable `$wpdb` state.
3. Wire a real `SyncPullJob` into the default `RecognitionController -> ClustersController` composition path, including shared `SyncStateRepository` into `ClusterMutationsController`.
4. Harden `SyncPullJob` to fail closed (`false`) on projector exceptions, with a transient-based cooldown to prevent repeated slow sync attempts during outages.
5. Fix undismiss to write `curation_state = 'uncurated'` with `is_user_confirmed = 0`. This matches backend semantics (undismiss clears `dismissed_at`, keeps `user_confirmed=False` → snapshot emits `"active"` which normalizes to `"uncurated"`). Setting `is_user_confirmed = 0` allows the merge guard to overwrite the row on next sync, preventing permanent divergence.
6. Add `'active'` as an explicit accepted value in `normalize_curation_state()`, mapping it to `'uncurated'` intentionally rather than via fallthrough default.
7. Add bootstrap sync: on `ClustersController` proxy-read fallback success (2xx response), perform an **inline** `SyncPullJob::perform_bypass_cooldown( $tenant_id )` call (fail-closed) to seed local tables immediately while the backend is confirmed reachable. The cooldown bypass is necessary because the successful proxy-read proves the backend is reachable right now — any active cooldown transient is stale in this context. The inline call is synchronous and adds **one-time latency** to the first proxy-read response (snapshot fetch + projection). This is an acceptable trade-off: without it, WP-Cron scheduling alone cannot guarantee the tick fires before the backend goes down, which would leave local tables empty and offline mutations hitting zero-row UPDATEs. If the inline attempt fails (returns `false`), schedule `wp_schedule_single_event( time(), 'acx_bootstrap_sync', [ $tenant_id ] )` as a safety-net retry, guarded by `wp_next_scheduled()` to avoid duplicate scheduling. Do **not** schedule the cron when inline succeeds — it would cause a redundant full snapshot pull, adding avoidable backend/DB load. The cron callback must also use `perform_bypass_cooldown()` since the cooldown set by the failed inline attempt may still be active when the cron fires. Bootstrap must **not** fire when the proxy-read itself fails (non-2xx / `WP_Error`) — the backend is not confirmed reachable in that case. The `acx_bootstrap_sync` action must be registered via `add_action( 'acx_bootstrap_sync', … )` — without a registered callback the cron event is a no-op (same pattern as `ClusterMutationsController::__construct` registering `XMP_REFRESH_CLUSTER_HOOK`).
8. Add TDD coverage that reproduces and locks the manual smoke path.

## Patterns to Follow

### Local-Write Projection Marker

**WARNING**: Do NOT use `upsert_snapshot_version($tenant_id, 0)` — that method always sets `updated_at = NOW()`, which tells `is_projection_stale()` "we just synced" and **suppresses reconciliation for up to 3600 seconds** after backend recovery.

Instead, add a dedicated method that opens the gate and forces staleness:

```php
// SyncStateRepositoryInterface — new method
public function touch_local_curation_marker( string $tenant_id ): void;

// SyncStateRepository implementation — always backdates updated_at to epoch.
// INSERT … ON DUPLICATE KEY UPDATE ensures this works whether the row exists or not:
//   - No row yet: inserts with epoch updated_at → gate opens, stale check true.
//   - Row exists with recent updated_at: backdates to epoch → forces reconciliation on next read.
public function touch_local_curation_marker( string $tenant_id ): void {
    global $wpdb;
    $normalized = trim( $tenant_id );
    if ( '' === $normalized ) { return; }
    $stream_name = $this->stream_name_for_tenant( $normalized );
    $sql = $this->prepare_query(
        'INSERT INTO %i (stream_name, last_snapshot_version, updated_at)
         VALUES (%s, 0, %s)
         ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)',
        array( $this->table_name, $stream_name, '1970-01-01 00:00:00' )
    );
    if ( is_string( $sql ) && '' !== $sql ) {
        $wpdb->query( $sql );
    }
}
```

```php
// In ClusterMutationsController after successful local write:
// Repository mutation methods now return int (affected row count).
$tenant_id = $this->get_tenant_id();
$affected = $this->clusters_repository->update_label( $cluster_id, $label );
if ( $affected > 0 ) {
    $this->sync_state_repository->touch_local_curation_marker( $tenant_id );
}
```

**Key properties:**
- `ON DUPLICATE KEY UPDATE updated_at = VALUES(updated_at)` backdates to epoch whether the row is new or pre-existing — always forces reconciliation.
- Epoch `updated_at` means `is_projection_stale()` returns `true`, so the next read triggers `SyncPullJob::perform()` for reconciliation.
- Guard on repository return value `$affected > 0` prevents opening the gate when the UPDATE matched no rows (no prior sync populated local tables). This avoids relying on global `$wpdb->rows_affected` state.
- After successful reconciliation, `upsert_snapshot_version()` writes a real `updated_at = NOW()`, restoring normal staleness behavior.

### Fail-Closed Sync Pull with Transient Cooldown

Without throttling, every read while backend is down triggers a fetch attempt (epoch `updated_at` → always stale). The `SnapshotClient` timeout + retry adds latency to every request. A **transient-based** cooldown prevents repeated slow attempts **across PHP requests** (in-memory cooldowns are ineffective because WordPress creates fresh objects per request):

```php
private const SYNC_COOLDOWN_SECONDS = 30;
private const COOLDOWN_TRANSIENT_PREFIX = 'acx_sync_cooldown_';

public function perform(string $tenant_id): bool {
    $transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
    if ( false !== get_transient( $transient_key ) ) {
        return false; // Skip — recent failure, serve stale.
    }

    return $this->do_sync( $tenant_id, $transient_key );
}

/**
 * Bootstrap variant: bypasses cooldown because the caller has confirmed
 * backend reachability (e.g., a successful proxy-read just completed).
 */
public function perform_bypass_cooldown(string $tenant_id): bool {
    $transient_key = self::COOLDOWN_TRANSIENT_PREFIX . md5( $tenant_id );
    return $this->do_sync( $tenant_id, $transient_key );
}

private function do_sync(string $tenant_id, string $transient_key): bool {
    $snapshot = $this->client->fetch_snapshot($tenant_id);
    if (is_wp_error($snapshot) || !is_array($snapshot)) {
        set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
        return false;
    }

    try {
        $this->projector->project($tenant_id, $snapshot);
        return true;
    } catch (\Throwable $t) {
        set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
        return false;
    }
}
```

**Key properties:**
- Uses WordPress transients (`set_transient`/`get_transient`), which persist across requests via DB or object cache. This is the same pattern used in `AnalysisJobsController` for job tracking.
- 30-second TTL auto-expires — no cleanup needed. Cooldown lifts automatically.
- Scoped per tenant via `md5($tenant_id)` suffix.
- Successful sync does not set the transient, so the next stale check proceeds normally.
- Bootstrap callers use `perform_bypass_cooldown()` to skip the transient check — the proxy-read success proves the backend is reachable, making any active cooldown stale.
- Transient reads are cheap (single DB/cache lookup); the cost is only incurred when the stale gate fires.

### Default Runtime Wiring (No Null Sync Job)

```php
$clusters_repo = new ClustersRepository();
$members_repo = new IdentityMembersRepository();
$sync_repo = new SyncStateRepository();
$projector = new SnapshotProjector($clusters_repo, $members_repo, $sync_repo);
$sync_job = new SyncPullJob(new SnapshotClient(), $projector);
$clusters_controller = new ClustersController($clusters_repo, $members_repo, $sync_repo, $sync_job);
$cluster_mutations_controller = new ClusterMutationsController($clusters_repo, $sync_repo);
```

Note: `ClusterMutationsController` must receive the **shared** `$sync_repo` so mutation-time markers are visible to the read-path gate.

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | 169 | Inject `SyncStateRepositoryInterface`; use repository `int` return values to guard `touch_local_curation_marker()` calls after local mutation writes (`update_cluster_label`, `dismiss_cluster`, `undismiss_cluster`). |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-recognition-controller.php` | 37 | Build/wire `SyncPullJob` and pass non-null job + shared repositories into `ClustersController`. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-clusters-controller.php` | __construct | Register `acx_bootstrap_sync` action handler via `add_action( 'acx_bootstrap_sync', [ $this, 'perform_bootstrap_sync' ] )`. Callback uses `perform_bypass_cooldown()` since cooldown from failed inline may still be active. Without this, the `wp_schedule_single_event` call in the proxy-read fallback schedules a cron event with no callback. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/interface-sync-pull-job.php` | 8 | Add `perform_bypass_cooldown( string $tenant_id ): bool` to interface contract. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` | 19 | Catch projector exceptions and return `false` to preserve graceful stale-serving contract. Add `perform_bypass_cooldown()` method for bootstrap callers. Extract shared `do_sync()` private method. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | 357 | Change `undismiss()` to `curation_state='uncurated'` AND `is_user_confirmed=0`. Matches backend semantics (undismiss → `"active"` + `user_confirmed=False`). Setting `is_user_confirmed=0` allows merge guard to overwrite on next sync, preventing permanent divergence. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | 469 | Add `'active'` as explicit accepted value in `normalize_curation_state()` mapping to `'uncurated'`, replacing implicit fallthrough default. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/interface-sync-state-repository.php` | 8 | Add `touch_local_curation_marker( string $tenant_id ): void` method to interface. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | 33 | Implement `touch_local_curation_marker()` with `INSERT … ON DUPLICATE KEY UPDATE updated_at = epoch` (forces staleness whether row is new or pre-existing). |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/interface-clusters-repository.php` | 50 | Change `update_label()`, `dismiss()`, `undismiss()` return types from `void` to `int` (affected row count). |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | 298 | Update `update_label()`, `dismiss()`, `undismiss()` implementations to return `(int) $wpdb->rows_affected`. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/ClusterMutationsControllerDualWriteTest.php` | 27 | Add failing-first assertions for sync-state touch on proxy failure. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/ClustersControllerTest.php` | 87 | Add regression test: after local mutation marker, list endpoints stay local even when backend unavailable. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/SyncPullJobTest.php` | 20 | Add test proving projector exception returns `false` (no throw). |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/RecognitionControllerTest.php` | 16 | Add composition test verifying default runtime path wires a non-null sync job. |

## Related Files

| File | Note |
| --- | --- |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` | Projection gate behavior currently tied only to sync-state presence. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Can throw `RuntimeException` and re-throws after rollback; impacts sync pull error handling contract. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/interface-sync-pull-job.php` | Must add `perform_bypass_cooldown()` to interface. Any anonymous test doubles implementing `SyncPullJobInterface` (e.g., `ClustersControllerTest:313`) must also implement it. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | `merge_snapshot_for_tenant` uses `IF(is_user_confirmed = 1, curation_state, …)` guard — any non-canonical state written with `is_user_confirmed=1` becomes permanent. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/Unit/SovereignProjectionIntegrationTest.php` | Existing SQL-structure guard tests for curated-label preservation. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/stubs/class-null-sync-state-repository.php` | Must be updated to implement new `touch_local_curation_marker()` method. |
| `/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/tests/stubs/wp.php` | Missing `delete_transient()` stub (line 925 area). Required for cooldown-expiry test simulation. |
| `/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/4.0/4.13.2/next-steps-task-plan.md` | Parent Phase 3 closure + Phase 4 execution sequence. |

---

# Consolidated Checklist

## Completed

- [x] Repro confirmed: labeling with backend stopped does not persist on reload/restart (manual smoke).
- [x] Untracked Phase 3 files reviewed against branch review heuristics (correctness, gate logic, SQL/state consistency, coverage gaps).

## Phase 0: Scaffolding

- [ ] Add `touch_local_curation_marker()` to `SyncStateRepositoryInterface` and `NullSyncStateRepository` stub.
- [ ] Change `ClustersRepositoryInterface` mutation methods (`update_label`, `dismiss`, `undismiss`) from `void` to `int` return type. Update implementations to return `(int) $wpdb->rows_affected`. Update `NullClustersRepository` stub.
- [ ] Add/extend test doubles for `SyncStateRepositoryInterface` in mutation/controller tests.
- [ ] Add `delete_transient()` stub to `tests/stubs/wp.php` (currently missing — only `get_transient`/`set_transient` are stubbed). Without it, cooldown-expiry tests cannot simulate TTL expiry via explicit deletion. Implementation: `unset( $GLOBALS['__ac_transients'][$transient] )`.
- [ ] Add failing regression tests for offline label persistence flow before implementation.
- [ ] Add failing test for `SyncPullJob` projector exception handling.
- [ ] Add failing test for undismiss state (`'uncurated'` + `is_user_confirmed=0`).
- [ ] Verify scaffolds compile: `cd /Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context && composer test`.

## Phase 1: Correctness Fixes (Offline Persistence)

- [ ] Implement `touch_local_curation_marker()` in `SyncStateRepository` using `INSERT … ON DUPLICATE KEY UPDATE updated_at = '1970-01-01 00:00:00'` (opens gate AND forces staleness whether row is new or pre-existing).
- [ ] Inject `SyncStateRepositoryInterface` into `ClusterMutationsController` constructor.
- [ ] After each local mutation write, use repository return value (`$affected > 0`) before calling `touch_local_curation_marker()` (prevents opening gate onto empty tables when no prior sync has populated rows; avoids reliance on global `$wpdb->rows_affected`).
- [ ] Update `ClustersRepository::undismiss()` to `curation_state = 'uncurated'` AND `is_user_confirmed = 0`. Matches backend semantics: undismiss clears `dismissed_at` + keeps `user_confirmed=False` → snapshot emits `"active"` (normalized to `"uncurated"`). Setting `is_user_confirmed=0` allows the merge guard to overwrite the row on next sync.
- [ ] Add `'active'` as explicit accepted value in `normalize_curation_state()` mapping to `'uncurated'`.
- [ ] Ensure mutation handlers keep local-first write semantics when proxy fails.

## Phase 2: Runtime Sync Wiring & Resilience

- [ ] Wire non-null `SyncPullJob` in default `RecognitionController` composition.
- [ ] Ensure `ClustersController` default path receives shared repositories + sync job.
- [ ] Wire shared `SyncStateRepository` into `ClusterMutationsController` construction in `RecognitionController`.
- [ ] Add try/catch in `SyncPullJob::perform()` around projector call and return `false` on throwable.
- [ ] Add transient-based sync-attempt cooldown (30s TTL) to `SyncPullJob` using `set_transient`/`get_transient` so the cooldown persists across PHP requests (in-memory cooldowns are ineffective in WP's request-per-process model).
- [ ] Add bootstrap sync: after successful proxy-read fallback in `ClustersController`, call `SyncPullJob::perform_bypass_cooldown()` inline to seed local tables immediately. If the inline call returns `false`, schedule `wp_schedule_single_event( time(), 'acx_bootstrap_sync', [ $tenant_id ] )` as a safety-net retry (guarded by `wp_next_scheduled()`). Do **not** schedule the cron when inline succeeds.
- [ ] Register `acx_bootstrap_sync` action handler via `add_action( 'acx_bootstrap_sync', … )` in `ClustersController::__construct` (or equivalent composition point). The callback must also use `perform_bypass_cooldown()` since the cooldown from the failed inline attempt may still be active. Without this registration the scheduled cron event is a no-op. Follow the same pattern as `ClusterMutationsController::__construct` line 37.

## Phase 3: Tests

- [ ] Unit: offline mutation updates local row and sync-state marker even on proxy failure.
- [ ] Unit: mutation that affects zero rows (no prior sync) does NOT touch sync-state marker.
- [ ] Unit: post-mutation list reads local projection when backend is unreachable.
- [ ] Unit: `SyncPullJob::perform()` returns `false` when projector throws.
- [ ] Unit: `SyncPullJob::perform()` skips fetch when transient cooldown is set after failure.
- [ ] Unit: `SyncPullJob::perform()` retries after transient is deleted (simulating expiry). Note: WP test stubs store transients without TTL handling, so tests must explicitly `delete_transient()` to model expiry rather than relying on time passage. Requires `delete_transient()` stub added in Phase 0.
- [ ] Unit: `RecognitionController` default wiring includes sync job and shared sync-state repo in mutations controller.
- [ ] Unit: undismiss stores `curation_state = 'uncurated'` AND `is_user_confirmed = 0` (not `'active'`, not `'confirmed'` with confirmed=1).
- [ ] Unit: `normalize_curation_state()` explicitly maps `'active'` to `'uncurated'`.
- [ ] Unit: `touch_local_curation_marker()` forces staleness even when sync-state row already exists with recent `updated_at`.
- [ ] Unit: `update_label()`, `dismiss()`, `undismiss()` return affected row count (0 when no matching row, 1 when row exists).
- [ ] Unit: successful proxy-read fallback calls `SyncPullJob::perform_bypass_cooldown()` inline to seed local tables.
- [ ] Unit: inline bootstrap does NOT schedule cron when inline sync succeeds.
- [ ] Unit: inline bootstrap schedules `acx_bootstrap_sync` cron only when inline sync returns `false`.
- [ ] Unit: firing `acx_bootstrap_sync` cron event invokes `SyncPullJob::perform_bypass_cooldown()` with correct tenant context (callback execution correctness, not just registration).
- [ ] Unit: bootstrap `perform_bypass_cooldown()` executes even when cooldown transient is active (proves cooldown bypass).
- [ ] Unit: `acx_bootstrap_sync` action handler is registered in `ClustersController::__construct` (cron event without handler is a no-op).
- [ ] Unit: duplicate proxy-read fallback does not double-schedule (guarded by `wp_next_scheduled`).
- [ ] Unit: failed proxy-read (non-2xx / `WP_Error`) does NOT trigger inline bootstrap sync.
- [ ] Unit: failed proxy-read does NOT schedule `acx_bootstrap_sync` cron event.
- [ ] Manual smoke: run backend down/up scenario and verify label persistence + reconciliation using local WP service workflow.

## Stretch Goals

- [ ] Return a synthetic success response (with sync-pending flag) from mutation handlers when local write succeeds but proxy fails, instead of exposing the `WP_Error` to the frontend.
- [ ] Add lightweight telemetry event for sync-pull failures to speed smoke-test diagnosis.

## Known Limitations (Accepted)

- `merge_cluster`, `split_cluster`, `reassign_cluster_identity`, `create_cluster_for_identity`, `revert_merge_cluster` remain proxy-only. They require backend availability and are not curation-preservation operations. No local dual-write is planned for this task.
- Mutation handlers still return proxy `WP_Error` to the frontend when backend is unreachable, even though the local write succeeded. The user sees an error flash but data persists locally. Tracked as stretch goal above.
- Offline curation persistence requires that the plugin has successfully loaded clusters at least once (via proxy-read) to populate local projection rows. The bootstrap sync (Phase 2) automates this via a two-tier strategy: (1) an **inline** `SyncPullJob::perform_bypass_cooldown()` call during the proxy-read fallback seeds local tables immediately while the backend is confirmed reachable (bypassing cooldown since proxy success proves reachability), and (2) a `wp_schedule_single_event` cron event serves as a safety-net retry **only if the inline attempt fails**. The inline call is synchronous and adds one-time latency to the first proxy-read response (snapshot fetch + projection); this is an acceptable trade-off vs. the risk of never seeding local tables if cron doesn't fire before the backend goes down. Until that first successful sync, mutation UPDATEs affect zero rows and the marker is correctly skipped.

## Success Criteria

- [ ] Offline label/dismiss/undismiss persists across reloads without backend connectivity (after at least one successful cluster read that bootstraps local projection).
- [ ] After backend restart, reconciliation fires on next read and does not erase locally confirmed curation.
- [ ] Default runtime path performs stale-check sync pulls (no null sync job in production wiring).
- [ ] First successful proxy-read fallback seeds local tables via inline `SyncPullJob::perform_bypass_cooldown()` (one-time latency, cooldown-bypassed). Cron safety net scheduled only on inline failure.
- [ ] `touch_local_curation_marker()` forces staleness even when sync-state row already exists with recent `updated_at`.
- [ ] Repeated sync failures do not add latency beyond transient-based cooldown period (30s TTL, persists across requests).
- [ ] Undismiss writes `curation_state='uncurated'` + `is_user_confirmed=0`, matching backend snapshot semantics and allowing merge guard to overwrite on reconciliation.
- [ ] Repository mutation methods return affected row count; controller does not depend on global `$wpdb` state.
- [ ] `composer test` and `composer phpstan` pass; any failures are explicitly triaged in this task.
