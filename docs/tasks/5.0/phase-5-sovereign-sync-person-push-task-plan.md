# Phase 5: Sovereign Sync -- Curation Replay, Person Binding, and Conflict Safety

## Problem Statement

Local person curation currently lives primarily in WordPress projection tables. The plugin now has partial replay scaffolding, but the reconciliation loop is still incomplete: backend application logic is not implemented, row-level revision coverage is inconsistent, and the local mutation paths are not yet transactionally tied to durable outbox writes.

This phase should establish the first real reconciliation slice for curation, not a temporary shim. The slice is intentionally limited to person CRUD and cluster-person binding, but it must use the same primitives the broader epic will rely on later: local revisions, durable outbox records, idempotent backend acknowledgement, and explicit conflict handling.

## Workflow Principles

- **WordPress renders truth**: all operator-facing reads continue to come from local projection. Backend responses never short-circuit the local model.
- **Curation-first**: user-created person records, person assignments, and deliberate person removals are authoritative local decisions.
- **No fire-and-forget**: async push may be non-blocking for the UI, but every outbound curation operation must produce an observable local status: `pending`, `acknowledged`, `conflict`, or `failed`.
- **Dissociation is curation**: removing a person from a cluster is not a surrender back to machine authority. It remains a curated state unless the operator explicitly undoes that curation.
- **Generic primitives over narrow shims**: the outbox, acknowledgement, and conflict model introduced here must be reusable later for dismiss, merge, split, and reassignment flows.
- **TDD**: write the failing test first, then implement the smallest change that moves the system toward the epic architecture.

## Terminology

- **Curation operation**: a user-authored mutation that changes local person or cluster assignment state.
- **Local revision**: a monotonic counter on a local row that increments whenever curation changes that row.
- **Expected base version**: the backend machine version the plugin believes it is building on when it emits a curation operation.
- **Outbox operation**: a durable local record of a curation operation awaiting acknowledgement from the backend.
- **Acknowledgement**: a backend response stating that an outbox operation was accepted and applied or was already applied idempotently.
- **Conflict**: a backend response stating that the curation operation could not be applied safely against the current backend base state.
- **Curated dissociation**: a cluster with `person_id = NULL` that remains intentionally curated and protected from machine overwrite.
- **Person binding**: the backend association of `identity_clusters.roster_id` to the local `person_uuid`.

## Current State Analysis

- `commit_roster_cluster()` in [`apps/prototype-wp-alt-context/src/api/class-api.php`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/api/class-api.php) already sets `curation_state = 'confirmed'`, `is_user_confirmed = 1`, increments `local_revision`, and enqueues `cluster_person_bound` / `cluster_person_unbound` outbox operations.
- `delete_person()` already preserves curated dissociation locally by clearing `person_id` while keeping the affected clusters confirmed and protected from overwrite.
- The plugin already has `wp_acx_sync_outbox`, `wp_acx_sync_conflicts`, `local_revision` on clusters, outbox writer/drain/dispatcher classes, and sync-status counters for pending operations and conflicts.
- [`apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php) and [`apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php) already honor `is_user_confirmed = 1`; the remaining gap is to verify every person-related mutation path is transactionally safe and fully covered by tests.
- Person rows do not yet carry a local revision of their own, so `person_created`, `person_updated`, and `person_deleted` operations still use coarse revision semantics.
- Local mutation + outbox insertion is not yet wrapped in a real database transaction, so the plan still needs to close the partial-write window.
- The description service already has a scaffolded `/roster/curation/sync` router and `CurationSyncService`, but the service is still `NotImplemented` and the router does not yet resolve tenant/auth context correctly.
- [`apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`](/Users/daniel/Development/context-alt-text-monorepo/apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py) still contains a phantom `roster_entries` lookup that does not fit the current local-first naming model.

## Proposed Solution

Implement one reconciliation-safe vertical slice for person curation:

1. **Local curation semantics**: person assignment and person dissociation both become protected local curation actions. They increment local revision, mark the cluster curated, and record machine-base information needed for replay.
2. **Durable curation outbox**: finish the existing outbox path so person CRUD and cluster-person binding mutations are transactionally coupled to generic outbox operations with idempotency keys, expected base version, local revision, and status tracking.
3. **Backend curation acknowledgement**: the description service accepts a generic curation operation payload for this slice, binds or clears `roster_id`, and returns `acknowledged` or `conflict` with version information.
4. **Conflict-safe local state**: acknowledgement updates local sync metadata; conflicts are stored explicitly and surfaced through sync state instead of being silently retried forever or silently overwritten.
5. **Forward-safe row revisions**: extend person rows with local revision semantics now so later curation replay for rename, merge, and person-level drift does not require a second data-model rewrite.

This task does not solve the entire epic. It does, however, establish the durable primitives that future phases can extend to dismiss, undismiss, merge, split, and reassignment flows without re-architecting the sync model.

## Patterns to Follow

### Transactional Local Mutation + Outbox Write

```php
// Pseudocode only. Use one transaction so local state and durable replay state
// do not drift apart when a request fails mid-flight.

$wpdb->query( 'START TRANSACTION' );

try {
    // 1. mutate local row(s)
    // 2. increment row revision(s)
    // 3. enqueue outbox operation(s)
    // 4. refresh sync metrics
    $wpdb->query( 'COMMIT' );
} catch ( Throwable $e ) {
    $wpdb->query( 'ROLLBACK' );
    throw $e;
}
```

### Protected Local Curation on Person Assignment

```php
// In class-api.php::commit_roster_cluster(), inside a transaction:
// 1. resolve person_id/person_uuid
// 2. update cluster as a curated row
// 3. enqueue a durable curation outbox operation

$wpdb->update(
    $table_clusters,
    [
        'person_id'         => $person_id,
        'curation_state'    => 'confirmed',
        'is_user_confirmed' => 1,
        'local_revision'    => $next_local_revision,
        'updated_at'        => current_time( 'mysql' ),
    ],
    [ 'cluster_uuid' => $cluster_uuid ],
    [ '%d', '%s', '%d', '%d', '%s' ],
    [ '%s' ]
);

$outbox_writer->enqueue(
    operation_type: 'cluster_person_bound',
    entity_type: 'cluster',
    entity_key: $cluster_uuid,
    tenant_id: $tenant_id,
    expected_base_version: $snapshot_version,
    local_revision: $next_local_revision,
    payload: [
        'cluster_uuid' => $cluster_uuid,
        'person_uuid'  => $person_uuid,
    ]
);
```

### Curated Dissociation, Not Reversion to Machine Control

```php
// In delete_person() or an explicit unassign flow, preserve that the operator
// intentionally removed the person. Do not set is_user_confirmed back to 0.

$wpdb->update(
    $table_clusters,
    [
        'person_id'         => null,
        'curation_state'    => 'confirmed',
        'is_user_confirmed' => 1,
        'local_revision'    => $next_local_revision,
        'updated_at'        => current_time( 'mysql' ),
    ],
    [ 'person_id' => $person_id ],
    [ null, '%s', '%d', '%d', '%s' ],
    [ '%d' ]
);

$outbox_writer->enqueue(
    operation_type: 'cluster_person_unbound',
    entity_type: 'cluster',
    entity_key: $cluster_uuid,
    tenant_id: $tenant_id,
    expected_base_version: $snapshot_version,
    local_revision: $next_local_revision,
    payload: [
        'cluster_uuid' => $cluster_uuid,
        'person_uuid'  => null,
    ]
);
```

### Generic Outbox Record with Ack/Conflict Semantics

```sql
CREATE TABLE {prefix}acx_sync_outbox (
    id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
    tenant_id varchar(64) NOT NULL,
    operation_type varchar(64) NOT NULL,
    entity_type varchar(64) NOT NULL,
    entity_key varchar(128) NOT NULL,
    idempotency_key char(36) NOT NULL,
    expected_base_version bigint(20) unsigned NOT NULL DEFAULT 0,
    local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
    payload longtext NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending',
    attempts int(11) unsigned NOT NULL DEFAULT 0,
    last_error_code varchar(64) DEFAULT NULL,
    last_error_message text DEFAULT NULL,
    acknowledged_version bigint(20) unsigned DEFAULT NULL,
    created_at datetime NOT NULL,
    last_attempted_at datetime DEFAULT NULL,
    acknowledged_at datetime DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_idempotency (idempotency_key),
    KEY idx_status_created (status, created_at),
    KEY idx_entity (entity_type, entity_key)
);
```

### Conflict Record Instead of Silent Retry

```sql
CREATE TABLE {prefix}acx_sync_conflicts (
    id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
    tenant_id varchar(64) NOT NULL,
    entity_type varchar(64) NOT NULL,
    entity_key varchar(128) NOT NULL,
    outbox_id bigint(20) unsigned NOT NULL,
    expected_base_version bigint(20) unsigned NOT NULL DEFAULT 0,
    backend_version bigint(20) unsigned NOT NULL DEFAULT 0,
    local_revision bigint(20) unsigned NOT NULL DEFAULT 0,
    conflict_code varchar(64) NOT NULL,
    machine_payload longtext NOT NULL,
    local_payload longtext NOT NULL,
    resolution_status varchar(20) NOT NULL DEFAULT 'open',
    created_at datetime NOT NULL,
    resolved_at datetime DEFAULT NULL,
    PRIMARY KEY (id),
    KEY idx_entity_resolution (entity_type, entity_key, resolution_status)
);
```

### Backend Acknowledgement Contract

```python
@router.post("/roster/curation/sync")
async def sync_curation_operation(
    request: CurationSyncRequest,
    tenant=Depends(get_tenant),
    session: AsyncSession = Depends(get_session),
):
    """
    Accept one idempotent curation operation for the current slice.
    Supported operation types for now:
    - person_created
    - person_updated
    - person_deleted
    - cluster_person_bound
    - cluster_person_unbound
    """

    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=request,
    )

    if result.status == "conflict":
        return JSONResponse(
            status_code=409,
            content={
                "status": "conflict",
                "conflict_code": result.conflict_code,
                "backend_version": result.backend_version,
                "machine_payload": result.machine_payload,
            },
        )

    return {
        "status": "acknowledged",
        "backend_version": result.backend_version,
        "idempotency_key": request.idempotency_key,
    }
```

### Drain Updates Local State by Result Type

```php
$result = $dispatcher->dispatch( $operation );

if ( 'acknowledged' === $result['status'] ) {
    $outbox_repository->mark_acknowledged( $operation->id, (int) $result['backend_version'] );
    $sync_state_repository->record_success( $tenant_id, $operation->id );
} elseif ( 'conflict' === $result['status'] ) {
    $conflict_repository->record_conflict( $operation, $result );
    $outbox_repository->mark_conflict( $operation->id, $result['conflict_code'] );
    $sync_state_repository->record_conflict( $tenant_id );
} else {
    $outbox_repository->mark_retryable_failure( $operation->id, $result['error_code'] );
}
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/src/api/class-api.php` | `commit_roster_cluster()` / `create_person()` / `update_person()` / `delete_person()` | Finish the current implementation by adding transaction boundaries, person-row revision handling, and stricter failure behavior when local mutation or enqueue fails. |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php` | `create_tables()` | Extend `wp_acx_persons` with `local_revision` and add any remaining reconciliation metadata needed by the finalized contract. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` | snapshot merge and mutation methods | Verify merge rules still hold with current cluster revision semantics and future conflict handling. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | sync state helpers | Keep current counters, but extend them only where needed for acknowledged sequence/version tracking. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php` | `enqueue()` | Reuse the existing writer; adjust only if the contract needs extra person-revision or acknowledgement metadata. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php` | `drain()` / result handling | Reuse the existing drain; tighten around transaction-safe state refresh, conflict recording, and eventual backend acknowledgement semantics. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php` | `dispatch()` | Keep the generic transport contract but align request and error semantics with the implemented backend endpoint. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php` | `record_conflict()` | Reuse existing persistence and extend only if the backend emits richer machine payload or resolution metadata. |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | sync status payload | Validate the existing pending/conflict fields against the final contract and add only missing acknowledgement metadata. |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | `get_roster_entry_name()` | Remove the phantom `roster_entries` dependency. Treat WordPress as the naming authority for this slice. |
| `apps/prototype-description-service/roster/interface_adapters/http/curation_router.py` | existing scaffold | Replace placeholder tenant handling and 501 behavior with real dependency wiring, validation, and conflict response semantics. |
| `apps/prototype-description-service/roster/application/curation_sync_service.py` | existing scaffold | Implement supported operation types, idempotency handling, base-version checks, and `roster_id` binding or clearing. |
| `apps/prototype-description-service/roster/__init__.py` | package exports | Ensure the existing curation router is mounted with the rest of the roster surface. |
| `apps/prototype-description-service/recognition/tests/api/test_curation_sync_router.py` | new | Add backend API coverage for acknowledgement, conflict, and not-implemented regression paths. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Existing protection logic for curated rows stays relevant; this task must activate it consistently for person curation paths. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | Future phases will need the same local revision and conflict-safe semantics for membership replay. This task should not block that extension. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Not the main implementation target here, but sync-status payload changes should anticipate future UX surfacing of pending and conflict state. |
| `apps/prototype-description-service/db/models/identity.py` | `IdentityCluster.roster_id` already exists and remains the backend binding target for this slice. |
| `apps/prototype-description-service/recognition/interface_adapters/http/router.py` | May need router registration changes for the new roster curation endpoint. |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Source-of-truth architecture for why this task must use durable replay and conflict semantics rather than fire-and-forget push. |

---

# Consolidated Checklist

## Completed

- [x] Phases 1-4 delivered the local roster/dashboard/cluster UX needed for curation-first workflows.
- [x] Snapshot projection already protects curated rows when `is_user_confirmed = 1`.
- [x] Plugin schema scaffolds for `wp_acx_sync_outbox`, `wp_acx_sync_conflicts`, cluster `local_revision`, and sync-state curation metrics exist.
- [x] Plugin outbox writer, drain, dispatcher, conflict repository, and sync-status payload extensions exist.
- [x] Plugin person CRUD and cluster commit paths already enqueue curation operations and preserve curated dissociation semantics.
- [x] Backend curation router and service scaffolds exist.

## Phase 0: Scaffolding

- [x] Add schema scaffolds for `wp_acx_sync_outbox`, `wp_acx_sync_conflicts`, and the new reconciliation fields on `wp_acx_clusters` / `wp_acx_sync_state`.
- [x] Add `OutboxWriter`, `OutboxDrain`, `OutboxDispatcher`, and `ConflictRepository` class stubs with typed method signatures and docblocks.
- [x] Add backend `curation_router.py` and `curation_sync_service.py` scaffolds with request/response types for acknowledgement and conflict results.
- [x] Create PHPUnit scaffolds and initial plugin coverage for person CRUD, outbox writer, and outbox drain behavior.
- [x] Add or update cross-layer contract docs for the curation sync payload and response semantics.
- [x] Create backend pytest coverage for the curation router and service.
- [x] Verify scaffolds compile and targeted test collection stays clean after the backend tests are added.

## Phase 1: Local Curation Semantics

- [x] **Tested + implemented**: committing a cluster to a person sets `curation_state = 'confirmed'`, `is_user_confirmed = 1`, increments `local_revision`, and queues a curation operation.
- [x] **Tested + implemented**: deleting a person clears `person_id` while preserving curated protection on affected clusters.
- [x] Wrap each local mutation + enqueue path in a real DB transaction to avoid partial-write windows.
- [x] Extend `wp_acx_persons` with `local_revision` and use it for `person_created`, `person_updated`, and `person_deleted` operations instead of constant revision placeholders.
- [x] Add or strengthen tests that a deliberately unassigned cluster remains out of pending review and survives snapshot replay end-to-end.

## Phase 2: Durable Outbox and Local Sync State

- [x] **Implemented + tested**: `wp_acx_sync_outbox`, `wp_acx_sync_conflicts`, outbox writer, and drain status transitions (`acknowledged`, `conflict`, `pending`, `failed`) exist.
- [x] **Implemented**: sync-state counters for pending operations, conflicts, and last acknowledgement exist.
- [x] Move enqueue behavior under the same transaction as the local mutation, rather than relying on sequential best effort inside one request.
- [x] Tighten expected-base semantics so the operation contract is not only stream-level snapshot based where row-level lineage is needed.
- [x] Add backend-facing contract coverage so dispatcher/request and drain/result expectations cannot drift silently.

## Phase 3: Backend Curation Acknowledgement

- [x] **Scaffolded**: `POST /roster/curation/sync` and `CurationSyncService` contracts exist.
- [x] Implement real tenant resolution and dependency wiring for the curation router.
- [x] Implement supported operation handling for `person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, and `cluster_person_unbound`.
- [x] Add idempotency persistence so repeated delivery of the same idempotency key is a safe acknowledgement.
- [x] Add expected-base-version checks that return `409 conflict` with backend version and machine payload when replay is stale.
- [x] Bind, rebind, and unbind `identity_clusters.roster_id` correctly for the tenant.
- [x] Remove the phantom `roster_entries` query from `cluster_repository.get_roster_entry_name()`.
- [x] Add backend API and service tests for acknowledgement, conflict, and idempotent replay.

## Phase 4: Integration Verification

- [ ] End-to-end manual test: create person in WP, assign cluster, confirm outbox record is written, drain runs, backend acknowledges, and local sync status updates.
- [ ] End-to-end manual test: delete or unassign person, confirm curated dissociation remains protected locally and backend clears `roster_id`.
- [ ] End-to-end manual test: simulate stale backend base version and verify the plugin records a conflict instead of silently retrying or overwriting local state.
- [x] Verify snapshot projection after acknowledgement still preserves curated rows.
- [x] All relevant PHPUnit, pytest, and targeted frontend sync-status tests pass.

## Stretch Goals

- [x] Replace WP cron draining with Action Scheduler once the acknowledgement contract is stable.
- [x] Add lightweight admin visibility for pending and conflicting curation operations.
- [x] Batch multiple curation operations per HTTP request once single-operation acknowledgement is proven stable.
- [x] Introduce shared replay primitives for dismiss and undismiss mutations using the same outbox contract.

## Success Criteria

- [x] Person assignment and deliberate person removal are both preserved as curated local state and are no longer vulnerable to silent machine overwrite.
- [x] Person CRUD and cluster-person binding mutations produce durable outbox operations with idempotency key, expected base version, and local revision.
- [x] The backend acknowledges or conflicts each replayed curation operation explicitly; the plugin does not rely on fire-and-forget push semantics.
- [x] Conflicts are stored and surfaced locally instead of being silently dropped or retried forever.
- [x] The implementation establishes reusable replay primitives for later curation mutations instead of a person-only shim that must be replaced.
