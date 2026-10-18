# Phase 4: Offline and Conflict UX

## Problem Statement

Operators cannot currently distinguish offline, stale, queued, or conflicted sync states from normal operation. Conflict records exist in `wp_acx_sync_conflicts` but have no resolution UI. Dead-letter outbox operations have no inspection or manual retry surface. The dashboard shows no sync health indicators. Operators must query the database directly to understand or resolve sync problems.

## Workflow Principles

- **Operator comprehension over automation.** Every sync state the system can enter must be understandable from the UI. Silent internal states that require database access are bugs.
- **Conflicts are first-class work items.** Machine proposals blocked by curation are not errors; they are review tasks that need an inbox, detail view, and resolution workflow.
- **Recovery is always operator-initiated for conflict resolution.** Auto-retry handles transient failures (Phase 3). Conflict resolution, dead-letter retry, and forced resync require explicit operator action.
- **Progressive disclosure.** Summary indicators (counts, timestamps) are always visible. Detail views (conflict payloads, outbox operation history) load on demand.
- **Existing infrastructure first.** Phase 3 delivered outbox, conflict recording, sync state metrics, and topology command tracking. Phase 4 builds query/display/resolution layers on top of that infrastructure without rebuilding it.

## Terminology

- **Conflict record**: a `wp_acx_sync_conflicts` row written when a backend snapshot proposes a change to a curated entity (projection conflict) or when a curation push returns 409 (outbox conflict). Resolution status is `open`, `accepted`, or `dismissed`. Transitions: `open` -> `accepted` | `dismissed`. There is no generic `resolved` state; the specific resolution choice (accept machine vs. keep local) is always recorded.
- **Dead-letter operation**: an outbox row with `status = 'failed'` after exhausting its retry budget (default 5 attempts). Requires manual inspection and retry or discard.
- **Stale state**: `is_stale = true` in sync status, meaning the local projection has not been refreshed within the staleness threshold.
- **Queued state**: `pending_curation_operations > 0` or `topology_commands.pending > 0`, indicating local mutations awaiting backend sync.
- **Offline**: the backend recognition service is unreachable. Determined from persisted `last_sync_result` field in `wp_acx_sync_state`: when the most recent sync attempt failed with a network/connection error, the service is considered offline until the next successful sync. `SyncPullJob` already persists this result after every real sync attempt (including `trigger_sync()`, inline stale refresh, and bootstrap pulls) so that subsequent GET requests can derive the offline state without a live probe. `SyncPullJobInterface` returns `SyncPullResult` (`ok` | `failed` | `unreachable` | `skipped`), and `SyncStateRepository` is already injected into `SyncPullJob`. The `skipped` value covers the cooldown short-circuit in `perform()` -- when a cooldown transient is active, no fetch is attempted and `last_sync_result`/`last_sync_attempted_at` are NOT overwritten (the previous attempt's result remains authoritative).
- **Conflict resolution**: the operator reviews a machine proposal vs. local curation and chooses to accept the machine version or keep the local version. Resolution is not just a status flag update -- it must reconcile the underlying local/backend divergence per conflict source:
  - **Outbox conflict resolution (accept machine)**: available only where Phase 4 can reconcile the local row deterministically. Supported **single-row operations** are `cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, and `cluster_person_unbound`. The resolution service joins to the outbox row via `outbox_id` to read `operation_type` and gates acceptance. For accepted cluster/member conflicts: clear the curation flags on the affected entity (`is_user_confirmed = 0` for clusters, `is_curated = 0` for members), discard the conflicted outbox row, and mark the conflict `accepted`. Convergence to the machine state requires a subsequent sync pull; the resolution service does not trigger this automatically -- the frontend should show a "Sync Now" affordance after successful resolution (reusing `useSyncTrigger`). The curation flag reset is required because the projection's `ON DUPLICATE KEY UPDATE` guards preserve curated rows. **Cluster curation caveat**: the schema uses a single `is_user_confirmed` flag that guards label, person_id, and curation_state jointly, so accepting any cluster outbox conflict resets ALL curated fields on that cluster (not just the conflicting field). The UI must warn the operator which curated fields will be lost. **Person CRUD and compound topology operations** (`person_created`, `person_updated`, `person_deleted`, `cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) do not get "accept machine" in Phase 4 because they need either person-level overwrite/delete contracts or multi-entity revert contracts that are not yet defined. For those conflicts, only "keep local" (re-enqueue) is offered. Per-operation acceptance is a follow-on or stretch goal.
  - **Outbox conflict resolution (keep local)**: re-enqueue the outbox operation with the current `backend_version` as the new `expected_base_version`, mark the conflict `dismissed`, and let the next drain attempt replay the curation against the updated base. Column-level: the outbox row's `status` resets from `conflict` to `pending`, `attempts` resets to `0`, `expected_base_version` is set to the conflict's `backend_version`, and error fields are cleared. The conflict row's `resolution_status` transitions to `dismissed`. The original outbox row (same `id`) is mutated in place -- no new row is created.
  - **Projection conflict resolution (accept machine)**: dispatch per `conflict_code` since machine_payload content varies by conflict type (deletion conflicts store only sentinel data like `{status: 'missing_from_snapshot'}`, not full replacement state). For `curated_cluster_deleted`: delete the curated cluster row AND all member rows that reference it in the same transaction (the schema has no FK cascade, so orphan cleanup must be explicit -- `ClustersRepository::delete_cluster_with_members()` deletes members first, then the cluster). For `curated_member_deleted`: delete the curated member row. For `member_cluster_reassignment`: update the member's `cluster_uuid` to the machine-proposed value and set `is_curated = 0` via `accept_machine_cluster_assignment()` (distinct from the existing `reassign_to_cluster()` which sets `is_curated = 1` for user-initiated reassignment). Mark the conflict `accepted` after entity mutation.
  - **Projection conflict resolution (keep local)**: mark the conflict `dismissed` with no entity mutation. The local curated state is preserved and the machine proposal is discarded.

## Current State Analysis

- `SyncStatusIndicator` shows coarse states: syncing, stale+retry, fresh, unavailable. It already includes a retry affordance for projection errors and stale/unreachable states, but it does not link to conflict detail or dead-letter management.
- `DashboardPage` shows library coverage, identity stats, quick actions, and job history. No sync health or conflict indicators exist on the dashboard.
- `SyncStatusResponse` TypeScript type already includes `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, `last_curation_conflict_at`, `last_curation_failed_at`, and `topology_commands` (pending/applied/failed/conflict). The data contract is already rich enough for Phase 4 summary indicators.
- `ConflictRepository` can `record_conflict()` and `record_projection_conflict()` but has no public query methods for listing, filtering, or resolving conflicts. Only the private `find_open_projection_conflict()` method exists.
- `SyncStateRepository` provides aggregate counts (`get_pending_curation_operations`, `get_conflict_count`, `get_failed_curation_operations`) but no detail queries for individual operations or conflicts.
- `OutboxDrain` handles bounded retry (max 5 attempts, no backoff delay between attempts) and marks dead-letter operations as `failed` after exhausting the budget. Retry attempts are immediate on the next scheduled drain run. No manual retry mechanism exists.
- `SyncStatusController` exposes `GET /acx/v1/recognition/sync-status` and `POST /acx/v1/recognition/sync/trigger` but no conflict list/detail/resolution endpoints, no outbox operation list, and no dead-letter retry endpoint. Its constructor accepts only `SyncStateRepositoryInterface` and `SyncPullJobInterface`; conflict and dead-letter routes need their own controller to avoid inflating this constructor.
- `SyncPullJobInterface` defines `perform(string $tenant_id): SyncPullResult` and `perform_bypass_cooldown(string $tenant_id): SyncPullResult`. The structured return type distinguishes failure kinds (network unreachable vs. projection error vs. cooldown skip) and is already consumed by `ClustersController` and `SyncStatusController`.
- `SyncPullJob` persists sync results via `SyncStateRepository::set_last_sync_result()` after each real `do_sync()` call: `unreachable` for network errors, `failed` for projection errors, `ok` for successful projection (even if acknowledgement fails). The cooldown short-circuit returns `SyncPullResult::skipped()` without overwriting persisted state.
- `SyncStatusController` already includes `classify_sync_health()` and exposes `sync_health` and `last_sync_result` fields in both GET and POST responses.
- `wp_acx_sync_state` already has `last_sync_result varchar(20)` and `last_sync_attempted_at datetime` columns. `SyncHealth` TypeScript type plus `sync_health`/`last_sync_result` fields already exist in `SyncStatusResponse` and `SyncTriggerResponse`.
- `wp_acx_sync_conflicts` table schema has `resolution_status` (`open` default) and `resolved_at` columns but no resolution infrastructure writes to them.
- `wp_acx_sync_outbox` has `status`, `attempts`, `last_error_code`, `last_error_message` columns that Phase 4 needs to surface.
- Person CRUD and cluster-person binding (`person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`) already use the same outbox/conflict path delivered in earlier phases, so Phase 4 must give those conflicts an operator-visible resolution path even where "accept machine" remains out of scope.
- The deferred UX ergonomics document routes the **operator-facing person-name conflict UX foundation** to this phase, but backend-authored machine proposal generation for person names is still a separate follow-on dependency.

## Proposed Solution

Build Phase 4 in five layers, each independently testable:

1. **PHP: Conflict and outbox query/resolution API.** Add REST endpoints for listing conflicts, viewing conflict detail, resolving conflicts, listing dead-letter operations, and retrying or discarding dead-letter entries. Extend `ConflictRepository` with query and resolution methods. Extend `OutboxDrain` with dead-letter query, retry, and discard methods (outbox row persistence stays in the existing outbox classes, not in `SyncStateRepository` which owns only aggregate sync-state reads/writes).

2. **PHP: Sync status enrichment (already implemented).** `wp_acx_sync_state` already has `last_sync_result` and `last_sync_attempted_at` columns, persisted by `SyncPullJob` after every real sync attempt (including `trigger_sync()`, inline stale refresh, and bootstrap pulls from `ClustersController`). `SyncPullJobInterface` returns `SyncPullResult` (`ok` | `failed` | `unreachable` | `skipped`), and `SyncStatusController` already computes a `sync_health` field (`healthy`, `queued`, `stale`, `conflicts`, `failures`, `offline`) in both GET and POST responses. No Phase 4 work is needed for this layer.

3. **Frontend: Sync health indicators.** Upgrade `SyncStatusIndicator` to surface the `sync_health` classification with distinct visual states and actionable links. For `conflicts` and `failures` states, the indicator shows total counts (conflict count badge, failed count badge) linked to their respective panels. The current storage model does not reliably distinguish curation-outbox conflicts from topology-command conflicts (both flow through `wp_acx_sync_conflicts` via the outbox, and `SyncStateRepository::get_conflict_count()` aggregates all open conflicts), so the indicator does NOT attempt a per-source breakdown. Topology command pending/failed/conflict counts from `topology_commands` in `SyncStatusResponse` are shown as a separate informational line when non-zero (not merged into the conflict/failure totals). Add a condensed sync health badge to `DashboardPage` with the same approach. Wire conflict count and failed count badges as navigation links to the detail views via the workbench panel contract defined below.

4. **Frontend: Conflict inbox and dead-letter management.** Add a conflict list component showing open conflicts with entity type, entity key, conflict code, timestamps, and local-vs-machine payload comparison. Add resolution actions (accept machine, keep local). Add a dead-letter list showing failed outbox operations with error details, and retry/discard actions.

5. **Frontend: Navigation contract.** Conflict inbox and dead-letter UI are rendered as workbench overlays, activated by a `panel` query parameter (`?panel=conflicts` or `?panel=dead-letter`). This avoids extending the existing `WorkbenchTab` type (`scan | batch | confirm`) which controls the primary workflow tabs, and avoids overloading the existing cluster-panel abstraction from `Panels.tsx` / `ClusterPanelState`. Overlays sit above the active tab content and are dismissible. `WorkbenchContext` gains an `activeOverlay: WorkbenchOverlay | null` state and `setActiveOverlay` setter. `SyncStatusIndicator` badges and `DashboardPage` links navigate to the workbench with the appropriate `panel` query param.

Retention/export/purge endpoints are explicitly out of scope for this task plan. The epic lists them as Phase 5 deliverables (Retention, Export, Purge), not Phase 4. They depend on backend tenant policy infrastructure that does not exist yet (no retention mode fields, no audit event tables). They should be scoped as a separate task plan once backend policy fields land.

## Patterns to Follow

### PHP: Conflict Query Pattern

```php
// In ConflictRepository -- new public query method
public function find_conflicts_for_tenant( string $tenant_id, string $resolution_status = 'open', int $limit = 50, int $offset = 0 ): array {
    global $wpdb;
    return $wpdb->get_results(
        $wpdb->prepare(
            'SELECT id, entity_type, entity_key, conflict_code, backend_version, local_revision,
                    machine_payload, local_payload, resolution_status, outbox_id, created_at
             FROM %i WHERE tenant_id = %s AND resolution_status = %s
             ORDER BY created_at DESC LIMIT %d OFFSET %d',
            $this->table_name, $tenant_id, $resolution_status, $limit, $offset
        ),
        ARRAY_A
    );
}
```

The `outbox_id` column distinguishes conflict sources: a non-zero value means outbox conflict (curation operation that the backend rejected), `0` means projection conflict (backend proposed a change that conflicts with local curation). The schema defines `outbox_id bigint(20) unsigned NOT NULL` -- projection conflicts are inserted with `outbox_id = 0` as a sentinel (not NULL). PHP source detection uses `! empty($conflict['outbox_id'])` which works because `empty(0)` is `true` in PHP. `ConflictController` uses `outbox_id` to derive the `allowed_resolutions` field in the REST response (see below).

### PHP: Conflict Resolution Pattern

Resolution is a multi-step operation wrapped in a database transaction: reconcile the entity state, then update the conflict record. The `ConflictResolutionService` owns the dispatch to the correct reconciliation path per conflict source. All entity mutations and conflict status updates within a single `resolve()` call are wrapped in `$wpdb->query('START TRANSACTION')` / `COMMIT` / `ROLLBACK` to prevent partial state (e.g., curation cleared but conflict still `open`, allowing duplicate resolution).

```php
// In ConflictResolutionService -- dispatch per source
/**
 * @return array{ok:bool, reason:'success'|'not_found'|'already_resolved'|'resolution_not_allowed'|'entity_mutation_failed'|'conflict_update_failed'}
 */
public function resolve( int $conflict_id, string $resolution, string $tenant_id ): array {
    global $wpdb;
    $conflict = $this->conflict_repo->find_conflict_by_id( $conflict_id, $tenant_id );
    if ( ! $conflict ) {
        return array( 'ok' => false, 'reason' => 'not_found' );
    }
    if ( $conflict['resolution_status'] !== 'open' ) {
        return array( 'ok' => false, 'reason' => 'already_resolved' );
    }

    $wpdb->query( 'START TRANSACTION' );

    $has_outbox_id = ! empty( $conflict['outbox_id'] ); // 0 = projection, non-zero = outbox
    $ok = true;

    if ( 'accepted' === $resolution ) {
        if ( $has_outbox_id ) {
            // Outbox conflict: look up operation_type to gate acceptance.
            $operation = $this->outbox_drain->find_operation_by_id( (int) $conflict['outbox_id'], $tenant_id );
            if ( ! $this->is_single_entity_operation( $operation['operation_type'] ?? '' ) ) {
                $wpdb->query( 'ROLLBACK' );
                return array( 'ok' => false, 'reason' => 'resolution_not_allowed' );
            }
            $ok = $this->clear_curation_for_entity( $conflict['entity_type'], $conflict['entity_key'], $tenant_id );
            if ( $ok ) {
                $ok = $this->outbox_drain->discard_operation( (int) $conflict['outbox_id'], $tenant_id );
            }
        } else {
            // Projection conflict: dispatch per conflict_code (machine_payload varies by type).
            $ok = $this->resolve_projection_accepted( $conflict, $tenant_id );
        }
    } elseif ( 'dismissed' === $resolution ) {
        if ( $has_outbox_id ) {
            // Outbox conflict: re-enqueue with updated base version.
            $ok = $this->outbox_drain->re_enqueue_with_current_base(
                (int) $conflict['outbox_id'],
                (int) $conflict['backend_version'],
                $tenant_id
            );
        }
        // Projection conflict dismissed: no entity mutation, local state preserved.
    }

    if ( ! $ok ) {
        $wpdb->query( 'ROLLBACK' );
        return array( 'ok' => false, 'reason' => 'entity_mutation_failed' );
    }

    $marked = $this->conflict_repo->mark_resolved( $conflict_id, $resolution, $tenant_id );
    if ( ! $marked ) {
        $wpdb->query( 'ROLLBACK' );
        return array( 'ok' => false, 'reason' => 'conflict_update_failed' );
    }
    $wpdb->query( 'COMMIT' );
    return array( 'ok' => true, 'reason' => 'success' );
}

// Single-row outbox operations where 'accept machine' is safe in Phase 4.
private const SINGLE_ENTITY_OPS = [
    'cluster_label_updated', 'cluster_dismissed', 'cluster_undismissed', 'identity_reassigned',
    'cluster_person_bound', 'cluster_person_unbound',
];

private function is_single_entity_operation( string $operation_type ): bool {
    return in_array( $operation_type, self::SINGLE_ENTITY_OPS, true );
}

// Clear curation flags so next projection can overwrite (outbox accept path).
// Note: for clusters, this resets ALL curated fields (label, person_id, curation_state)
// because they share a single is_user_confirmed flag in the schema.
private function clear_curation_for_entity( string $entity_type, string $entity_key, string $tenant_id ): bool {
    return match ( $entity_type ) {
        'cluster' => $this->clusters_repo->reset_curation( $entity_key, $tenant_id ),
        'member'  => $this->members_repo->reset_curation( $entity_key, $tenant_id ),
        default   => false,
    };
}

// Helper: per-conflict_code dispatch for projection conflict acceptance.
private function resolve_projection_accepted( array $conflict, string $tenant_id ): bool {
    return match ( $conflict['conflict_code'] ) {
        'curated_cluster_deleted'      => $this->clusters_repo->delete_cluster_with_members(
            $conflict['entity_key'], $tenant_id
        ),
        'curated_member_deleted'       => $this->members_repo->delete_member(
            $conflict['entity_key'], $tenant_id
        ),
        'member_cluster_reassignment'  => $this->members_repo->accept_machine_cluster_assignment(
            $conflict['entity_key'],
            json_decode( $conflict['machine_payload'], true )['cluster_uuid'],
            $tenant_id
        ),
        default                        => false,
    };
}
```

`ConflictController` maps the structured result to HTTP semantics instead of collapsing everything to a 500-style failure: `not_found` -> `404`, `already_resolved` -> `409`, `resolution_not_allowed` -> `422`, and mutation/update failures -> `500`.

```php
// In ConflictRepository -- status update (called by resolution service)
public function mark_resolved( int $conflict_id, string $resolution_status, string $tenant_id ): bool {
    global $wpdb;
    $updated = $wpdb->update(
        $this->table_name,
        array(
            'resolution_status' => $resolution_status,
            'resolved_at'       => current_time( 'mysql' ),
        ),
        array(
            'id'        => $conflict_id,
            'tenant_id' => $tenant_id,
        )
    );
    return $updated !== false;
}
```

### PHP: Dead-Letter Retry Pattern

```php
// In OutboxDrain -- dead-letter operations stay in the outbox class
public function retry_failed_operation( int $outbox_id, string $tenant_id ): bool {
    global $wpdb;
    $updated = $wpdb->update(
        $this->outbox_table,
        array(
            'status'   => 'pending',
            'attempts' => 0,
            'last_error_code'    => null,
            'last_error_message' => null,
        ),
        array(
            'id'        => $outbox_id,
            'tenant_id' => $tenant_id,
            'status'    => 'failed',
        )
    );
    if ( $updated ) {
        $this->sync_state_repository->refresh_curation_metrics( $tenant_id );
        OutboxDrain::maybe_schedule_drain();
    }
    return $updated !== false;
}
```

### REST: Dead-Letter Response Contract

```typescript
export interface OutboxOperation {
  id: number;
  tenant_id: string;
  operation_type: string;
  entity_type: string;
  entity_key: string;
  status: "failed" | "pending" | "conflict" | "discarded" | "acknowledged";
  attempts: number;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  last_attempted_at: string | null;
}

export interface OutboxListResponse {
  items: OutboxOperation[];
  total: number;
  limit: number;
  offset: number;
}

export interface OutboxMutationResponse {
  operation: OutboxOperation;
}
```

`GET /acx/v1/recognition/outbox/failed` returns `OutboxListResponse` with tenant-scoped failed rows. `POST /acx/v1/recognition/outbox/{id}/retry` returns `200` plus `OutboxMutationResponse` when the row moves back to `pending`, `404` when the row is missing for the tenant, and `409` when the row is not currently `failed`. `POST /acx/v1/recognition/outbox/{id}/discard` returns the same response shape/status pattern for the transition to `discarded`.

### PHP: Sync Health Classification

The classifier uses persisted `last_sync_result` for offline and failure detection, and checks both curation outbox and topology command backlogs for queued state. `syncing` is excluded -- it is a transient state visible only during the POST `trigger_sync()` response, not derivable from GET. `last_sync_result` is persisted by `SyncPullJob` itself (not by `SyncStatusController`) so that all pull sites -- `trigger_sync()`, inline stale refresh, and bootstrap -- update the reachability state. A `failed` result (non-network projection error) surfaces immediately as `stale` rather than waiting for the staleness threshold, since the projection did not update `last_synced_at`.

```php
// In SyncStatusController -- computed from existing + new persisted metrics
private function classify_sync_health( array $curation_state, bool $is_stale, string $last_sync_result ): string {
    if ( 'unreachable' === $last_sync_result ) {
        return 'offline';
    }
    // A 'failed' last_sync_result (projection error, not network) surfaces as 'stale'
    // once the staleness threshold elapses. To avoid a latency window where the operator
    // sees 'healthy' despite a recent projection failure, treat 'failed' as 'stale'
    // immediately -- the projection did not update last_synced_at, so the data IS stale.
    if ( 'failed' === $last_sync_result ) {
        return 'stale';
    }
    if ( ( $curation_state['failed_curation_operations'] ?? 0 ) > 0
        || ( $curation_state['topology_commands']['failed'] ?? 0 ) > 0 ) {
        return 'failures';
    }
    if ( ( $curation_state['conflict_count'] ?? 0 ) > 0
        || ( $curation_state['topology_commands']['conflict'] ?? 0 ) > 0 ) {
        return 'conflicts';
    }
    if ( $is_stale ) {
        return 'stale';
    }
    if ( ( $curation_state['pending_curation_operations'] ?? 0 ) > 0
        || ( $curation_state['topology_commands']['pending'] ?? 0 ) > 0 ) {
        return 'queued';
    }
    return 'healthy';
}
```

### Frontend: Sync Health Type Extension

```typescript
// Extend SyncStatusResponse / SyncTriggerResponse
// Note: 'syncing' is excluded from SyncHealth -- it is only observable during
// the transient POST trigger_sync response, not from GET sync-status.
export type SyncHealth =
  | "healthy"
  | "queued"
  | "stale"
  | "conflicts"
  | "failures"
  | "offline";

export interface SyncStatusResponse {
  // ... existing fields ...
  sync_health: SyncHealth;
  last_sync_result: "ok" | "failed" | "unreachable";
}

export interface SyncTriggerResponse {
  // ... existing fields ...
  sync_health: SyncHealth;
  last_sync_result: "ok" | "failed" | "unreachable";
}
```

### Frontend: Conflict List Hook Pattern

```typescript
// New hook: useConflicts
export const useConflicts = (options?: { resolution_status?: string }) => {
  return useQuery({
    queryKey: ["acx", "conflicts", options?.resolution_status ?? "open"],
    queryFn: () =>
      apiFetch<ConflictListResponse>({
        path: `/acx/v1/recognition/conflicts?resolution_status=${options?.resolution_status ?? "open"}`,
      }),
    staleTime: 30_000,
  });
};
```

### Frontend: Conflict Resolution Action Pattern

```typescript
export type ProjectionConflictCode =
  | "curated_cluster_deleted"
  | "curated_member_deleted"
  | "member_cluster_reassignment";

// New mutation: useResolveConflict
export const useResolveConflict = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: {
      conflictId: number;
      resolution: "accepted" | "dismissed";
    }) =>
      apiFetch({
        path: `/acx/v1/recognition/conflicts/${params.conflictId}/resolve`,
        method: "POST",
        data: { resolution_status: params.resolution },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["acx", "conflicts"] });
      queryClient.invalidateQueries({ queryKey: ["acx", "sync-status"] });
    },
  });
};
```

For Phase 4, projection conflicts use the documented `conflict_code` values above. `curated_cluster_deleted` means the backend snapshot no longer contains a locally curated cluster, `curated_member_deleted` means the backend snapshot no longer contains a locally curated member, and `member_cluster_reassignment` means the backend proposes moving a curated member to a different cluster. `ConflictController` should expose these raw codes in REST responses so the frontend can map them to human-readable copy without inventing new server semantics.

### Frontend: UI State Precedence Rule

`SyncStatusIndicator` already surfaces transient pipeline states (projecting, acknowledging, trigger progress, retry affordances) with higher priority than persisted sync-status data. Phase 4's `sync_health` field must **not** replace this precedence -- it drives only the idle/post-sync visual state.

**Precedence (first match wins):**

1. `isLoading` / `isError` -- loading or unavailable (unchanged).
2. `pipelinePhase === 'projecting'` -- projecting or acknowledging results (Phase 1 pipeline lifecycle). Authoritative while a job is running.
3. `syncTrigger.isPending` -- active manual or auto trigger in progress.
4. `sync_health` discriminant -- drives idle-state badge and links: `offline`, `failures`, `conflicts`, `stale`, `queued`, `healthy`.
5. Curation detail badges (conflict count, pending count, timestamps) -- shown alongside the active state.

Transient states (2-3) override persisted `sync_health`. Tests must prove that projecting/acknowledging still display correctly even when `sync_health` is `conflicts` or `failures`.

## Functions to Change

### Plugin (WordPress)

| File                                                                                             | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`                 | Add `find_conflicts_for_tenant( string $tenant_id, string $resolution_status = 'open' )` (paginated, accepts any valid status), `find_conflict_by_id()`, `mark_resolved()`, `count_conflicts( string $tenant_id, string $resolution_status = 'open' )` public query/mutation methods.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php`         | New service. Dispatches conflict resolution per source, `operation_type`, and `conflict_code`. All entity mutations and conflict status updates within `resolve()` are wrapped in a `$wpdb` transaction (`START TRANSACTION` / `COMMIT` / `ROLLBACK`) to prevent partial state. Dependencies: `ConflictRepository`, `OutboxDrain`, `ClustersRepository`, `IdentityMembersRepository`. Outbox conflicts: joins to outbox row to read `operation_type`; gates "accept machine" to deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`); person CRUD (`person_created`, `person_updated`, `person_deleted`) and compound topology mutations (`cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) support only "keep local" (re-enqueue) in Phase 4. Accepted single-entity conflicts clear curation flags via `reset_curation()`, discard outbox row (convergence requires a subsequent sync pull, triggered by the operator via frontend "Sync Now" affordance). Projection conflicts: dispatch per `conflict_code` -- `curated_cluster_deleted` deletes the curated cluster and its members (no FK cascade, explicit cleanup required), `curated_member_deleted` deletes the curated member, `member_cluster_reassignment` updates cluster assignment and clears curation (accepted); dismissed = no entity mutation.                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`         | Add `reset_curation( string $cluster_uuid, string $tenant_id )`: sets `is_user_confirmed = 0`, clears curated label/person_id/curation_state so the next projection can overwrite. Note: the schema uses a single `is_user_confirmed` flag, so this resets ALL curated fields on that cluster -- limitation documented in terminology. Add `delete_cluster_with_members( string $cluster_uuid, string $tenant_id )` for projection conflict deletion acceptance (`curated_cluster_deleted`). This method deletes all `wp_acx_identity_members` rows referencing the cluster BEFORE deleting the cluster row itself, within the caller's transaction. Explicit member cleanup is required because the schema has no FK cascade between members and clusters. Used by `ConflictResolutionService`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | Add `reset_curation( string $identity_uuid, string $tenant_id )`: sets `is_curated = 0` so the next projection can overwrite cluster assignment. Add `delete_member( string $identity_uuid, string $tenant_id )` for projection conflict deletion acceptance. Add `accept_machine_cluster_assignment( string $identity_uuid, string $cluster_uuid, string $tenant_id )`: updates `cluster_uuid` to the machine-proposed value AND sets `is_curated = 0` in a single tenant-scoped query. This is distinct from the existing `reassign_to_cluster()` which sets `is_curated = 1` (correct for user-initiated reassignment, wrong for machine acceptance). Used by `ConflictResolutionService` for `member_cluster_reassignment` projection conflict acceptance.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`       | Already has `get_last_sync_result()` and `set_last_sync_result()`. SyncStateRepository retains its existing aggregate-only scope; dead-letter queries and mutations belong in the outbox classes. No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `apps/prototype-wp-alt-context/src/sovereign/sync/interface-sync-pull-job.php`                   | Already returns `SyncPullResult` (`ok`, `failed`, `unreachable`, `skipped`). No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`                       | Already has `SyncStateRepository` as constructor dependency and persists sync results via `set_last_sync_result()`. No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php`                            | Already adapted to `SyncPullResult` return type. No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`                         | Already has `classify_sync_health()`, `sync_health`, and `last_sync_result` in both GET and POST responses. No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php`                            | **New controller.** Owns all conflict and dead-letter REST routes: conflict list, conflict detail, conflict resolution, dead-letter list, dead-letter retry, dead-letter discard. Constructor dependencies: `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, `SyncStateRepository`. Registered in `RecognitionController` composition root alongside the existing controllers. This separates conflict management concerns from sync status reporting, avoiding the need to inflate `SyncStatusController`'s constructor with dependencies it doesn't need for its primary sync health role. The conflict list and detail responses include a server-computed `allowed_resolutions` array derived from conflict source: projection conflicts allow `['accepted', 'dismissed']`; outbox conflicts for deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) allow `['accepted', 'dismissed']`; outbox conflicts for person CRUD and compound topology operations allow only `['dismissed']`. `resolve()` consumes the structured `ConflictResolutionService` result so the controller can return `404` for missing conflicts, `409` for already-resolved conflicts, `422` for disallowed resolutions, and `500` for mutation/update failures. Dead-letter endpoints return explicit `OutboxOperation` / `OutboxListResponse` payloads and map missing/non-failed rows to `404` / `409` rather than a generic failure. |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                         | Update composition root to instantiate `ConflictController` with `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, and `SyncStateRepository`. Wire `ConflictController::register_routes()` alongside existing controller route registrations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                        | Add `find_failed_operations()` and `find_operation_by_id()` for dead-letter inspection. Add `retry_failed_operation()` (reset to pending, clear errors, reschedule drain), `discard_operation()` (mark as discarded, refresh metrics), and `re_enqueue_with_current_base()` (reset conflict row to pending with updated base version). Outbox row persistence stays in the outbox classes rather than SyncStateRepository.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                         | Already has `last_sync_result varchar(20) DEFAULT 'ok'` and `last_sync_attempted_at datetime DEFAULT NULL` columns in `wp_acx_sync_state` table definition. No Phase 4 changes needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |

### Frontend (TypeScript/React)

| File                                                                             | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts`           | `SyncHealth` type, `sync_health`, and `last_sync_result` already exist on `SyncStatusResponse` / `SyncTriggerResponse`. Add `ConflictRecord` (including `outbox_id: number` where `0` means projection conflict, and `allowed_resolutions: Array<'accepted' \| 'dismissed'>` fields), `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse`, and `OutboxMutationResponse` types. `OutboxOperation` includes `id`, `tenant_id`, `operation_type`, `entity_type`, `entity_key`, `status`, `attempts`, `last_error_code`, `last_error_message`, `created_at`, and `last_attempted_at`. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Refactor to use `sync_health` discriminant for visual states. Add actionable links: conflict count links to conflict inbox panel (`?panel=conflicts`), failed count links to dead-letter panel (`?panel=dead-letter`). Add distinct offline, queued, and failures visual states.                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`                 | Add sync health summary card showing current `sync_health` state, conflict count, failed count, and pending count with links to workbench detail panels (`?panel=conflicts`, `?panel=dead-letter`).                                                                                                                                                                                                                                                                                                                                                                                           |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx`    | Add `WorkbenchOverlay` type (`'conflicts' \| 'dead-letter' \| null`), `activeOverlay` state, and `setActiveOverlay` setter. Sync with `panel` URL query param via `useTabParam` or a new `usePanelParam` hook. This keeps the new URL-driven overlay concept distinct from the existing cluster-panel state in `Panels.tsx`.                                                                                                                                                                                                                                                                  |
| `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`                 | Render `ConflictInbox` and `DeadLetterPanel` as overlay panels when `activeOverlay` is set. Add overlay dismiss handler.                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `apps/prototype-wp-alt-context/js/admin/hooks/`                                  | Add `useConflicts` hook (paginated conflict list query), `useResolveConflict` mutation hook, `useDeadLetterOperations` hook (failed outbox query), `useRetryOperation` and `useDiscardOperation` mutation hooks.                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/`                        | Add `ConflictInbox.tsx` component: paginated list of open conflicts with entity info, conflict code, timestamps, and local-vs-machine payload side-by-side view. Add resolution actions (accept/keep/dismiss).                                                                                                                                                                                                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/`                        | Add `DeadLetterPanel.tsx` component: list of failed outbox operations with operation type, entity key, error details, attempt count. Add retry and discard actions.                                                                                                                                                                                                                                                                                                                                                                                                                           |

## Related Files

| File                                                                                     | Note                                                                                                                                                                                                                   |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`               | Outbox enqueue path. No changes needed -- Phase 4 reads from what Phase 3 writes.                                                                                                                                      |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`           | Dispatch transport. No changes needed.                                                                                                                                                                                 |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-topology-command-repository.php` | Topology command state. Currently exposes only `find_pending()` and `find_reconcilable()` queries. A topology-command panel (stretch goal) would need additional failed/conflict/detail query methods not yet present. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`           | Curation mutation entrypoint. No changes needed.                                                                                                                                                                       |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts`                          | Existing sync status hook. May need stale-time adjustment but no structural changes.                                                                                                                                   |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts`                         | Existing sync trigger mutation. No changes needed.                                                                                                                                                                     |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx`            | Workbench context provider. Extended to add overlay state (see Functions to Change).                                                                                                                                   |
| `docs/tasks/6.0/phase-3-minimal-durable-sync-replay-task-plan.md`                        | Phase 3 delivers the infrastructure Phase 4 depends on.                                                                                                                                                                |
| `docs/tasks/6.0/deferred-ux-ergonomics-post-epic-task-plan.md`                           | Routes bidirectional conflict resolution for person name edits to this phase.                                                                                                                                          |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md`      | Parent epic with Phase 4 exit criteria.                                                                                                                                                                                |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure from Phase 3)

- [x] `wp_acx_sync_conflicts` table with `resolution_status`, `resolved_at`, `machine_payload`, `local_payload` columns.
- [x] `ConflictRepository::record_conflict()` and `record_projection_conflict()` write conflict records from drain 409s and projection conflicts.
- [x] `SyncStateRepository` aggregates pending, failed, and conflict counts into `wp_acx_sync_state`.
- [x] `SyncStatusController` REST response includes `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, timestamps, and `topology_commands` status.
- [x] `SyncStatusResponse` TypeScript type includes all aggregate sync fields and `TopologyCommandStatus`.
- [x] `SyncStatusIndicator` displays conflict count badge, pending curation badge, and timestamp labels.
- [x] `OutboxDrain` handles bounded retry (max 5 attempts, no backoff delay) and dead-letter (`failed` status).
- [x] `SyncPullResult` value object (`ok`, `failed`, `unreachable`, `skipped`) and `SyncPullJobInterface` returns `SyncPullResult`.
- [x] `SyncPullJob` has `SyncStateRepository` as constructor dependency and persists sync results via `set_last_sync_result()`.
- [x] `SyncStateRepository` has `get_last_sync_result()` and `set_last_sync_result()` with `last_sync_result`/`last_sync_attempted_at` columns in `wp_acx_sync_state`.
- [x] `SyncStatusController` has `classify_sync_health()` and includes `sync_health`/`last_sync_result` in both GET and POST responses.
- [x] `ClustersController` adapted to `SyncPullResult` return type in `should_use_local_projection()` and `maybe_bootstrap_after_proxy_read()`.
- [x] `SyncHealth` TypeScript type and `sync_health`/`last_sync_result` fields in `SyncStatusResponse` and `SyncTriggerResponse`.

## Phase 0: Scaffolding

- [x] Add REST route registrations for conflict list, conflict detail, conflict resolution, dead-letter list, dead-letter retry, and dead-letter discard in new `ConflictController` (not `SyncStatusController`).
- [x] Add `ConflictController` scaffold: constructor accepting `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, `SyncStateRepository`. Register route stubs returning `501 Not Implemented`.
- [x] Update `RecognitionController` composition root to instantiate `ConflictController` and call `register_routes()`.
- [x] `SyncPullJobInterface` already returns `SyncPullResult` (`ok`, `failed`, `unreachable`, `skipped`). Pre-existing.
- [x] `SyncPullResult` value object already exists. Pre-existing.
- [x] `SyncPullJob` already has `SyncStateRepository` as constructor dependency. Pre-existing.
- [x] `ClustersController` already adapted to `SyncPullResult`. Pre-existing.
- [x] Add `ConflictRepository` method signatures: `find_conflicts_for_tenant( string $tenant_id, string $resolution_status = 'open' )`, `find_conflict_by_id()`, `mark_resolved()`, `count_conflicts( string $tenant_id, string $resolution_status = 'open' )`.
- [x] Add `ConflictResolutionService` scaffold for source-aware resolution dispatch.
- [x] `SyncStateRepository` already has `get_last_sync_result()` and `set_last_sync_result()`. Pre-existing.
- [x] Add `OutboxDrain` method signatures: `find_failed_operations()`, `find_operation_by_id()`, `retry_failed_operation()`, `discard_operation()`, `re_enqueue_with_current_base()`.
- [x] Add `ClustersRepository` method signature: `reset_curation()`, `delete_cluster_with_members()`.
- [x] Add `IdentityMembersRepository` method signature: `reset_curation()`, `delete_member()`, `accept_machine_cluster_assignment()`.
- [x] `wp_acx_sync_state` already has `last_sync_result` and `last_sync_attempted_at` columns. Pre-existing.
- [x] Add TypeScript type stubs: `ConflictRecord` (with `outbox_id: number` where `0` = projection conflict, and `allowed_resolutions: Array<'accepted' | 'dismissed'>` fields), `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse`, `OutboxMutationResponse`, conflict resolution request/response types, and `WorkbenchOverlay` state types. (`SyncHealth`, `sync_health`, and `last_sync_result` already exist on the sync types.)
- [x] Define/document the Phase 4 projection `conflict_code` contract: `curated_cluster_deleted`, `curated_member_deleted`, `member_cluster_reassignment`. Reuse the raw server codes in REST/TypeScript types so the frontend can map them to operator copy consistently.
- [x] Create React component file stubs: `ConflictInbox.tsx`, `DeadLetterPanel.tsx` with `NotImplementedError` placeholder renders.
- [x] Create hook file stubs: `useConflicts.ts`, `useResolveConflict.ts`, `useDeadLetterOperations.ts`, `useRetryOperation.ts`, `useDiscardOperation.ts`.
- [x] Create PHPUnit test scaffolding for conflict query, resolution, and dead-letter endpoints.
- [x] Create Vitest test scaffolding for conflict inbox, dead-letter panel, and sync health indicator states.
- [x] Verify scaffolds compile: `cd apps/prototype-wp-alt-context && composer phpstan` and `cd apps/prototype-wp-alt-context && npm run typecheck`.

## Phase 1: PHP -- Conflict Query and Resolution API

- [x] Implement `ConflictRepository::find_conflicts_for_tenant()`: paginated query accepting a `resolution_status` filter (default `'open'`), returning conflicts ordered by `created_at DESC`. Query includes `outbox_id` column so the controller can derive `allowed_resolutions`.
- [x] Implement `ConflictRepository::find_conflict_by_id()`: single conflict with full payload fields, tenant-scoped.
- [x] Implement `ConflictRepository::mark_resolved()`: update `resolution_status` and `resolved_at`, tenant-scoped. Valid transitions: `open` to `accepted`, `dismissed`. Does not reconcile entity state -- that is the resolution service's job.
- [x] Implement `ConflictRepository::count_conflicts()`: count query accepting a `resolution_status` filter (default `'open'`) for pagination headers.
- [x] Keep projection `conflict_code` values as explicit API contract in conflict list/detail responses: `curated_cluster_deleted`, `curated_member_deleted`, `member_cluster_reassignment`. Do not rename them per-endpoint; the frontend maps these stable codes to human-readable labels.
- [x] Implement `ConflictResolutionService::resolve()`: dispatch per source, `operation_type`, and `conflict_code`. Return a structured result (`success`, `not_found`, `already_resolved`, `resolution_not_allowed`, `entity_mutation_failed`, `conflict_update_failed`) instead of `bool` so `ConflictController` can map to correct HTTP statuses. Wrap all entity mutations and conflict status updates in a `$wpdb` transaction (`START TRANSACTION` / `COMMIT` / `ROLLBACK`). Every return path after `START TRANSACTION` must issue `ROLLBACK` first; intermediate mutation results (`clear_curation_for_entity`, `discard_operation`, `re_enqueue_with_current_base`, `resolve_projection_accepted`) must be checked and must abort with `ROLLBACK` on failure before reaching `mark_resolved` or `COMMIT`. Join to outbox row via `outbox_id` to read `operation_type`. Gate outbox "accept machine" to deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`); `ROLLBACK` and return `resolution_not_allowed` for person CRUD and compound topology mutations (`person_created`, `person_updated`, `person_deleted`, `cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) -- these only support "keep local" (re-enqueue). Accepted single-entity outbox conflicts: clear curation flags on entity via `reset_curation()`, discard outbox row (convergence on next sync pull -- operator triggers via frontend). Outbox conflict dismissed = re-enqueue with updated base version (available for all operation types). Projection conflict accepted = dispatch per `conflict_code`: `curated_cluster_deleted` deletes the curated cluster row and its member rows (no FK cascade, explicit cleanup required); `curated_member_deleted` deletes the curated member row; `member_cluster_reassignment` updates member's `cluster_uuid` to machine-proposed value and clears `is_curated`. Projection conflict dismissed = no entity mutation.
- [x] Implement conflict endpoints in `ConflictController`: `GET /acx/v1/recognition/conflicts` (paginated list with `resolution_status` filter param -- response includes `outbox_id` and computed `allowed_resolutions` per row), `GET /acx/v1/recognition/conflicts/{id}` (detail with decoded payloads, `outbox_id`, and `allowed_resolutions`), `POST /acx/v1/recognition/conflicts/{id}/resolve` (accepts `resolution_status` (`accepted` | `dismissed`), validates against `allowed_resolutions` server-side, calls `ConflictResolutionService::resolve()`, refreshes sync state metrics). Permission: `manage_options`. The `allowed_resolutions` array is derived per row: projection conflicts (`outbox_id = 0`) -> `['accepted', 'dismissed']`; outbox conflicts with deterministic single-row `operation_type` (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) -> `['accepted', 'dismissed']`; outbox conflicts with person CRUD or compound topology `operation_type` -> `['dismissed']`. For outbox conflicts, the controller joins to the outbox row via `OutboxDrain::find_operation_by_id()` to read `operation_type`. `resolve()` result mapping is explicit: `not_found` -> `404`, `already_resolved` -> `409`, `resolution_not_allowed` -> `422`, mutation/update failures -> `500`.
- [x] Implement `OutboxDrain::discard_operation()`: mark outbox row as `discarded` (new status value -- not present in current codebase), refresh metrics. Tenant-scoped, only operates on `conflict` or `failed` rows.
- [x] Implement `OutboxDrain::re_enqueue_with_current_base()`: reset outbox row to `pending` with `attempts = 0`, update `expected_base_version` to given value, reschedule drain. Tenant-scoped, only operates on `conflict` rows.
- [x] Implement `ClustersRepository::reset_curation()`: set `is_user_confirmed = 0`, clear curated label/person_id/curation_state for a given cluster_uuid. Used by outbox conflict acceptance.
- [x] Implement `ClustersRepository::delete_cluster_with_members()`: delete all member rows referencing the cluster_uuid (`DELETE FROM wp_acx_identity_members WHERE cluster_uuid = %s AND tenant_id = %s`), then delete the cluster row itself. Runs within the caller's transaction. Explicit member cleanup is required because the schema has no FK cascade. Used by projection conflict acceptance (`curated_cluster_deleted`).
- [x] Implement `IdentityMembersRepository::reset_curation()`: set `is_curated = 0` for a given identity_uuid. Used by outbox conflict acceptance.
- [x] Implement `IdentityMembersRepository::delete_member()`: delete a member row by identity_uuid. Used by projection conflict acceptance (`curated_member_deleted`).
- [x] Implement `IdentityMembersRepository::accept_machine_cluster_assignment()`: update `cluster_uuid` to machine-proposed value AND set `is_curated = 0`, tenant-scoped. Distinct from existing `reassign_to_cluster()` which sets `is_curated = 1` for user-initiated reassignment. Used by projection conflict acceptance (`member_cluster_reassignment`).
- [x] Implement `OutboxDrain::find_operation_by_id()`: single outbox operation detail, tenant-scoped. Required by `ConflictResolutionService::resolve()` to look up `operation_type` for acceptance gating.
- [ ] Add PHPUnit tests: conflict list returns open conflicts ordered by date with `outbox_id` and `allowed_resolutions`; `allowed_resolutions` is `['accepted', 'dismissed']` for projection conflicts, `['accepted', 'dismissed']` for deterministic single-row outbox conflicts, and `['dismissed']` for person CRUD plus compound topology outbox conflicts; conflict detail returns decoded payloads with `allowed_resolutions`; resolve endpoint maps `not_found` to `404`, already-resolved conflicts to `409`, disallowed resolutions to `422`, and mutation/update failures to `500`; outbox conflict accepted for single-row cluster/member operations clears curation flags (`is_user_confirmed`/`is_curated` reset), discards outbox row (verify the next manual sync can converge the projection to machine state -- resolution does NOT trigger sync automatically); outbox conflict accepted for person CRUD or compound topology operation (`person_updated`, `cluster_merged` etc.) returns `422`; outbox conflict dismissed re-enqueues with updated base version across supported operation families; projection conflict accepted dispatches per conflict_code -- `curated_cluster_deleted` deletes cluster and its member rows (no FK cascade, explicit cleanup), `curated_member_deleted` deletes member, `member_cluster_reassignment` updates cluster assignment and clears curation; projection conflict dismissed preserves local state; resolution rejects invalid status transitions; tenant isolation is enforced.

## Phase 2: PHP -- Dead-Letter Query and Management API

- [x] Implement `OutboxDrain::find_failed_operations()`: paginated query for `status = 'failed'` outbox rows with operation type, entity key, error details, attempt count. Outbox row persistence stays in the outbox classes.
- [x] Implement `OutboxDrain::retry_failed_operation()`: reset `status` to `pending`, `attempts` to `0`, clear error fields, refresh curation metrics immediately, and reschedule drain. Tenant-scoped, only operates on `failed` rows.
- [x] Implement dead-letter endpoints in `ConflictController`: `GET /acx/v1/recognition/outbox/failed` (paginated `OutboxListResponse` with `items`, `total`, `limit`, `offset`), `POST /acx/v1/recognition/outbox/{id}/retry` (returns `200` plus `OutboxMutationResponse` with updated `operation`; `404` for missing tenant-scoped row; `409` for non-failed row), `POST /acx/v1/recognition/outbox/{id}/discard` (same response shape/status mapping for the transition to `discarded`, refreshes metrics). Permission: `manage_options`.
- [x] Add PHPUnit tests: dead-letter list returns failed operations with full error details and documented fields; retry resets operation to pending, refreshes metrics immediately, and triggers drain; discard marks operation and updates metrics; endpoints return `404` for missing tenant-scoped rows and `409` for non-failed rows; operations scoped to tenant.

## Phase 3: PHP -- Sync Health Classification (Already Implemented)

All sync health classification infrastructure was delivered in a prior phase. No Phase 4 work is needed.

- [x] `classify_sync_health()` private method in `SyncStatusController`. Pre-existing.
- [x] `SyncStateRepository::get_last_sync_result()` and `set_last_sync_result()`. Pre-existing.
- [x] `SyncPullJob` result persistence (`unreachable`, `failed`, `ok`; cooldown returns `skipped` without overwriting). Pre-existing.
- [x] `SyncStatusController::trigger_sync()` reads `last_sync_result` from `SyncStateRepository`. Pre-existing.
- [x] `sync_health` and `last_sync_result` fields in `get_sync_status()` REST response. Pre-existing.
- [x] `sync_health` and `last_sync_result` fields in `trigger_sync()` REST response. Pre-existing.
- [x] PHPUnit tests for sync health classification. Pre-existing.

## Phase 4: Frontend -- Sync Health Indicator Upgrade

- [x] `SyncHealth` union type, `sync_health`, and `last_sync_result` already exist in `SyncStatusResponse` and `SyncTriggerResponse` TypeScript types. Pre-existing.
- [x] Refactor `SyncStatusIndicator` to use `sync_health` as the **idle-state** visual discriminant. Preserve the existing transient-state precedence: `pipelinePhase === 'projecting'` (projecting/acknowledging) and `syncTrigger.isPending` (active trigger) remain authoritative while a job is running. `sync_health` only drives the badge and links when no transient operation is active. This avoids regressing the Phase 1 unified pipeline lifecycle indicators.
- [x] Add distinct visual states for `offline` (error styling, manual retry), `failures` (warning styling, link to dead-letter panel), `conflicts` (warning styling, link to conflict inbox), `queued` (info styling with pending count -- includes both curation and topology command backlogs), `stale` (warning with sync-now), `healthy` (success). For `failures` and `conflicts` states, show total counts (conflict count, failed count) linked to their respective panels. The current storage model aggregates all open conflicts via `SyncStateRepository::get_conflict_count()` without distinguishing curation-outbox from topology-command sources, so no per-source breakdown is attempted. Topology command pending/failed/conflict counts from `topology_commands` are shown as a separate informational line when non-zero.
- [x] Make conflict count badge clickable/linked to conflict inbox panel (`?panel=conflicts`).
- [x] Make failed count badge clickable/linked to dead-letter panel (`?panel=dead-letter`).
- [x] Add sync health summary card to `DashboardPage`: compact display of current health state, conflict count, failed count, pending count, with links to workbench panels (`?panel=conflicts`, `?panel=dead-letter`). Topology command pending/failed/conflict counts are shown as a separate informational line when non-zero.
- [x] Add `WorkbenchOverlay` type (`'conflicts' | 'dead-letter' | null`) to `WorkbenchContext`. Add `activeOverlay` state synced with `panel` URL query param. Add `setActiveOverlay` setter.
- [x] Render `ConflictInbox` and `DeadLetterPanel` as overlay panels in `WorkbenchPage` when `activeOverlay` is set. Add dismiss handler that clears the `panel` query param.
- [x] Add Vitest tests: each `sync_health` value renders the correct visual state when idle (no transient operation active); transient states (projecting, acknowledging, trigger pending) override `sync_health` badges even when sync_health is `conflicts` or `failures`; conflict badge links to `?panel=conflicts`; failed badge links to `?panel=dead-letter`; dashboard card renders correct summary with panel links; `WorkbenchOverlay` state syncs with URL query param; topology command counts render as a separate informational line when non-zero.

## Phase 5: Frontend -- Conflict Inbox

- [x] Implement `useConflicts` hook: paginated query for `GET /acx/v1/recognition/conflicts` with `resolution_status` filter, React Query config.
- [x] Implement `useResolveConflict` mutation hook: `POST /acx/v1/recognition/conflicts/{id}/resolve`, invalidates conflict and sync-status queries on success.
- [x] Implement `ConflictInbox` component: paginated list of open conflicts. Each row shows entity type, entity key (with cluster label if available), conflict code (human-readable), created timestamp.
- [x] Add conflict detail expansion or modal: side-by-side comparison of `machine_payload` (what backend proposed) vs `local_payload` (what operator curated). Highlight differing fields.
- [x] Add resolution actions per conflict, driven by the `allowed_resolutions` field from the REST response (no client-side operation-type classification needed). If `allowed_resolutions` includes `'accepted'`, show "Accept machine version"; if it includes `'dismissed'`, show "Keep local version". Projection conflicts: `allowed_resolutions` is `['accepted', 'dismissed']` -- show both actions. For `curated_cluster_deleted` projection conflicts, the acceptance confirmation must note that accepting the machine version deletes the cluster and all member rows still attached to it (show the affected member count when available). Outbox conflicts for deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) use `['accepted', 'dismissed']`. For cluster outbox conflicts, the acceptance confirmation must warn that ALL curated fields on the cluster will be reset (label, person assignment, dismissal state) due to the single `is_user_confirmed` flag. Outbox conflicts for person CRUD and compound topology operations use `['dismissed']` only; show an explanation that Phase 4 supports re-enqueue/retry for those operations but not machine acceptance because the overwrite/delete contract is not yet defined. Show confirmation before action.
- [x] Add empty state for zero conflicts.
- [x] Wire `ConflictInbox` into workbench navigation: rendered as overlay panel when `activeOverlay === 'conflicts'`. Accessible from `SyncStatusIndicator` conflict badge link and `DashboardPage` summary card.
- [x] After successful conflict resolution, show a "Sync Now" affordance (reuse existing `useSyncTrigger`) so the operator can trigger convergence to the machine state immediately. Resolution itself does not trigger a sync -- the `ConflictResolutionService` clears curation and discards the outbox row, but the next projection (via sync pull) is what actually converges the entity.
- [x] Add Vitest tests: conflict list renders with correct data; resolution actions are driven by `allowed_resolutions` (buttons present/absent match server-provided array); compound topology conflicts show only "Keep local" with explanation; empty state renders; loading and error states handled; "Sync Now" affordance appears after successful resolution.

## Phase 6: Frontend -- Dead-Letter Management Panel

- [x] Implement `useDeadLetterOperations` hook: paginated query for `GET /acx/v1/recognition/outbox/failed`, React Query config.
- [x] Implement `useRetryOperation` mutation hook: `POST /acx/v1/recognition/outbox/{id}/retry`, invalidates dead-letter and sync-status queries on success.
- [x] Implement `useDiscardOperation` mutation hook: `POST /acx/v1/recognition/outbox/{id}/discard`, invalidates dead-letter and sync-status queries on success.
- [x] Implement `DeadLetterPanel` component: list of failed outbox operations. Each row shows operation type (human-readable), entity key, attempt count, last error code, last error message, last attempted timestamp.
- [x] Add per-operation actions: "Retry" (resets to pending), "Discard" (marks discarded). Show confirmation before discard.
- [x] Add empty state for zero failed operations.
- [x] Wire `DeadLetterPanel` into workbench navigation: rendered as overlay panel when `activeOverlay === 'dead-letter'`. Accessible from `SyncStatusIndicator` failed badge link.
- [x] Add Vitest tests: dead-letter list renders with correct data; retry calls correct endpoint and shows success; discard calls correct endpoint; empty state renders.

## Phase 7: Integration Tests

- [x] PHPUnit integration test: create conflict via projection, query via REST, resolve via REST, verify sync state metrics update.
- [x] PHPUnit integration test: create failed outbox operation, query via dead-letter REST, retry via REST, verify operation resets to pending and drain is rescheduled.
- [x] PHPUnit integration test: sync health classification returns correct values across all state combinations.
- [x] Vitest integration test: `SyncStatusIndicator` renders all `sync_health` states correctly with real sync status data shapes. Panel navigation links resolve to correct `panel` query params.
- [ ] All PHPUnit, PHPStan, Vitest, and ESLint checks pass.

## Stretch Goals

- [x] Topology command status panel (surface `wp_acx_topology_commands` pending/failed/conflict state alongside outbox dead-letter).
- [x] Conflict resolution preview: show what the entity would look like after accepting the machine version before committing.
- [x] Outbox operation timeline: full history view showing all operations (not just failed) with status transitions.
- [x] Batch conflict resolution: select multiple conflicts and resolve them in one action.
- Remaining compound topology acceptance follow-on (`cluster_merged`), plus export/purge controls and operator-visible audit history, are now tracked in [Phase 5](phase-5-retention-export-and-audit-controls-task-plan.md).

## Success Criteria

- [ ] Operators can distinguish offline, stale, queued, conflicted, failed, and healthy sync states from the workbench and dashboard without database access.
- [ ] Operators can view a list of open conflicts, inspect local-vs-machine payload differences, and resolve each conflict through a source-aware workflow that reconciles the underlying projection or outbox state.
- [ ] Operators can view failed outbox operations with error details, retry individual operations, or discard them.
- [ ] Sync health badge on the dashboard provides at-a-glance status with links to detail views.
- [ ] Dashboard and sync badge links open stable workbench overlay panels via the `panel` query parameter.
- [ ] Resolving all conflicts and retrying/discarding all dead-letter operations returns the sync health indicator to `healthy` when no stale/offline/topology backlog remains. Topology-command backlogs are visible as a separate informational line in the health badge even though detailed inspection/management requires the stretch-goal topology-command panel.
- [ ] All PHPUnit, PHPStan, Vitest, and ESLint checks pass.

## Out of Scope

- **Export and purge endpoints**: depend on backend tenant policy fields (`retention_mode`, audit event tables) that do not exist yet. They belong to Phase 5 (Retention, Export, Purge) in the parent epic.
- **Delta ingest**: tracked in deferred/post-v0.2.0 scope. Phase 4 works with existing snapshot-based sync.
- **Backend-authored machine proposals for person names**: this is the only part of person-name conflict handling that remains out of scope. Phase 4 still owns the operator-facing conflict inbox, person-side outbox conflict review, and UI affordances for person-name drift, matching the routing in [deferred-ux-ergonomics-post-epic-task-plan.md](/Users/daniel/Development/context-alt-text-monorepo/docs/tasks/6.0/deferred-ux-ergonomics-post-epic-task-plan.md). What remains out of scope is new backend proposal generation/storage (`machine_proposals` table or equivalent) for machine-authored person-name suggestions, which still needs a separate follow-on once that backend contract exists.
- **Admin retry controls for topology commands**: topology command retry/discard follows the same pattern as outbox dead-letter but is listed as stretch because `TopologyCommandRepository` currently exposes only `find_pending()` and `find_reconcilable()` -- failed/conflict/detail query methods would still need to be added.
