# Phase 3: Minimal Durable Sync Replay

## Problem Statement

Curation mutations fall into two failure categories today:

1. **Remaining backend-first curation actions (split, revert-merge, and backend-only assign-outlier)**: these still lack a durable plugin intent record before backend execution. If the backend is offline, the operator sees an error or has no local retry surface and the curation action is lost.
2. **Durable local-intent mutations (label rename, merge, reassign, create-for-identity, dismiss/undismiss, person CRUD, person bind/unbind)**: these already persist local intent before backend acknowledgement. If the backend is offline, the mutation remains durable locally and can replay or reconcile later.

The goal of this phase is to move the remaining backend-first curation actions to durable local intent so that all currently supported curation mutations survive backend outages. Most of those actions will use the existing outbox-first path; split uses a dedicated topology-command record because the backend owns the final partition result. The operator should also have visibility into which local changes are queued, failed, conflicted, or safely acknowledged.

## Workflow Principles

- **Durable local intent first**: every curation action must persist locally before attempting a network call. Deterministic mutations in this phase persist to `wp_acx_sync_outbox`; `cluster_split` persists to the dedicated topology-command journal defined below. The operator sees durable queued intent immediately; backend sync happens asynchronously.
- **Idempotent replay**: outbox operations must be safe to retry against the backend without producing duplicates or side effects. The backend's `CurationReplayRecord` keyed on `(tenant_id, idempotency_key)` is the deduplication surface.
- **Expected-base-version gating**: stale local mutations must be rejected cleanly by the backend (409 conflict) instead of partially applied. The plugin must surface these conflicts to the operator rather than silently retrying.
- **Bounded retry with dead-letter**: failed operations escalate to `failed` status after max attempts. The operator can inspect and manually retry or discard dead-letter entries.
- **Curation precedence**: conflict resolution always favors the operator's local curation. Backend 409s become local conflict records requiring human review, never silent overwrites.

## Terminology

- **Outbox operation**: a durable record in `wp_acx_sync_outbox` representing a local curation intent that must be pushed to the backend.
- **Drain**: the async dispatch process for a durable local intent queue. In this phase there are two drain planes: the outbox drain for replay-plane mutations and the topology-command drain for split commands.
- **Dead-letter**: an outbox operation that has exhausted its retry budget and is marked `failed`.
- **Expected base version**: the backend version the plugin believes is current when making a mutation. If the backend has advanced past this version, it returns 409.
- **Acknowledged version**: the backend version returned on successful replay, recorded on the outbox operation for lineage.
- **Proxied mutation**: a curation mutation that currently calls the backend directly (synchronous HTTP) without outbox durability.
- **Topology command**: a durable local command record for a backend-authored topology operation whose final shape cannot be safely projected locally before execution.

## Current State Analysis

- **Outbox infrastructure exists and works**: `OutboxWriter`, `OutboxDrain`, `OutboxDispatcher` are implemented with batch dispatch, retry, dead-letter, and conflict recording. Action Scheduler preferred, WP-Cron fallback.
- **Backend curation sync endpoint exists**: `POST /roster/curation/sync` accepts single and batch operations with idempotency keys. `CurationReplayRecord` stores cached results. Version conflict detection returns 409.
- **Several mutation types already use durable local intent**: `cluster_dismissed`, `cluster_undismissed`, `cluster_label_updated`, `identity_reassigned`, `cluster_merged`, and `cluster_created_for_identity` are already durable in `ClusterMutationsController`. Person CRUD (`person_created`, `person_updated`, `person_deleted`) and person binding (`cluster_person_bound`, `cluster_person_unbound`) use durable replay via `class-api.php`.
- **Only a reduced set still lacks durable plugin intent**: split (`POST clusters/{id}/split`) and revert-merge (`POST clusters/{id}/revert-merge`) are still synchronous plugin-to-backend calls; assign-outlier exists only as a backend capability today and has no plugin durable mutation path yet. A network failure still loses those actions unless this plan changes their durability path.
- **Backend sync service now handles state-only label replay too**: `person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`, `cluster_dismissed`, `cluster_undismissed`, and `cluster_label_updated` are in `CurationSyncService`. Merge, split, reassign, create-for-identity, revert-merge, and assign-outlier remain outside that service because their business logic lives in the recognition boundary.
- **Sync state surfaces baseline durability counts**: `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, `last_curation_acknowledged_at`, and `last_curation_failed_at` are already in the REST response via `SyncStatusController`. What is still missing is richer per-operation visibility, queue trend/history, and split-command-specific status once the topology-command plane exists.
- **OutboxWriter interface seam now exists**: `OutboxWriterInterface` has already been extracted, so the remaining work is to keep using that seam consistently as Phase 3 broadens mutation coverage.

## Proposed Solution

Extend the existing outbox and curation sync infrastructure in three layers:

1. **Plugin: move proxied mutations to durable local intent first**. Deterministic curation mutations write local state + enqueue an outbox operation in a single transaction. `cluster_split` writes a topology-command record instead of mutating local projection rows. The operator sees immediate queued intent; backend sync is async.

2. **Backend: expand sync surface for state-only operations; delegate topology mutations to existing recognition endpoints**.
   - **State-only operation** (`cluster_label_updated`): add handler to `CurationSyncService` alongside existing bind/unbind/dismiss handlers. Label updates are pure state mutations with no side effects.
   - **Replay-plane topology mutations** (`cluster_merged`, `identity_reassigned`, `cluster_created_for_identity`, `revert_merge_cluster`, `assign_outlier_to_cluster`): these carry side effects (follow-up re-clustering jobs, suggestion refresh, representative pinning) that already live in the recognition boundary. The outbox drain dispatches merge, reassign, and create-for-identity to active replay-ready recognition endpoints (`/clusters/{id}/merge`, `/clusters/reassign`, `/clusters/create-for-identity`) instead of re-implementing logic in `CurationSyncService`. `revert_merge_cluster` remains pending backend endpoint/contract work in this phase; the plugin currently proxies `/recognition/clusters/revert-merge`, but the recognition router does not expose that replay endpoint yet. `assign_outlier_to_cluster` has an active manual route (`/clusters/{id}/assign`), but it still needs replay-contract alignment (`idempotency_key`, replay cache load/store, and acknowledged-version response semantics) before the plan can treat it as exact-once replay-ready.
   - **Split topology command** (`cluster_split`): this is carved out of the outbox plane. It persists to the dedicated topology-command journal and dispatches to the split topology-command endpoint because the backend authors the final partition result.

3. **Plugin: build on the delivered sync status baseline**. The failed-count and failure-timestamp fields already exist in `wp_acx_sync_state` and `SyncStatusController`. This phase should extend that baseline only where needed for richer per-operation visibility and split topology-command status.

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

### Plugin: Replay-Plane Topology Mutation Drain Dispatch

Replay-plane topology mutations are dispatched by the outbox drain to recognition endpoints, not to `CurationSyncService`. Merge, reassign, and create-for-identity already have replay-ready recognition router targets. `revert_merge_cluster` is still pending explicit backend route/contract work in this phase, and `assign_outlier_to_cluster` still needs replay-contract alignment before it can satisfy the plan's exact-once guarantees. The intended drain mapping is:

```php
// In OutboxDispatcher -- topology operation routing:
$topology_routes = [
    'cluster_merged'               => ['POST', '/recognition/clusters/%s/merge'],
    'identity_reassigned'          => ['POST', '/recognition/clusters/reassign'],
    'cluster_created_for_identity' => ['POST', '/recognition/clusters/create-for-identity'],
    'revert_merge_cluster'         => ['POST', '/recognition/clusters/revert-merge'],
    'assign_outlier_to_cluster'    => ['POST', '/recognition/clusters/%s/assign'],
];
// Merge/reassign/create-for-identity already handle the business logic and side effects for replay.
// This phase must add the missing revert-merge recognition endpoint, align assign-outlier to the
// replay contract (`idempotency_key`, replay cache load/store), and align replay-plane topology
// responses to return `backend_version` (or an equivalent acknowledged version field) so
// OutboxDispatcher can persist acknowledgement/version state correctly.
```

### Plugin: Split Topology Command Dispatch

`cluster_split` is not dispatched by `OutboxDispatcher`. It is drained by the dedicated topology-command surface introduced in the addendum:

```php
// In split topology-command drain:
$split_command_endpoint = ['POST', '/recognition/topology-commands/split'];
// The command row, result_json, and reconciliation status live in wp_acx_topology_commands,
// not in wp_acx_sync_outbox.
// Hard cutover also removes the legacy cluster_split route from OutboxDispatcher::TOPOLOGY_ROUTES
// so split no longer has two competing dispatch surfaces.
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

| File                                                                                       | Line                        | Change                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------ | --------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | update_cluster_label        | Convert from direct backend proxy to local-write + outbox enqueue pattern. Remove synchronous HTTP call; write label locally in transaction, enqueue `cluster_label_updated` operation.                                                                                                                                                                                    |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | merge_cluster               | Convert from direct backend proxy to local-write + outbox. Apply merge locally (move members, update cluster state), enqueue `cluster_merged` operation for backend replay.                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | split_cluster               | Convert from direct backend proxy to durable topology command. Persist split intent locally, do not mutate projection rows during request handling, and return pending command state.                                                                                                                                                                                      |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | reassign_cluster_identity   | Convert from direct backend proxy to local-write + outbox. Apply reassign locally (move member row), enqueue `identity_reassigned` operation. Keep `mark_as_curated()` call.                                                                                                                                                                                               |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | create_cluster_for_identity | Convert from direct backend proxy to local-write + outbox. Create cluster locally, move identity, enqueue `cluster_created_for_identity` operation.                                                                                                                                                                                                                        |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | revert_merge_cluster        | Convert from direct backend proxy to durable local intent. Preserve the existing revert-merge payload, enqueue a replayable operation, and return pending local intent instead of synchronous backend success.                                                                                                                                                             |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`             | assign_outlier_to_cluster   | Add a plugin mutation path for assign-outlier and make it durable local intent instead of a direct backend-only action.                                                                                                                                                                                                                                                    |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | refresh_curation_metrics    | Add `failed_curation_operations` count from outbox `status = 'failed'`. Add `last_curation_failed_at` from `MAX(last_attempted_at)` of failed operations.                                                                                                                                                                                                                  |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                   | schema                      | Add `failed_curation_operations` and `last_curation_failed_at` columns to `wp_acx_sync_state` CREATE TABLE.                                                                                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`                   | get_sync_status             | Include `failed_curation_operations` and `last_curation_failed_at` in REST response.                                                                                                                                                                                                                                                                                       |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`                 | interface                   | Extract `OutboxWriterInterface` for test seam.                                                                                                                                                                                                                                                                                                                             |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`             | dispatch                    | Extend topology operation routing from the currently landed replay-plane mutations (`cluster_merged`, `identity_reassigned`, `cluster_created_for_identity`) to also cover `revert_merge_cluster` and `assign_outlier_to_cluster`. State-only operations continue to route to `/roster/curation/sync`. Coordinate shared sequencing with the split topology-command plane. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                  | sequencing                  | Enforce cross-plane ordering between replay-plane outbox operations and split topology commands targeting the same cluster lineage.                                                                                                                                                                                                                                        |
| `apps/prototype-wp-alt-context/src/sovereign/sync/`                                        | topology command support    | Add split topology-command repository/drain support around `wp_acx_topology_commands`, durable result storage, and reconciliation tracking.                                                                                                                                                                                                                                |

### Backend (Python)

| File                                                                                         | Line                           | Change                                                                                                                                                                                                                                                      |
| -------------------------------------------------------------------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-description-service/roster/application/curation_sync_service.py`             | \_SUPPORTED_OPERATION_TYPES    | Add `cluster_label_updated` to supported types.                                                                                                                                                                                                             |
| `apps/prototype-description-service/roster/application/curation_sync_service.py`             | \_apply                        | Add handler branch for `cluster_label_updated`: load cluster, apply version conflict check, update `cluster.label` from `payload.label`.                                                                                                                    |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/`            | split topology command route   | Add the dedicated `POST /recognition/topology-commands/split` endpoint and any optional command-status lookup route used by the split command plane.                                                                                                        |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | revert/assign replay endpoints | Add the missing replay endpoint/contract for `revert-merge`, and align `assign-outlier` to the replay contract (`idempotency_key`, replay cache load/store, acknowledged-version response fields) before the plugin treats it as durable exact-once replay. |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/`            | request/response contracts     | Add request and response schemas for split topology-command execution, including `expected_base_version`, `idempotency_key`, conflict payload, and typed result metadata.                                                                                   |
| `apps/prototype-description-service/recognition/application/orchestration/`                  | split command orchestration    | Add or extend the split orchestration/service layer so the topology-command route reuses the existing partition algorithm while returning durable typed command results.                                                                                    |
| `apps/prototype-description-service/recognition/application/persistence/`                    | command/result persistence     | Add the persistence path for split command acknowledgement/result state if backend-side durable command lookup is required by the final route contract.                                                                                                     |

> **Note:** Replay-plane topology mutations (`cluster_merged`, `identity_reassigned`, `cluster_created_for_identity`, `revert_merge_cluster`, `assign_outlier_to_cluster`) are NOT added to `CurationSyncService`; they remain recognition-boundary work. However, only merge/reassign/create-for-identity are currently replay-ready router targets. Phase 3 still needs backend contract work before `revert_merge_cluster` and `assign_outlier_to_cluster` can be treated as exact-once replay operations. `cluster_split` is also excluded from `CurationSyncService`, but it is no longer an `OutboxDispatcher` concern: it moves to the dedicated split topology-command surface and endpoint.

## Related Files

| File                                                                                         | Note                                                                                                                                                                                                                                                                                                                                                  |
| -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                    | Existing drain infrastructure. Needs shared sequencing coordination with split topology commands so replay-plane mutations cannot reorder across cluster lineage.                                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`               | Existing HTTP transport. Already routes the landed replay-plane topology operations (`cluster_merged`, `identity_reassigned`, `cluster_created_for_identity`); still needs routing extension for `revert_merge_cluster` and `assign_outlier_to_cluster`, and must participate in the shared sequencing contract with split topology-command dispatch. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/`                                          | New split topology-command repository/drain surface. Owns `wp_acx_topology_commands`, split dispatch, durable result storage, and reconciliation state.                                                                                                                                                                                               |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`             | Existing conflict recording. No changes needed -- already handles 409 responses from drain and writes conflict records.                                                                                                                                                                                                                               |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`              | Phase 2 conflict-aware projector. No changes needed for Phase 3.                                                                                                                                                                                                                                                                                      |
| `apps/prototype-wp-alt-context/src/api/class-api.php`                                        | Person CRUD + cluster assignment endpoints already use outbox pattern. Reference implementation for the pattern being extended to mutations controller.                                                                                                                                                                                               |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Existing recognition endpoints for merge, reassign, create-for-identity, assign-outlier, and label update. Phase 3 still needs to add the revert-merge replay endpoint and align assign-outlier plus the broader return-version contract here before outbox replay can depend on them.                                                                |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/`            | New split topology-command route surface. Owns the dedicated split command endpoint and any optional command-status lookup path required by the addendum.                                                                                                                                                                                             |
| `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py`       | Curation sync endpoint. Handles state-only operations (bind/unbind/dismiss/label). No changes needed.                                                                                                                                                                                                                                                 |
| `apps/prototype-description-service/db/models/identity.py`                                   | `CurationReplayRecord` model for idempotency. No schema changes needed.                                                                                                                                                                                                                                                                               |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md`          | Parent epic with Phase 3 exit criteria.                                                                                                                                                                                                                                                                                                               |
| `docs/tasks/6.0/phase-2-curation-first-merge-contract-task-plan.md`                          | Phase 2 task plan -- prerequisite for Phase 3. Curation guards and conflict recording must be in place before mutations move to outbox-first.                                                                                                                                                                                                         |

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
- [x] Backend `CurationSyncService` handles `person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`, `cluster_dismissed`, `cluster_undismissed`, and `cluster_label_updated`.
- [x] Backend `CurationReplayRecord` provides idempotency deduplication per `(tenant_id, idempotency_key)`.
- [x] Backend expected-base-version conflict detection returns 409 with `conflict_code` and `machine_payload`.
- [x] Person CRUD and cluster person binding/unbinding already use outbox pattern in `class-api.php`.
- [x] Dismiss/undismiss already use outbox pattern in `ClusterMutationsController`.

## Phase 0: Scaffolding

- [x] Extract `OutboxWriterInterface` from `OutboxWriter` for testability. Add to `src/sovereign/sync/` interfaces.
- [x] Add `failed_curation_operations INT UNSIGNED NOT NULL DEFAULT 0` column to `wp_acx_sync_state` in lifecycle manager.
- [x] Add `last_curation_failed_at DATETIME NULL` column to `wp_acx_sync_state` in lifecycle manager.
- [x] Add backend operation type constants for new types: `cluster_label_updated`, `cluster_merged`, `cluster_split`, `identity_reassigned`, `cluster_created_for_identity`.
- [x] Create PHPUnit test scaffolding for outbox-first mutation tests with `@dataProvider` for each mutation type.
- [x] Create pytest test scaffolding for `cluster_label_updated` backend sync handler.
- [x] Verify scaffolds compile: `composer phpstan` and `make check` (backend).

## Phase 1: Plugin -- Outbox-First Label and Reassign Mutations

- [x] Convert `update_cluster_label()` to outbox-first: write label locally in transaction, enqueue `cluster_label_updated`, remove synchronous backend proxy call. Return `{synced: false, status: pending}`.
- [x] Convert `reassign_cluster_identity()` to outbox-first: write member reassignment locally in transaction, enqueue `identity_reassigned`, retain `mark_as_curated()` call, remove synchronous backend proxy call.
- [x] Update `enqueue_curation_operation()` in `ClusterMutationsController` to support new operation types with correct entity_type/entity_key/payload extraction.
- [x] Add PHPUnit tests: label mutation enqueues outbox operation with correct payload; reassign mutation enqueues with correct cluster and identity references; local state is written before outbox enqueue.

## Phase 2: Plugin -- Durable Merge, Split, Create, Revert-Merge, and Assign-Outlier Mutations

> **Compound operation contract:** Merge touches multiple clusters and member rows, but the outbox carries one `entity_key` and one `expected_base_version` per record. For merge: `entity_key` is the **source** cluster UUID, `expected_base_version` is the source cluster's version (the target is referenced in `payload.target_cluster_uuid`). For `revert_merge_cluster`: `entity_key` is the **target/current merged** cluster UUID being reverted, `expected_base_version` is that cluster's version at enqueue time, and `payload` carries the moved identity IDs plus any source-label metadata needed to rebuild the prior cluster. For `assign_outlier_to_cluster`: `entity_key` is the **target** cluster UUID receiving the outlier, `expected_base_version` is that target cluster's version at enqueue time, and `payload` carries the outlier/member identity references required by the recognition route. For all replay-plane topology operations, the outbox `idempotency_key` remains the backend dedupe key and the backend contract must return either acknowledged `{backend_version}` or conflict `{backend_version, conflict_code}` payloads. Split is not modeled as an outbox replay row in this phase; it uses the dedicated topology-command plane defined in the addendum because the backend authors the final partition result.

- [x] Convert `merge_cluster()` to outbox-first: apply merge locally (move source cluster members to target, mark source as dismissed, update identity counts), enqueue `cluster_merged` with `entity_key = source_cluster_uuid` and `payload = {target_cluster_uuid, ...}`.
- [ ] Convert `split_cluster()` to durable topology command: persist split intent locally without mutating projection rows, dispatch through the split topology-command plane, and reconcile projection only after backend-authored result arrives.
      Phase 2 progress:
  - [x] Plugin persists durable split intent in `wp_acx_topology_commands` and no longer routes split through `OutboxDispatcher`.
  - [x] Backend exposes the first `POST /recognition/topology-commands/split` execution surface with typed result + idempotency replay.
  - [ ] Dedicated topology-command drain, durable result persistence on the plugin side, and post-ack reconciliation are still pending.
- [x] Convert `create_cluster_for_identity()` to outbox-first: create cluster locally, move identity member, enqueue `cluster_created_for_identity` with a plugin-supplied cluster UUID that the backend now honors during replay.
- [ ] Convert `revert_merge_cluster()` to durable local intent: enqueue replayable revert-merge intent instead of proxying synchronously, and return pending local status.
- [ ] Add plugin support for assign-outlier durable intent: add the missing mutation path, enqueue replayable assign-outlier intent, and return pending local status.
- [ ] Add PHPUnit tests: merge enqueues correct operation and updates both clusters locally; split writes durable topology-command intent without local member movement; create-for-identity generates new cluster with correct membership; revert-merge and assign-outlier persist durable intent instead of proxying.

## Phase 3: Backend -- Label Sync Handler + Topology Dispatch Routing

- [x] Add `cluster_label_updated` handler in `CurationSyncService._apply()`: load cluster by entity_key, apply version conflict check, update `cluster.label` from `payload.label`.
- [x] Add pytest coverage: label handler applies mutation correctly; version conflict returns 409; idempotency key prevents duplicate execution.
- [x] Add topology operation routing to `OutboxDispatcher` for the currently landed replay-plane mutations: map `cluster_merged`, `identity_reassigned`, and `cluster_created_for_identity` to their recognition endpoints and include idempotency keys for backend-side replay deduplication.
- [ ] Add or align the missing replay-plane backend contract for `revert_merge_cluster` and `assign_outlier_to_cluster`: add the missing revert-merge endpoint, add assign-outlier `idempotency_key` + replay cache load/store, and ensure replay-plane topology responses return `backend_version` (or equivalent) so outbox acknowledgements can persist version lineage correctly.
- [ ] Extend replay-plane topology routing to include durable `revert-merge` and `assign-outlier` dispatch once those plugin mutation paths exist.
- [x] Add PHPUnit tests for `OutboxDispatcher` routing: state-only operations route to `/roster/curation/sync`; the currently landed replay-plane topology mutations route to the correct recognition endpoints.
- [ ] Add integration test: topology operation (merge) enqueued, drain dispatches to recognition endpoint, response acknowledged, outbox status transitions correctly.
- [ ] Add integration test: split topology command queues locally, dispatches through the split command plane, stores durable result metadata, and reconciles projection without outbox replay semantics.
- [ ] Add integration test: revert-merge and assign-outlier durable intents dispatch to their recognition endpoints and transition to acknowledged/conflict/failed states correctly.

## Phase 4: Sync State Reporting Enhancements

- [x] Extend `SyncStateRepository::refresh_curation_metrics()` to count `failed` outbox operations and extract `MAX(last_attempted_at)` for failed operations.
- [x] Upsert `failed_curation_operations` and `last_curation_failed_at` to `wp_acx_sync_state`.
- [x] Include `failed_curation_operations` and `last_curation_failed_at` in `SyncStatusController` REST response.
- [ ] Add PHPUnit test: metrics refresh correctly counts pending, failed, and conflict tallies after mixed outbox states.

## Phase 5: Tests

- [x] Unit tests for the currently converted `ClusterMutationsController` mutations: correct local state written, correct outbox operation enqueued, transaction atomicity preserved, no direct HTTP calls to backend.
- [x] Unit tests for `cluster_label_updated` backend sync handler: mutation applies correctly, version conflict detection works, idempotency key caching works.
- [x] Unit tests for `OutboxDispatcher` routing: state-only operations dispatch to curation sync; the currently landed replay-plane topology mutations dispatch to the correct recognition endpoints.
- [ ] Unit tests for newly in-scope replay-plane mutations once implemented: `revert_merge_cluster` and `assign_outlier_to_cluster` dispatch through `OutboxDispatcher` without synchronous backend proxying.
- [ ] Integration test: full cycle -- plugin enqueues label mutation, drain dispatches to curation sync endpoint, backend applies and returns acknowledged, outbox status transitions to acknowledged, sync state metrics updated.
- [ ] Integration test: topology cycle -- plugin enqueues merge mutation, drain dispatches to recognition cluster merge endpoint, response acknowledged, outbox status transitions correctly.
- [ ] Integration test: split cycle -- plugin enqueues split topology command, split drain dispatches to the split command endpoint, durable result metadata is stored, and local reconciliation completes.
- [ ] Integration test: conflict cycle -- plugin enqueues stale mutation, backend returns 409, drain records conflict in `wp_acx_sync_conflicts`, sync state reflects new conflict count.
- [ ] Integration test: dead-letter cycle -- backend repeatedly fails (5xx), drain retries up to max_attempts, operation transitions to `failed`, sync state reflects failed count.
- [ ] All PHPUnit, PHPStan, pytest, and ruff checks pass.

## Stretch Goals

- [ ] Manual retry UI for dead-letter operations in admin -- likely Phase 4 (Offline UX) scope.
- [ ] Outbox operation detail view showing payload, attempts, and error history -- likely Phase 4 scope.
- [ ] Pin-representative via durable replay once the broader low-frequency mutation surface is prioritized.

## Success Criteria

- [ ] Phase 3 core mutations use durable local intent before any network call: label, merge, reassign, create-for-identity, revert-merge, and assign-outlier persist through the replay plane; split persists to the dedicated topology-command journal; dismiss, undismiss, person CRUD, and person bind/unbind remain on the existing outbox path.
- [ ] Operators see immediate local results for replay-plane mutations and immediate queued intent/status for split topology commands regardless of backend connectivity.
- [ ] When connectivity resumes, queued mutations replay exactly once: state-only operations via the idempotent curation sync endpoint; merge/reassign/create/revert-merge/assign-outlier topology mutations via the recognition boundary; split via the dedicated topology-command endpoint.
- [ ] Stale mutations (expected_base_version behind backend) produce 409 conflicts that are recorded in `wp_acx_sync_conflicts` for operator review.
- [ ] Dead-letter operations (max retries exhausted) are marked `failed` and surfaced in sync status.
- [ ] `SyncStatusController` REST response includes pending queue size, failed count, and last acknowledgement/failure timestamps.
- [ ] All PHPUnit, PHPStan, pytest, and ruff checks pass.

> **Not in scope:** Pin-representative remains outside this phase. Revert-merge and assign-outlier are intentionally kept in core scope so the remaining backend-first mutation set is actually closed out.

## Phase 2 Blocker Resolution Addendum: Split Partition Ownership

### Why the Current Split Item Blocks

The current Phase 2 checklist line for `split_cluster()` assumes the plugin can deterministically choose moved members, create replacement clusters, and apply the resulting topology locally before replay. That assumption is wrong.

`split_cluster()` is not a deterministic local mutation. It is a backend-owned topology command:

- The recognition backend owns partitioning inputs and execution (`n_clusters`, `anchor_identity_id`, `split_mode`).
- The backend decides the final topology only after clustering logic runs.
- The backend may create one or more new clusters and define the final member assignment.
- The plugin cannot safely predict the final member movement offline without re-implementing backend clustering behavior and risking projection drift.

This is not just a split-specific inconvenience. It exposes a deeper architectural mismatch: the current durable replay model assumes all curation writes can be represented as local state mutations first and replayed later. That assumption does not hold for backend-authoritative topology changes.

### Decision

For `cluster_split`, stop modeling the operation as a replayable local mutation. Model it as a **durable topology command** with a typed backend result.

This addendum intentionally replaces the previous “outbox row + replay + projection refresh” compromise. The correct architecture is:

- The plugin owns durable operator intent.
- The backend owns topology execution and final topology shape.
- WordPress projection tables remain read models, not writable topology truth.
- UI immediacy comes from command state overlays, not from prematurely mutating projected cluster/member rows.

### Phase Scope Override

This addendum intentionally introduces a second durability plane for one operation class in this phase.

- **State replay plane**: existing `wp_acx_sync_outbox` for deterministic local-first mutations.
- **Topology command plane**: new `wp_acx_topology_commands` for backend-authored split execution.

That split is deliberate, not accidental:

- `label`, `dismiss`, `undismiss`, `reassign`, `merge`, `create-for-identity`, `revert-merge`, and `assign-outlier` remain in the replay/outbox model already defined in the main Phase 3 plan.
- `split` is removed from the replay/outbox model and redefined as a topology command because its final topology is backend-authored.
- This addendum therefore supersedes the split-specific parts of the main plan. It does not silently change the durability surface for the other operations in this phase.

### Architecture Change

Introduce an explicit split command model instead of forcing `cluster_split` through the generic curation replay abstraction.

#### 1. Projection is read-only for split command execution

For `cluster_split` command execution specifically, WordPress must stop directly mutating:

- `wp_acx_clusters`
- `wp_acx_identity_members`

during request handling.

Those tables are projections of backend topology. They may still be updated by:

- snapshot projection
- explicit backend command result application
- repair / reconciliation flows

They must not be treated as the first-write source of truth for split.

This read-only rule is intentionally narrow:

- It applies to `cluster_split` because the backend authors the final partition.
- It does not broaden Phase 3 scope to move `merge`, `reassign`, or `create-for-identity` off the replay plane.
- Other topology operations in this phase keep the ownership model already defined in the main plan unless and until a later phase explicitly migrates them.

#### 2. Topology commands become a separate durable surface

Do not store split in `wp_acx_sync_outbox` as if it were another replayable local state mutation.

Add a dedicated table for backend-owned topology commands, for example:

- `wp_acx_topology_commands`

Suggested columns:

- `id`
- `tenant_id`
- `command_type`
- `entity_key`
- `payload_json`
- `idempotency_key`
- `expected_base_version`
- `status`
  Values: `pending`, `dispatched`, `applied`, `reconciled`, `failed`, `conflict`
- `backend_command_id` nullable
- `result_json` nullable
- `projection_reconciled_at` nullable
- `attempts`
- `last_error_code`
- `last_error_message`
- `created_at`, `updated_at`, `last_attempted_at`, `acknowledged_at`

This is the durable local intent journal for topology commands.

#### 3. Backend exposes typed split command execution/result

Split should be invoked and tracked as a first-class topology command, not as a curation replay payload pretending to be a local state mutation.

Preferred backend surface:

- `POST /recognition/topology-commands/split`
- optional `GET /recognition/topology-commands/{command_id}`

Required request fields:

- `tenant_id`
- `cluster_id`
- `n_clusters`
- `anchor_identity_id` optional
- `split_mode` optional
- `idempotency_key`
- `expected_base_version`

Optional:

- `desired_cluster_ids`, but only for fixed-count splits where `n_clusters >= 2`

Result payload should be typed and durable:

- `command_id`
- `status`
- `original_cluster_id`
- `new_cluster_ids`
- `member_delta`
  - `source_cluster_id`
  - `remaining_identity_ids`
  - `created_clusters`
    - each entry includes:
      - `cluster_id`
      - `identity_ids`
- `moved_counts`
- `affected_cluster_ids`
- `result_snapshot_version` or equivalent lineage/version marker

Direct local delta apply is only the primary completion path when `member_delta` is present and complete enough to deterministically rewrite affected projection rows. If the backend returns only aggregate metadata such as counts, targeted snapshot reconciliation becomes the primary completion path for that command.

Conflict behavior must also be explicit:

- backend compares `expected_base_version` against the current source cluster version before executing split
- stale commands return `409 Conflict`
- the conflict payload must include:
  - `conflict_code`
  - `backend_version`
  - `machine_payload`
  - `source_cluster_id`
- plugin records that response as a split conflict through the same durable operator-conflict path used elsewhere in this phase

#### 4. Cross-plane ordering contract

The two durability planes must not race on the same cluster lineage.

- All drainable operations that target the same source cluster lineage must share one sequencing key: the source `cluster_uuid`.
- A pending or dispatched `cluster_split` blocks later replay-plane topology operations on that same sequencing key until the split command reaches `reconciled`, `failed`, or `conflict`.
- A pending replay-plane topology mutation on that same sequencing key blocks split dispatch until the earlier operation is no longer pending.
- If an operation affects multiple clusters, the dispatcher must conservatively lock the full affected key set before dispatch.
- The implementation may use a shared scheduler lane, lease table, or dependency graph, but the ordering rule must be consistent across both planes and visible in tests.

#### 5. Hard cutover sequencing

Implementation ownership must be unambiguous.

- The plugin split durability path must have exactly one authoritative backend target in this phase.
- Once the topology-command split endpoint is introduced, plugin split dispatch and drain behavior switch to that endpoint only.
- The existing `POST /recognition/clusters/{cluster_id}/split` route may remain as an internal/manual surface, but it must not remain the durability target in parallel.
- Routing, tests, and docs must cut over atomically in the same slice.

#### 6. Prefer direct result application over full snapshot refresh

The normal success path should not be “backend call succeeds, then do a snapshot pull to discover what happened.”

Instead:

- backend returns or persists a typed split result
- plugin stores the result durably on the topology command row
- plugin applies the result to the local projection directly, or consumes a backend-supplied delta
- snapshot refresh remains a convergence / repair backstop

For this phase, the intended primary completion path is:

- backend returns typed split result metadata
- plugin persists `result_json`
- plugin applies a direct local projection delta from `result_json`
- plugin marks the command `reconciled`

Targeted or full snapshot refresh is fallback only when:

- direct delta application fails
- required result fields are unavailable
- local projection invariants fail validation

If `member_delta` is absent or incomplete, the next-best acceptable model is:

- persist typed result_json durably
- schedule targeted projection refresh from that durable result
- mark `projection_reconciled_at` only after local projection refresh succeeds

But the long-term architecture should prefer direct typed result application over mandatory snapshot refresh.

### Addendum Patterns to Follow

#### Pattern A: Split Intent Enqueue (No Projection Mutation)

```php
// In ClusterMutationsController::split_cluster()
$wpdb->query('START TRANSACTION');

$command_id = $this->topology_command_repository->enqueue(
  array(
    'command_type' => 'cluster_split',
    'entity_key' => $cluster_id,
    'payload_json' => $payload,
    'expected_base_version' => $cluster_version,
    'idempotency_key' => wp_generate_uuid4(),
  )
);

$this->sync_state_repository->touch_local_curation_marker( $tenant_id );
$wpdb->query('COMMIT');

return rest_ensure_response(
  array(
    'command_id' => $command_id,
    'synced' => false,
    'status' => 'pending',
    'command_state' => 'queued',
    'projection_state' => 'awaiting_backend_partition',
  )
);
```

#### Pattern B: Cross-Plane Sequencing Before Dispatch

```php
// Shared sequencing key for both replay-plane and split-command dispatch.
$sequencing_key = $source_cluster_uuid;

if ( $this->sequencing_locks->is_blocked( $sequencing_key ) ) {
  return; // defer dispatch for this cycle
}

$this->sequencing_locks->acquire( $sequencing_key, $operation_id );
try {
  $response = $this->transport->request( 'POST', '/recognition/topology-commands/split', $body, array() );
  $this->topology_command_repository->record_dispatch_result( $command_id, $response );
} finally {
  $this->sequencing_locks->release( $sequencing_key, $operation_id );
}
```

#### Pattern C: Reconciliation State Machine

- If command response includes complete identity-level `member_delta`: apply local delta directly, validate invariants, mark `reconciled`.
- If response is acknowledged but `member_delta` is incomplete/aggregate-only: persist `result_json`, schedule targeted projection refresh, mark `reconciled` only after refresh succeeds.
- If backend returns `409`: mark command `conflict`, write durable conflict record, surface in sync status.
- If retry budget is exhausted: mark command `failed` and surface failed topology status to operators.

#### Pattern D: Backend Split Command Idempotency + Conflict Gate

```python
# In topology command router/service
cached = await replay_repo.load(tenant_id=request.tenant_id, idempotency_key=request.idempotency_key)
if cached is not None:
  return cached

current_version = await cluster_repo.backend_version(request.cluster_id)
if request.expected_base_version > 0 and request.expected_base_version < current_version:
  raise HTTPException(
    status_code=409,
    detail={
      "conflict_code": "version_conflict",
      "backend_version": current_version,
      "source_cluster_id": request.cluster_id,
      "machine_payload": {...},
    },
  )

result = await split_service.execute_command(request)
await replay_repo.store(tenant_id=request.tenant_id, idempotency_key=request.idempotency_key, payload=result)
return result
```

### Addendum Files to Touch

| File                                                                                                    | Split Addendum Responsibility                                                                                                                          |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`                          | Change `split_cluster()` to enqueue topology commands locally and return pending command state instead of proxying `/recognition/clusters/{id}/split`. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`                          | Remove legacy `cluster_split` topology route in the hard-cutover slice; keep replay-plane routing for non-split operations only.                       |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                               | Enforce shared sequencing contract between replay-plane operations and split topology commands.                                                        |
| `apps/prototype-wp-alt-context/src/sovereign/sync/`                                                     | Add topology-command repository/drain/lock support (or equivalent) for split command lifecycle and durable result storage.                             |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                                | Create/upgrade `wp_acx_topology_commands` schema with durable status/result/retry fields.                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`              | Fold topology-command pending/failed/conflict metrics into sync-state reporting (or publish explicit topology metrics).                                |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`                                | Expose split topology command durability state to operators in REST sync status.                                                                       |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/`                       | Add `POST /recognition/topology-commands/split` and optional command-status read endpoint; make this the single durable split target.                  |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/requests.py`            | Add split topology-command request model (`idempotency_key`, `expected_base_version`, split parameters, desired IDs rules).                            |
| `apps/prototype-description-service/recognition/interface_adapters/http/schemas/responses.py`           | Add typed split command response model (`command_id`, status, member delta/affected clusters, lineage marker, conflict shape).                         |
| `apps/prototype-description-service/recognition/application/orchestration/`                             | Implement split command orchestration that reuses partition logic and emits deterministic typed result metadata.                                       |
| `apps/prototype-description-service/recognition/application/persistence/`                               | Persist command result/lookup state when command polling or durable replay lookups are required by contract.                                           |
| `apps/prototype-wp-alt-context/tests/Unit/` and `apps/prototype-description-service/recognition/tests/` | Add unit/integration coverage for split enqueue, split dispatch, sequencing, conflict handling, and reconciliation completion semantics.               |

### Implementation Plan

1. Plugin `split_cluster()` endpoint behavior:
   - Validate source cluster exists and capture current row context (`snapshot_version`, `local_revision`).
   - Persist a `cluster_split` topology command locally before any network call.
   - Do not move members locally.
   - Do not create local replacement clusters in projection tables during request handling.
   - Return immediate command-state response:
     - `synced: false`
     - `status: pending`
     - `command_state: queued`
     - `projection_state: awaiting_backend_partition`

2. Backend split replay behavior:
   - Keep partition algorithm ownership in recognition split orchestration.
   - Execute split as a backend topology command.
   - Accept `desired_cluster_ids` only for fixed-count splits (`n_clusters >= 2`), validate exact count/uniqueness, and reject them for auto mode (`n_clusters = 0`).
   - Enforce `expected_base_version` before command execution and return a typed `409 Conflict` payload for stale commands.
   - Persist and/or return typed split result metadata:
     - `new_cluster_ids`
     - `member_delta` with explicit identity assignment per affected cluster when direct local apply is expected
     - `moved_counts`
     - `affected_cluster_ids`
     - resulting version marker

3. Command drain / reconciliation behavior:
   - Drain topology commands separately from state replay outbox operations.
   - Respect the shared per-cluster sequencing rule across both durability planes before dispatch.
   - On acknowledged split, persist the typed result durably to the topology command row.
   - Apply a typed result/delta directly to local projection as the primary completion path only when identity-level `member_delta` is present and complete.
   - Use targeted projection refresh as the primary completion path when only aggregate split metadata is available.
   - Use full tenant snapshot refresh only as last-resort repair.
   - Mark command `reconciled` only after projection convergence succeeds locally.

4. Sync status / operator status behavior:
   - Extend sync-state reporting so split topology command states are visible in operator durability status.
   - Either fold open split commands into the existing `pending_curation_operations` / `failed_curation_operations` / `conflict_count` surfaces, or add explicit topology-command fields and expose them in `SyncStatusController`.
   - Record at least one topology failure timestamp and ensure tests cover the REST status surface.

5. UI/operator semantics:
   - Show split as a pending topology command immediately after local enqueue.
   - Overlay command state on top of projection state instead of pretending projected members already moved.
   - Distinguish at least:
     - queued
     - applied remotely
     - reconciled locally
     - failed / conflict
   - Do not represent member movement as final until backend result has been applied or reconciled.

### Checklist Delta (Append-Only Override)

- [x] Replace the existing Phase 2 split checkbox text with: convert `split_cluster()` from replayable local mutation to durable topology command (`payload = {cluster_id, n_clusters, anchor_identity_id?, split_mode?, desired_cluster_ids?}`), where desired IDs are allowed only for fixed-count splits; backend owns partitioning and returns typed result metadata.
- [x] Add topology command schema and repository support in WordPress (`wp_acx_topology_commands`) with typed status, durable result_json, and projection reconciliation tracking.
  Progress:
  - [x] `wp_acx_topology_commands` and repository support now exist for durable split intent records.
  - [x] The repository seam now includes pending-query and status/result update methods needed for the upcoming split drain slice.
  - [x] The topology command table now has a tenant/status index to support sync-state queries efficiently.
  - [x] Typed result persistence, retry state, and projection reconciliation tracking now exist through durable `result_json`, attempt/error updates, and `projection_reconciled_at`.
- [x] Add PHPUnit coverage: split enqueue writes durable topology-command row and returns pending without synchronous backend proxy call.
- [x] Add backend command/result contract support for split, including validation for fixed-count `desired_cluster_ids`, rejection for auto mode, explicit `409 Conflict` behavior for stale `expected_base_version`, and typed conflict payload fields.
  Progress:
  - [x] The first `POST /recognition/topology-commands/split` endpoint is in place with idempotency replay, typed result payload, and stale-base `409` behavior.
  - [x] Member delta construction now uses targeted cluster-member reads instead of a full tenant snapshot fetch.
  - [x] API coverage now includes both the stale-base `409` path and non-empty identity-level `member_delta` assertions.
  - [x] Fixed-count `desired_cluster_ids` validation and auto-mode rejection now pass through the request model and API coverage, and fixed-count desired IDs are honored by the split executor.
- [x] Add cross-plane ordering support so replay-plane topology operations and split topology commands share a per-cluster sequencing rule.
- [x] Add hard-cutover implementation step: plugin split dispatch and drain route only to the topology-command split endpoint, with tests/docs updated in the same slice.
      Progress:
  - [x] Plugin request handling no longer proxies split to the legacy recognition split route and now records durable topology-command intent only.
  - [x] Dedicated split drain routing is now in place, with focused PHPUnit coverage for direct member-delta apply, targeted reconciliation, and repair-only full snapshot fallback.
  - [x] Cross-plane sequencing now blocks replay-plane topology mutations behind earlier split commands and blocks pending split dispatch behind earlier replay-plane topology mutations on the same cluster lineage.
- [x] Remove the legacy `cluster_split` entry from `OutboxDispatcher::TOPOLOGY_ROUTES` during the same hard-cutover slice so the old split replay path cannot survive as dead routing.
- [x] Add command-drain unit coverage: acknowledged split persists typed result metadata durably, survives restart, applies direct local delta only when identity-level `member_delta` is complete, and otherwise falls back to targeted reconciliation before marking convergence.
  Progress:
  - [x] PHPUnit now covers the dedicated split drain, durable result recording, direct local delta application, targeted reconciliation when the member delta is incomplete, and repair-only full snapshot fallback when targeted reconciliation is unavailable.
  - [x] Applied split commands can now resume local reconciliation from durable `result_json` after restart without re-dispatch, and focused PHPUnit covers that restart-safe path.
  - [x] Targeted per-cluster reconciliation now uses the dedicated targeted snapshot endpoint and synthetic member-delta application before any full snapshot repair fallback.
- [x] Add sync-state / sync-status coverage: split topology command states are surfaced to operators through pending/failed/conflict durability metrics or explicit new topology status fields.
  Progress:
  - [x] `SyncStatusController` now includes explicit `topology_commands` lifecycle fields (`pending`, `applied`, `failed`, `conflict`, `last_reconciled_at`) alongside the aggregate durability counters.
  - [x] Focused PHPUnit now covers both the sync-state repository readers and the REST sync-status response for split topology command lifecycle visibility.
- [x] Add backend validation coverage: fixed-count splits validate `desired_cluster_ids` cardinality/uniqueness and auto mode rejects caller-supplied `desired_cluster_ids`.
- [x] Add integration coverage: offline split command queues successfully, backend applies partition, typed result is stored locally, local projection converges via direct apply when identity-level delta is present, and otherwise via targeted reconciliation with full snapshot refresh reserved for repair-only fallback.
  Progress:
  - [x] PHPUnit flow coverage now drives split intent through `ClusterMutationsController`, persists the topology command locally, drains it through the dedicated split command plane, and verifies both direct-apply and targeted-reconciliation convergence paths.
