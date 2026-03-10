# Phase 3: Minimal Durable Sync Replay

## Problem Statement

Curation mutations fall into two failure categories today:

1. **Backend-first proxies (label rename, merge, split, reassign, create-for-identity)**: these call the backend synchronously and only update local state on success. If the backend is offline, the operator sees an error and the mutation is lost entirely -- there is no local record to retry.
2. **Local-first outbox (dismiss/undismiss, person CRUD, person bind/unbind)**: these write local state and enqueue an outbox operation. If the backend is offline, the mutation is durable locally and replays when connectivity resumes.

The goal is to move category-1 mutations to the outbox-first pattern so that all curation intents are durable regardless of backend connectivity. The operator should also have visibility into which local changes are queued, failed, or safely acknowledged.

## Workflow Principles

- **Local-first writes**: every curation action must persist to `wp_acx_sync_outbox` before attempting a network call. The operator sees the local result immediately; backend sync happens asynchronously.
- **Idempotent replay**: outbox operations must be safe to retry against the backend without producing duplicates or side effects. The backend's `CurationReplayRecord` keyed on `(tenant_id, idempotency_key)` is the deduplication surface.
- **Expected-base-version gating**: stale local mutations must be rejected cleanly by the backend (409 conflict) instead of partially applied. The plugin must surface these conflicts to the operator rather than silently retrying.
- **Bounded retry with dead-letter**: failed operations escalate to `failed` status after max attempts. The operator can inspect and manually retry or discard dead-letter entries.
- **Curation precedence**: conflict resolution always favors the operator's local curation. Backend 409s become local conflict records requiring human review, never silent overwrites.

## Terminology

- **Outbox operation**: a durable record in `wp_acx_sync_outbox` representing a local curation intent that must be pushed to the backend.
- **Drain**: the async process that reads pending outbox operations in FIFO order and dispatches them to the backend curation sync endpoint.
- **Dead-letter**: an outbox operation that has exhausted its retry budget and is marked `failed`.
- **Expected base version**: the backend version the plugin believes is current when making a mutation. If the backend has advanced past this version, it returns 409.
- **Acknowledged version**: the backend version returned on successful replay, recorded on the outbox operation for lineage.
- **Proxied mutation**: a curation mutation that currently calls the backend directly (synchronous HTTP) without outbox durability.

## Current State Analysis

- **Outbox infrastructure exists and works**: `OutboxWriter`, `OutboxDrain`, `OutboxDispatcher` are implemented with batch dispatch, retry, dead-letter, and conflict recording. Action Scheduler preferred, WP-Cron fallback.
- **Backend curation sync endpoint exists**: `POST /roster/curation/sync` accepts single and batch operations with idempotency keys. `CurationReplayRecord` stores cached results. Version conflict detection returns 409.
- **Only 2 of 9+ mutation types use the outbox**: `cluster_dismissed` and `cluster_undismissed` (in `ClusterMutationsController`). Person CRUD (`person_created`, `person_updated`, `person_deleted`) and person binding (`cluster_person_bound`, `cluster_person_unbound`) use the outbox via `class-api.php`.
- **Proxied mutations lack durability**: label rename (`PATCH clusters/{id}`), merge (`POST clusters/{id}/merge`), split (`POST clusters/{id}/split`), reassign (`POST clusters/reassign`), create-for-identity (`POST clusters/create-for-identity`), assign-outlier (`POST clusters/{id}/assign`), and revert-merge (`POST clusters/{id}/revert-merge`) are direct HTTP calls. A network failure loses the mutation.
- **Backend sync service handles only 6 operation types**: `person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`, `cluster_dismissed`, `cluster_undismissed`. Label, merge, split, reassign, and create operations have no sync handlers.
- **Sync state surfaces basic counts**: `pending_curation_operations`, `conflict_count`, `last_curation_acknowledged_at` are already in the REST response via `SyncStatusController`. But no queue depth trend, no dead-letter count, no per-operation status visibility.
- **OutboxWriter has no interface**: used directly as concrete class. No test seam for stubbing in unit tests.

## Proposed Solution

Extend the existing outbox and curation sync infrastructure in three layers:

1. **Plugin: move all proxied mutations to outbox-first pattern**. Each curation mutation writes local state + enqueues an outbox operation in a single transaction. The existing drain infrastructure handles dispatch. The operator sees immediate local state; backend sync is async.

2. **Backend: expand sync surface for state-only operations; delegate topology mutations to existing recognition endpoints**.
   - **State-only operation** (`cluster_label_updated`): add handler to `CurationSyncService` alongside existing bind/unbind/dismiss handlers. Label updates are pure state mutations with no side effects.
   - **Topology mutations** (`cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity`): these carry side effects (follow-up re-clustering jobs, suggestion refresh, representative pinning) that already live in the recognition cluster router. The outbox drain dispatches these to the existing recognition endpoints (`/clusters/{id}/merge`, `/clusters/{id}/split`, `/clusters/reassign`, `/clusters/create-for-identity`) instead of re-implementing logic in `CurationSyncService`. The drain must record the acknowledged version from the response and mark the outbox entry accordingly.

3. **Plugin: enhance sync state reporting**. Extend `wp_acx_sync_state` and `SyncStatusController` with dead-letter count and last failure timestamp. Expose enough metadata for the frontend to distinguish "all synced" from "N pending" from "N failed -- attention needed".

## Patterns to Follow

### Plugin: Outbox-First Mutation Pattern

```php
// In ClusterMutationsController::update_cluster_label()
// 1. Write local state in transaction
$this->begin_database_transaction();
$wpdb->update($table_clusters, ['label' => $label, 'updated_at' => $now], ['cluster_uuid' => $cluster_id]);
$wpdb->query($wpdb->prepare('UPDATE %i SET local_revision = local_revision + 1 WHERE cluster_uuid = %s', $table_clusters, $cluster_id));
$local_revision = (int) $wpdb->get_var($wpdb->prepare('SELECT local_revision FROM %i WHERE cluster_uuid = %s', $table_clusters, $cluster_id));

// 2. Enqueue outbox operation in same transaction
$this->enqueue_curation_operation('cluster_label_updated', $cluster_id, $cluster);
$this->commit_database_transaction();

// 3. Return local result immediately (synced: false, status: pending)
return rest_ensure_response(['cluster_id' => $cluster_id, 'label' => $label, 'synced' => false, 'status' => 'pending']);
```

### Backend: New Operation Type Handler

```python
# In CurationSyncService._apply()
# Add cluster_label_updated to CLUSTER_OPERATION_TYPES:
CLUSTER_OPERATION_TYPES = frozenset({
    "cluster_person_bound", "cluster_person_unbound",
    "cluster_dismissed", "cluster_undismissed",
    "cluster_label_updated",
})

# Handler for cluster_label_updated:
if operation_type == "cluster_label_updated":
    new_label = payload.get("label", "")
    cluster.label = new_label
    cluster.updated_at = func.now()
```

### Plugin: Topology Mutation Drain Dispatch

Topology mutations (`cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity`) are dispatched by the outbox drain to the existing recognition cluster router endpoints, not to `CurationSyncService`. The drain maps operation types to recognition endpoints:

```php
// In OutboxDispatcher -- topology operation routing:
$topology_routes = [
    'cluster_merged'               => ['POST', '/recognition/clusters/%s/merge'],
    'cluster_split'                => ['POST', '/recognition/clusters/%s/split'],
    'identity_reassigned'          => ['POST', '/recognition/clusters/reassign'],
    'cluster_created_for_identity' => ['POST', '/recognition/clusters/create-for-identity'],
];
// These endpoints already handle the business logic, side effects (follow-up jobs,
// suggestion refresh), and return the updated cluster version for acknowledgement.
```

### Backend: Expected-Base-Version Conflict Detection (existing)

```python
# Already implemented in CurationSyncService._apply():
if expected_base_version > 0 and expected_base_version < cluster_backend_version:
    return CurationSyncResult(
        status="conflict",
        conflict_code="version_conflict",
        backend_version=cluster_backend_version,
        machine_payload={"current_label": cluster.label, ...},
    )
```

### Plugin: Dead-Letter Reporting Extension

```php
// In SyncStateRepository::refresh_curation_metrics()
// Add failed operation count alongside pending count:
$failed_count = (int) $wpdb->get_var($wpdb->prepare(
    'SELECT COUNT(*) FROM %i WHERE tenant_id = %s AND status = %s',
    $this->outbox_table, $tenant_id, 'failed'
));
// Include in upsert to wp_acx_sync_state
```

## Functions to Change

### Plugin (WordPress)

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | update_cluster_label | Convert from direct backend proxy to local-write + outbox enqueue pattern. Remove synchronous HTTP call; write label locally in transaction, enqueue `cluster_label_updated` operation. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | merge_clusters | Convert from direct backend proxy to local-write + outbox. Apply merge locally (move members, update cluster state), enqueue `cluster_merged` operation for backend replay. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | split_cluster | Convert from direct backend proxy to local-write + outbox. Apply split locally (create new cluster, move designated members), enqueue `cluster_split` operation. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | reassign_cluster_identity | Convert from direct backend proxy to local-write + outbox. Apply reassign locally (move member row), enqueue `identity_reassigned` operation. Keep `mark_as_curated()` call. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | create_cluster_for_identity | Convert from direct backend proxy to local-write + outbox. Create cluster locally, move identity, enqueue `cluster_created_for_identity` operation. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | refresh_curation_metrics | Add `failed_curation_operations` count from outbox `status = 'failed'`. Add `last_curation_failed_at` from `MAX(last_attempted_at)` of failed operations. |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | schema | Add `failed_curation_operations` and `last_curation_failed_at` columns to `wp_acx_sync_state` CREATE TABLE. |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | get_sync_status | Include `failed_curation_operations` and `last_curation_failed_at` in REST response. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php` | interface | Extract `OutboxWriterInterface` for test seam. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php` | dispatch | Add topology operation routing: map `cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity` to their existing recognition cluster router endpoints. State-only operations continue to route to `/roster/curation/sync`. |

### Backend (Python)

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-description-service/roster/application/curation_sync_service.py` | _SUPPORTED_OPERATION_TYPES | Add `cluster_label_updated` to supported types. |
| `apps/prototype-description-service/roster/application/curation_sync_service.py` | _apply | Add handler branch for `cluster_label_updated`: load cluster, apply version conflict check, update `cluster.label` from `payload.label`. |

> **Note:** Topology mutations (`cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity`) are NOT added to `CurationSyncService`. They are dispatched by `OutboxDispatcher` directly to the existing recognition cluster router endpoints, which already own the business logic and side effects.

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php` | Existing drain infrastructure. No changes needed -- already handles batch dispatch, retry, dead-letter, and conflict recording for any operation type. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php` | Existing HTTP transport. Needs routing extension: topology operations dispatch to recognition cluster router endpoints; state-only operations dispatch to curation sync endpoint. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php` | Existing conflict recording. No changes needed -- already handles 409 responses from drain and writes conflict records. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Phase 2 conflict-aware projector. No changes needed for Phase 3. |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | Person CRUD + cluster assignment endpoints already use outbox pattern. Reference implementation for the pattern being extended to mutations controller. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Existing recognition endpoints for merge, split, reassign, create-for-identity, label update. Topology mutations are dispatched here by the outbox drain. |
| `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py` | Curation sync endpoint. Handles state-only operations (bind/unbind/dismiss/label). No changes needed. |
| `apps/prototype-description-service/db/models/identity.py` | `CurationReplayRecord` model for idempotency. No schema changes needed. |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Parent epic with Phase 3 exit criteria. |
| `docs/tasks/6.0/phase-2-curation-first-merge-contract-task-plan.md` | Phase 2 task plan -- prerequisite for Phase 3. Curation guards and conflict recording must be in place before mutations move to outbox-first. |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure)

- [x] `wp_acx_sync_outbox` table exists with correct schema (tenant_id, operation_type, entity_type, entity_key, idempotency_key, expected_base_version, local_revision, payload, status, attempts, acknowledged_version, etc).
- [x] `OutboxWriter` enqueues durable operations with UUID idempotency keys.
- [x] `OutboxDrain` processes pending operations in FIFO batches via Action Scheduler (WP-Cron fallback).
- [x] `OutboxDispatcher` builds request bodies and dispatches to `/roster/curation/sync` with batch support.
- [x] `ConflictRepository` records conflicts from 409 drain responses and projection conflicts.
- [x] `SyncStateRepository::refresh_curation_metrics()` counts pending operations and open conflicts.
- [x] `SyncStatusController` REST response includes `pending_curation_operations`, `conflict_count`, `last_curation_acknowledged_at`, `last_curation_conflict_at`.
- [x] Backend `POST /roster/curation/sync` endpoint accepts single and batch operations with idempotency.
- [x] Backend `CurationSyncService` handles `person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`, `cluster_dismissed`, `cluster_undismissed`.
- [x] Backend `CurationReplayRecord` provides idempotency deduplication per `(tenant_id, idempotency_key)`.
- [x] Backend expected-base-version conflict detection returns 409 with `conflict_code` and `machine_payload`.
- [x] Person CRUD and cluster person binding/unbinding already use outbox pattern in `class-api.php`.
- [x] Dismiss/undismiss already use outbox pattern in `ClusterMutationsController`.

## Phase 0: Scaffolding

- [x] Extract `OutboxWriterInterface` from `OutboxWriter` for testability. Add to `src/sovereign/sync/` interfaces.
- [ ] Add `failed_curation_operations INT UNSIGNED NOT NULL DEFAULT 0` column to `wp_acx_sync_state` in lifecycle manager.
- [ ] Add `last_curation_failed_at DATETIME NULL` column to `wp_acx_sync_state` in lifecycle manager.
- [x] Add backend operation type constants for new types: `cluster_label_updated`, `cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity`.
- [x] Create PHPUnit test scaffolding for outbox-first mutation tests with `@dataProvider` for each mutation type.
- [x] Create pytest test scaffolding for `cluster_label_updated` backend sync handler.
- [x] Verify scaffolds compile: `composer phpstan` and `make check` (backend).

## Phase 1: Plugin -- Outbox-First Label and Reassign Mutations

- [x] Convert `update_cluster_label()` to outbox-first: write label locally in transaction, enqueue `cluster_label_updated`, remove synchronous backend proxy call. Return `{synced: false, status: pending}`.
- [x] Convert `reassign_cluster_identity()` to outbox-first: write member reassignment locally in transaction, enqueue `identity_reassigned`, retain `mark_as_curated()` call, remove synchronous backend proxy call.
- [x] Update `enqueue_curation_operation()` in `ClusterMutationsController` to support new operation types with correct entity_type/entity_key/payload extraction.
- [x] Add PHPUnit tests: label mutation enqueues outbox operation with correct payload; reassign mutation enqueues with correct cluster and identity references; local state is written before outbox enqueue.

## Phase 2: Plugin -- Outbox-First Merge, Split, and Create Mutations

> **Compound operation contract:** Merge and split touch multiple clusters and member rows, but the outbox carries one `entity_key` and one `expected_base_version` per record. For merge: `entity_key` is the **source** cluster UUID, `expected_base_version` is the source cluster's version (the target is referenced in `payload.target_cluster_uuid`). For split: `entity_key` is the **original** cluster UUID, `expected_base_version` is the original cluster's version (the new cluster UUID is generated locally and carried in `payload.new_cluster_uuid`). The backend recognition endpoints already handle the multi-entity writes atomically; the outbox record only gates staleness of the primary entity.

- [ ] Convert `merge_clusters()` to outbox-first: apply merge locally (move source cluster members to target, mark source as dismissed, update identity counts), enqueue `cluster_merged` with `entity_key = source_cluster_uuid` and `payload = {target_cluster_uuid, ...}`.
- [ ] Convert `split_cluster()` to outbox-first: apply split locally (create new cluster, move designated members), enqueue `cluster_split` with `entity_key = original_cluster_uuid` and `payload = {new_cluster_uuid, identity_uuids}`.
- [ ] Convert `create_cluster_for_identity()` to outbox-first: create cluster locally, move identity member, enqueue `cluster_created_for_identity` with new cluster UUID and identity reference.
- [ ] Add PHPUnit tests: merge enqueues correct operation and updates both clusters locally; split creates new cluster and moves members; create-for-identity generates new cluster with correct membership.

## Phase 3: Backend -- Label Sync Handler + Topology Dispatch Routing

- [x] Add `cluster_label_updated` handler in `CurationSyncService._apply()`: load cluster by entity_key, apply version conflict check, update `cluster.label` from `payload.label`.
- [x] Add pytest coverage: label handler applies mutation correctly; version conflict returns 409; idempotency key prevents duplicate execution.
- [x] Add topology operation routing to `OutboxDispatcher`: map `cluster_merged` to `POST /recognition/clusters/{source_id}/merge`, `cluster_split` to `POST /recognition/clusters/{id}/split`, `identity_reassigned` to `POST /recognition/clusters/reassign`, `cluster_created_for_identity` to `POST /recognition/clusters/create-for-identity`.
- [x] Add PHPUnit tests for `OutboxDispatcher` routing: state-only operations route to `/roster/curation/sync`; topology operations route to correct recognition endpoints.
- [ ] Add integration test: topology operation (merge) enqueued, drain dispatches to recognition endpoint, response acknowledged, outbox status transitions correctly.

## Phase 4: Sync State Reporting Enhancements

- [ ] Extend `SyncStateRepository::refresh_curation_metrics()` to count `failed` outbox operations and extract `MAX(last_attempted_at)` for failed operations.
- [ ] Upsert `failed_curation_operations` and `last_curation_failed_at` to `wp_acx_sync_state`.
- [ ] Include `failed_curation_operations` and `last_curation_failed_at` in `SyncStatusController` REST response.
- [ ] Add PHPUnit test: metrics refresh correctly counts pending, failed, and conflict tallies after mixed outbox states.

## Phase 5: Tests

- [x] Unit tests for each converted mutation in `ClusterMutationsController`: correct local state written, correct outbox operation enqueued, transaction atomicity preserved, no direct HTTP calls to backend.
- [x] Unit tests for `cluster_label_updated` backend sync handler: mutation applies correctly, version conflict detection works, idempotency key caching works.
- [x] Unit tests for `OutboxDispatcher` routing: state-only operations dispatch to curation sync; topology operations dispatch to correct recognition endpoints.
- [ ] Integration test: full cycle -- plugin enqueues label mutation, drain dispatches to curation sync endpoint, backend applies and returns acknowledged, outbox status transitions to acknowledged, sync state metrics updated.
- [ ] Integration test: topology cycle -- plugin enqueues merge mutation, drain dispatches to recognition cluster merge endpoint, response acknowledged, outbox status transitions correctly.
- [ ] Integration test: conflict cycle -- plugin enqueues stale mutation, backend returns 409, drain records conflict in `wp_acx_sync_conflicts`, sync state reflects new conflict count.
- [ ] Integration test: dead-letter cycle -- backend repeatedly fails (5xx), drain retries up to max_attempts, operation transitions to `failed`, sync state reflects failed count.
- [ ] All PHPUnit, PHPStan, pytest, and ruff checks pass.

## Stretch Goals

- [ ] Manual retry UI for dead-letter operations in admin -- likely Phase 4 (Offline UX) scope.
- [ ] Outbox operation detail view showing payload, attempts, and error history -- likely Phase 4 scope.
- [ ] Revert-merge operation via outbox (currently proxied, complex undo semantics) -- defer until merge-via-outbox is stable.
- [ ] Assign-outlier and pin-representative via outbox -- low-frequency operations, can remain proxied until needed.

## Success Criteria

- [ ] Phase 3 core mutations (label, merge, split, reassign, create-for-identity) are persisted to `wp_acx_sync_outbox` before any network call, joining the already-outbox-backed mutations (dismiss, undismiss, person CRUD, person bind/unbind).
- [ ] Operators see local mutation results immediately regardless of backend connectivity.
- [ ] When connectivity resumes, queued mutations replay exactly once: state-only operations via the idempotent curation sync endpoint; topology operations via the existing recognition cluster router endpoints.
- [ ] Stale mutations (expected_base_version behind backend) produce 409 conflicts that are recorded in `wp_acx_sync_conflicts` for operator review.
- [ ] Dead-letter operations (max retries exhausted) are marked `failed` and surfaced in sync status.
- [ ] `SyncStatusController` REST response includes pending queue size, failed count, and last acknowledgement/failure timestamps.
- [ ] All PHPUnit, PHPStan, pytest, and ruff checks pass.

> **Not in scope:** Revert-merge and assign-outlier remain proxied (see Stretch Goals). These are explicitly deferred and do not block Phase 3 completion.
