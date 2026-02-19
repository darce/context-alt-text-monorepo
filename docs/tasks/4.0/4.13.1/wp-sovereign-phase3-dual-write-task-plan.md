# Sovereign Phase 3: Local-First Writes and Pull Sync (v4.13.1)

## Problem Statement

User curation actions (labeling, dismissing, merging) currently depend on live backend connectivity. If the backend is unreachable, these actions fail silently or return 502 errors. Phase 3 enables local-first persistence so curation is durable in WordPress immediately, with on-demand sync triggered by user interaction to keep the projection current.

## Workflow Principles

- **Local-First Writes**: Persist to local repositories before or alongside proxying to the backend.
- **Curation-First**: Local changes where `is_user_confirmed = 1` must be protected during sync ingestion. This is already enforced by `merge_snapshot_for_tenant`'s `ON DUPLICATE KEY UPDATE` guard (line 113 of `class-clusters-repository.php`).
- **User-Triggered Sync**: Sync only fires as a consequence of user interaction (opening clusters UI, completing analysis). No background cron -- every remote call is traceable to a user action.
- **Eventually Consistent**: On-demand sync on user interaction ensures local projection matches backend state without unsolicited background HTTP traffic.

## Terminology

- **Dual-Write**: Updating the local projection table AND proxying the request to the backend.
- **On-Demand Sync**: A sync pull triggered by user interaction (e.g., opening clusters UI when stale, or after a clustering job completes). Not a background cron.
- **Stale Projection**: A local projection that hasn't been synced within the defined interval (default 1 hour; controlled by `SyncStatusController::STALE_THRESHOLD_SECONDS`). Staleness is checked on read-path entry, not by a timer.

## Current State Analysis

What works:

- `ClustersController` (read-side) has the `should_use_local_projection` gate -- reads local tables when `sync_state.snapshot_version > 0` or `updated_at` is set, otherwise proxies to backend.
- `SnapshotProjector` wraps all projection writes in a DB transaction and delegates to `ClustersRepository::merge_snapshot_for_tenant`, `IdentityMembersRepository::merge_snapshot_for_tenant`, and `SyncStateRepository::upsert_snapshot_version`.
- `merge_snapshot_for_tenant` respects `is_user_confirmed = 1` rows -- label, curation_state, and is_user_confirmed are preserved on conflict.
- `LifecycleManager` defines `SNAPSHOT_SYNC_HOOK = 'acx_sync_pull_snapshot'` and clears it on deactivate/uninstall.

What is missing:

- `ClusterMutationsController` (461 lines) is 100% proxy-only. Its constructor (L32) only registers the XMP refresh hook. No repository injection.
- `ClustersRepositoryInterface` has 5 read methods (`merge_snapshot_for_tenant`, `list_for_tenant`, `list_labels`, `list_top_unlabeled`, `find_by_uuid`) but zero single-row mutation methods.
- `SyncPullJob` class does not exist.
- No on-demand sync trigger on the read path (stale-check → pull).
- Backend snapshot endpoint `GET /tenants/{tenant_id}/clusters/snapshot` is NOT implemented (see External Dependencies).

## Proposed Solution

### 1. Extend ClustersRepositoryInterface + Implementation

Add mutation methods that write directly to `wp_acx_clusters`:

| Method                                              | SQL Semantics                                                                                                 | Sets `is_user_confirmed` |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `update_label(string $cluster_uuid, string $label)` | `UPDATE ... SET label = %s, is_user_confirmed = 1, updated_at = %s WHERE cluster_uuid = %s`                   | Yes                      |
| `dismiss(string $cluster_uuid)`                     | `UPDATE ... SET curation_state = 'dismissed', is_user_confirmed = 1, updated_at = %s WHERE cluster_uuid = %s` | Yes                      |
| `undismiss(string $cluster_uuid)`                   | `UPDATE ... SET curation_state = 'active', is_user_confirmed = 1, updated_at = %s WHERE cluster_uuid = %s`    | Yes                      |

All mutations mark `is_user_confirmed = 1` so the next snapshot merge preserves the user's decision (curation-first principle).

Merge/split are excluded from local persistence for now -- these require cross-row member reassignment that the backend must orchestrate. Local projection will be updated on the next sync pull.

### 2. Inject ClustersRepository into ClusterMutationsController

Add an optional `?ClustersRepositoryInterface` constructor parameter (following the existing DI pattern in `RecognitionController`). Wire it from `RecognitionController`'s constructor.

Dual-write flow for `update_cluster_label`, `dismiss_cluster`, `undismiss_cluster`:

1. Persist locally first via repository method.
2. Proxy to backend.
3. Return the proxy response (success or error). Local write is already committed regardless of backend result.

### 3. Implement SyncPullJob (On-Demand)

New class at `src/sovereign/sync/class-sync-pull-job.php`:

- Accepts `SnapshotProjectorInterface` and a `SnapshotClient` (or client interface).
- Fetches `GET /tenants/{tenant_id}/clusters/snapshot` via `SnapshotClient::fetch_snapshot()`.
- Passes the decoded JSON to `SnapshotProjector::project()`.
- Fails fast on non-retryable errors (400-404, 422). Surfaces error to caller.
- No background retry/backoff -- caller is a user-interactive request that can report failure.

### 4. Trigger Sync from User Interaction (replaces WP-Cron)

**Why not cron:** The dual-write pattern already syncs both databases on every mutation. New clusters only appear after user-initiated analysis jobs. Hourly background HTTP traffic provides no value, runs without auth context, and fires unreliably via WP-Cron's page-visit trigger.

**Sync triggers:**

| Trigger                                   | Where                                          | Mechanism                                                                                                           |
| ----------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| User opens clusters UI (stale projection) | `ClustersController` read path                 | Check `SyncStatusController::STALE_THRESHOLD_SECONDS`; if exceeded, call `SyncPullJob::perform()` before rendering. |
| Clustering/analysis job completes         | `AnalysisJobsController` or job-status polling | Backend returns fresh cluster state; project locally via `SnapshotProjector`.                                       |
| User clicks "Sync Now" (optional)         | Future admin UI action                         | Explicit pull for diagnostics or power users.                                                                       |

**What to remove from current implementation:**

- `wp_schedule_event()` call in `LifecycleManager::activate()` — no cron scheduling.
- `add_action('acx_sync_pull_snapshot', ...)` in `Api::init()` — no cron callback.
- `Api::sync_pull_snapshot()` method — inline DI construction moves to proper injection.
- Retry/backoff delays in `SyncPullJob` — user-triggered sync fails fast.

**What to keep:**

- `LifecycleManager::SNAPSHOT_SYNC_HOOK` constant — still used by `deactivate()` / `uninstall()` for cleanup.
- `SyncPullJob` class — reused as on-demand mechanism, just triggered differently.
- `SnapshotProjector` — unchanged.

### 5. (Backend parallel) Build Snapshot Endpoint

The backend `GET /tenants/{tenant_id}/clusters/snapshot` endpoint does NOT yet exist. This task plan includes its implementation as a parallel workstream.

Contract: `docs/agentic/contracts/cluster-snapshot-api.md` (finalized).

Implementation scope:

- New FastAPI route in `recognition/interface_adapters/http/routers/clusters.py`.
- Query all clusters + members for the tenant from PostgreSQL.
- Compute `snapshot_version` from the highest cluster `updated_at` timestamp (or a monotonic counter).
- Return the response shape defined in the contract.
- Pydantic response model: `ClusterSnapshotResponse` in `recognition/interface_adapters/http/schemas/`.

## Patterns to Follow

### Pattern A: Dual-Write Mutation (Local-First)

```php
public function update_cluster_label( WP_REST_Request $request ): WP_REST_Response|WP_Error {
    $cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
    $label      = sanitize_text_field( (string) $request->get_param( 'label' ) );

    if ( '' === $cluster_id ) {
        return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
    }
    if ( '' === $label ) {
        return new WP_Error( 'missing_label', 'Label cannot be empty.', array( 'status' => 400 ) );
    }

    // 1. Persist locally first -- durable even if backend is unreachable.
    $this->clusters_repository->update_label( $cluster_id, $label );

    // 2. Proxy to backend (best-effort).
    $payload  = array( 'tenant_id' => $this->get_tenant_id(), 'label' => $label );
    $response = $this->proxy_request( 'PATCH', sprintf( '/recognition/clusters/%s', $cluster_id ), $payload );

    $this->maybe_trigger_xmp_refresh_for_response( $response, array( $cluster_id ), 'cluster-label-update' );
    return $response;
}
```

### Pattern B: On-Demand Sync Pull (SyncPullJob)

```php
class SyncPullJob implements SyncPullJobInterface {
    private SnapshotClient $client;
    private SnapshotProjectorInterface $projector;

    public function perform( string $tenant_id ): bool {
        // Fail fast -- no retry/backoff. Caller is user-interactive.
        $snapshot = $this->client->fetch_snapshot( $tenant_id );

        if ( is_wp_error( $snapshot ) || ! is_array( $snapshot ) ) {
            return false;
        }

        $this->projector->project( $tenant_id, $snapshot );
        return true;
    }
}
```

### Pattern D: Stale-Check on Read Path

```php
// In ClustersController, before returning local projection:
if ( $this->sync_state_repository->is_stale( $tenant_id ) ) {
    $this->sync_pull_job->perform( $tenant_id ); // best-effort; stale data served on failure
}
```

### Pattern C: Repository Mutation (update_label)

```php
public function update_label( string $cluster_uuid, string $label ): void {
    global $wpdb;

    $sql = $this->prepare_query(
        'UPDATE %i SET label = %s, is_user_confirmed = 1, updated_at = %s WHERE cluster_uuid = %s',
        array( $this->table_name, $label, gmdate( 'Y-m-d H:i:s' ), $cluster_uuid )
    );

    if ( is_string( $sql ) && '' !== $sql ) {
        $wpdb->query( $sql );
    }
}
```

## Functions to Change

| File                                                           | Line                          | Change                                                                                                |
| -------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| `src/sovereign/repositories/interface-clusters-repository.php` | 44 (EOF)                      | Add `update_label()`, `dismiss()`, `undismiss()` to interface.                                        |
| `src/sovereign/repositories/class-clusters-repository.php`     | New methods                   | Implement `update_label()`, `dismiss()`, `undismiss()` with `UPDATE` SQL + `is_user_confirmed = 1`.   |
| `src/api/class-cluster-mutations-controller.php`               | L32 (constructor)             | Add optional `?ClustersRepositoryInterface $clusters_repository = null` parameter; store as property. |
| `src/api/class-cluster-mutations-controller.php`               | L182 (`update_cluster_label`) | Insert `$this->clusters_repository->update_label(...)` before `proxy_request` call.                   |
| `src/api/class-cluster-mutations-controller.php`               | L207 (`dismiss_cluster`)      | Insert `$this->clusters_repository->dismiss(...)` before `proxy_request` call.                        |
| `src/api/class-cluster-mutations-controller.php`               | L219 (`undismiss_cluster`)    | Insert `$this->clusters_repository->undismiss(...)` before `proxy_request` call.                      |
| `src/api/class-recognition-controller.php`                     | L49 (constructor)             | Instantiate `ClustersRepository` and pass to `new ClusterMutationsController(...)`.                   |
| `src/support/class-life-cycle-manager.php`                     | L51–55 (`activate()`)         | **Remove** `wp_schedule_event()` call. Keep `SNAPSHOT_SYNC_HOOK` constant for cleanup.                |
| `src/api/class-api.php`                                        | L49, L52–65                   | **Remove** `acx_sync_pull_snapshot` action hook and `sync_pull_snapshot()` method.                    |
| `src/api/class-clusters-controller.php`                        | Read path                     | Add stale-check gate: if stale, call `SyncPullJob::perform()` before returning local projection.      |
| `src/sovereign/sync/class-sync-pull-job.php`                   | Existing file                 | **Simplify**: remove retry/backoff delays. Fail fast on error. Keep `perform()` contract.             |
| `src/sovereign/sync/interface-sync-pull-job.php`               | Existing file                 | No change -- `SyncPullJobInterface::perform(string $tenant_id): bool` still valid.                    |

### Backend (parallel)

| File                                                         | Line      | Change                                                                               |
| ------------------------------------------------------------ | --------- | ------------------------------------------------------------------------------------ |
| `recognition/interface_adapters/http/routers/clusters.py`    | New route | Add `GET /tenants/{tenant_id}/clusters/snapshot` endpoint.                           |
| `recognition/interface_adapters/http/schemas/`               | New file  | `ClusterSnapshotResponse` Pydantic model matching contract.                          |
| `recognition/application/services/` or `recognition/domain/` | New       | Service to query all clusters + members for a tenant and build the snapshot payload. |

## Related Files

| File                                                               | Note                                                                                                                           |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `src/sovereign/sync/class-snapshot-projector.php`                  | `project(string $tenant_id, array $snapshot): void` -- expects `{snapshot_version, clusters, members}`. Used by `SyncPullJob`. |
| `src/sovereign/sync/interface-snapshot-projector.php`              | `SnapshotProjectorInterface`.                                                                                                  |
| `src/sovereign/repositories/class-identity-members-repository.php` | Members repo used by projector.                                                                                                |
| `src/sovereign/repositories/class-sync-state-repository.php`       | Sync state tracking (`upsert_snapshot_version`, `get_snapshot_version`, `get_last_updated`).                                   |
| `src/api/class-abstract-recognition-proxy-controller.php`          | Base class with `proxy_request()`, `get_tenant_id()`, `get_recognition_base_url()`.                                            |
| `src/api/class-clusters-controller.php`                            | Read-side controller with `should_use_local_projection()` gate (reference for dual-write consistency).                         |
| `docs/agentic/contracts/cluster-snapshot-api.md`                   | Finalized contract for the snapshot endpoint response shape, retry semantics, and pagination.                                  |
| `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md`                   | Source epic for Phase 3 definition.                                                                                            |
| `tests/php/sovereign/`                                             | Existing test directory for sovereign repository and projector tests.                                                          |

## External Dependencies

| Dependency                                            | Owner               | Status                                          | Blocker                                                |
| ----------------------------------------------------- | ------------------- | ----------------------------------------------- | ------------------------------------------------------ |
| `GET /tenants/{tenant_id}/clusters/snapshot` contract | recognition-service | Finalized (`contracts/cluster-snapshot-api.md`) | No -- contract is ready                                |
| `GET /tenants/{tenant_id}/clusters/snapshot` route    | recognition-service | **Included in this plan** (Phase 2b)            | Blocks live sync pull; PHP-side tests use fixture data |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add `update_label(string $cluster_uuid, string $label): void` to `ClustersRepositoryInterface`.
- [x] Add `dismiss(string $cluster_uuid): void` to `ClustersRepositoryInterface`.
- [x] Add `undismiss(string $cluster_uuid): void` to `ClustersRepositoryInterface`.
- [x] Create `src/sovereign/sync/interface-sync-pull-job.php` with `SyncPullJobInterface::perform(string $tenant_id): bool`.
- [x] Create `src/sovereign/sync/class-sync-pull-job.php` shell implementing `SyncPullJobInterface`.
- [x] Add test stubs: `ClustersRepositoryMutationTest`, `ClusterMutationsControllerDualWriteTest`, `SyncPullJobTest`.
- [x] Verify scaffolds: `composer test`, `composer phpstan`.

## Phase 1: Local Mutation Persistence (PHP Plugin)

- [x] Implement `update_label()` in `ClustersRepository` (`UPDATE ... SET label, is_user_confirmed=1, updated_at`).
- [x] Implement `dismiss()` in `ClustersRepository` (`UPDATE ... SET curation_state='dismissed', is_user_confirmed=1`).
- [x] Implement `undismiss()` in `ClustersRepository` (`UPDATE ... SET curation_state='active', is_user_confirmed=1`).
- [x] Add optional `?ClustersRepositoryInterface` constructor param to `ClusterMutationsController`.
- [x] Wire `ClustersRepository` into `ClusterMutationsController` from `RecognitionController` constructor.
- [x] Dual-write `update_cluster_label`: call `update_label()` before `proxy_request()`.
- [x] Dual-write `dismiss_cluster`: call `dismiss()` before `proxy_request()`.
- [x] Dual-write `undismiss_cluster`: call `undismiss()` before `proxy_request()`.
- [x] Tests: local write succeeds even when proxy returns WP_Error.
- [x] Tests: `is_user_confirmed` is set to 1 after mutation.
- [x] Verify: `composer test`, `composer phpstan`.

## Phase 2a: On-Demand Sync Pull (PHP Plugin)

_Replaces cron-based background sync. All sync is triggered by user interaction._

- [x] Implement `SyncPullJob::perform()`: fetch snapshot via `SnapshotClient`, decode, pass to `SnapshotProjector::project()`.
- [x] **Remove** `wp_schedule_event()` from `LifecycleManager::activate()` -- no cron scheduling. _(H-1a)_
- [x] **Remove** `add_action('acx_sync_pull_snapshot', ...)` from `Api::init()` and delete `Api::sync_pull_snapshot()` method. _(H-1b)_
- [x] **Simplify** `SyncPullJob::perform()`: remove retry/backoff delay loop. Fail fast on non-retryable errors. _(H-1c)_
- [x] Add stale-check gate in `ClustersController` read path: if stale, call `SyncPullJob::perform()` before returning local projection. _(H-1d)_
- [x] Inject `SyncPullJobInterface` into `ClustersController` (nullable DI, consistent with existing pattern). _(H-1d)_
- [x] Tests: `SyncPullJob` projects valid snapshot payload correctly.
- [x] Tests: `SyncPullJob` returns false on non-200 response without corrupting local data.
- [x] Remove `testActivateSchedulesSnapshotSyncHook` (cron test no longer relevant). _(H-1e)_
- _Resolved in Phase 3:_ Tests: `ClustersController` triggers sync when projection is stale.
- _Resolved in Phase 3:_ Tests: `ClustersController` serves stale data gracefully when sync fails.
- [x] Verify: `composer test`, `composer phpstan`.

## Phase 2b: Snapshot Endpoint (Backend -- parallel)

- [x] Create `ClusterSnapshotResponse` Pydantic model matching `contracts/cluster-snapshot-api.md`.
- [x] Create `ClusterSnapshotMemberResponse` Pydantic model for nested members.
- [x] Implement snapshot query service: load all clusters + members for a tenant.
- [x] Compute `snapshot_version` (monotonic -- e.g., max `updated_at` as unix epoch or sequence counter).
- [x] Add `GET /tenants/{tenant_uuid}/clusters/snapshot` route in `clusters.py`.
- [x] Tests: endpoint returns correct shape for tenant with clusters.
- [x] Tests: endpoint returns `404` for unknown tenant.
- [x] Verify: `make check` (ruff + mypy + pytest). _(476 passed, 0 failed)_

## Phase 3: Verification and Hardening

- [x] Integration test: dual-write failure modes (remote fail, local success -- user sees error but data is locally persisted). _(dismiss + undismiss + update_label)_
- [x] Integration test: snapshot ingestion preserves locally curated labels (`is_user_confirmed = 1` rows survive merge). _(SovereignProjectionIntegrationTest)_
- [x] Integration test: stale-check triggers sync on read path and serves fresh data. _(ClustersControllerTest)_
- [x] Integration test: stale-check sync failure still returns stale local data (graceful degradation). _(ClustersControllerTest)_
- [ ] Manual smoke: label a cluster with backend stopped, restart backend, open clusters UI, confirm sync fires and label persists.
- [ ] Manual smoke: run full cycle -- clusters load from proxy, trigger analysis, stop backend, clusters still render from local.

### Audit Remediation (deferred from branch audit)

- [x] **M-2** — Extract `NullClustersRepository` into `tests/stubs/` and refactor 5 anonymous test stubs to extend it. _(Audit finding M-2: COMPLEXITY)_
- [x] **L-2** — Add `SyncPullJobTest` cases: non-array return, empty `$tenant_id`, stale-check integration. _(Audit finding L-2: GAP)_
- [x] Unit test: `ClustersController` triggers `SyncPullJob::perform()` when projection is stale. _(testStaleProjectionTriggersSyncPullBeforeServing)_
- [x] Unit test: `ClustersController` serves stale data gracefully when sync fails (null sync*pull_job or perform returns false). *(testStaleProjectionServesStaleDataWhenSyncFails + testNullSyncPullJobDoesNotCrashOnStaleProjection)\_

### Verification

- [x] `composer test` — 141 tests, 452 assertions, 0 failures.
- [x] `composer phpstan` — 46/46 files, 0 errors.

## Phase 4: Thumbnail Deprecations (Follow-up)

_Moved to standalone task plan: [`thumbnail-deprecation-task-plan.md`](thumbnail-deprecation-task-plan.md)._

## Success Criteria

- [ ] Label updates are reflected in `wp_acx_clusters` immediately (local write).
- [ ] Dismissing/undismissing a cluster persists `curation_state` to `wp_acx_clusters` locally.
- [ ] Disabling backend during a mutation does NOT prevent the local update from persisting.
- [ ] `last_synced_at` updates on user-triggered sync (stale-check on read path, or after analysis job completes).
- [ ] No unsolicited background HTTP traffic -- every remote call is traceable to a user action.
- [ ] Snapshot ingestion does NOT overwrite rows where `is_user_confirmed = 1`.
- [ ] `composer test` passes with zero failures.
- [ ] `composer phpstan` reports zero errors.
- [ ] Backend `make check` passes (ruff + mypy + pytest).
