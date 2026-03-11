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
- **Offline**: the backend recognition service is unreachable. Determined from persisted `last_sync_result` field in `wp_acx_sync_state`: when the most recent sync attempt failed with a network/connection error, the service is considered offline until the next successful sync. `SyncPullJob` persists this result after every real sync attempt (including `trigger_sync()`, inline stale refresh, and bootstrap pulls) so that subsequent GET requests can derive the offline state without a live probe. This requires expanding `SyncPullJobInterface` to return a structured `SyncPullResult` (`ok` | `failed` | `unreachable` | `skipped`) instead of `bool`, and injecting `SyncStateRepository` into `SyncPullJob` so it can write the result directly. The `skipped` value covers the cooldown short-circuit in `perform()` -- when a cooldown transient is active, no fetch is attempted and `last_sync_result`/`last_sync_attempted_at` must NOT be overwritten (the previous attempt's result remains authoritative).
- **Conflict resolution**: the operator reviews a machine proposal vs. local curation and chooses to accept the machine version or keep the local version. Resolution is not just a status flag update -- it must reconcile the underlying local/backend divergence per conflict source:
  - **Outbox conflict resolution (accept machine)**: available only where Phase 4 can reconcile the local row deterministically. Supported **single-row operations** are `cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, and `cluster_person_unbound`. The resolution service joins to the outbox row via `outbox_id` to read `operation_type` and gates acceptance. For accepted cluster/member conflicts: clear the curation flags on the affected entity (`is_user_confirmed = 0` for clusters, `is_curated = 0` for members), discard the conflicted outbox row, and mark the conflict `accepted`. Convergence to the machine state requires a subsequent sync pull; the resolution service does not trigger this automatically -- the frontend should show a "Sync Now" affordance after successful resolution (reusing `useSyncTrigger`). The curation flag reset is required because the projection's `ON DUPLICATE KEY UPDATE` guards preserve curated rows. **Cluster curation caveat**: the schema uses a single `is_user_confirmed` flag that guards label, person_id, and curation_state jointly, so accepting any cluster outbox conflict resets ALL curated fields on that cluster (not just the conflicting field). The UI must warn the operator which curated fields will be lost. **Person CRUD and compound topology operations** (`person_created`, `person_updated`, `person_deleted`, `cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) do not get "accept machine" in Phase 4 because they need either person-level overwrite/delete contracts or multi-entity revert contracts that are not yet defined. For those conflicts, only "keep local" (re-enqueue) is offered. Per-operation acceptance is a follow-on or stretch goal.
  - **Outbox conflict resolution (keep local)**: re-enqueue the outbox operation with the current `backend_version` as the new `expected_base_version`, mark the conflict `dismissed`, and let the next drain attempt replay the curation against the updated base. Column-level: the outbox row's `status` resets from `conflict` to `pending`, `attempts` resets to `0`, `expected_base_version` is set to the conflict's `backend_version`, and error fields are cleared. The conflict row's `resolution_status` transitions to `dismissed`. The original outbox row (same `id`) is mutated in place -- no new row is created.
  - **Projection conflict resolution (accept machine)**: dispatch per `conflict_code` since machine_payload content varies by conflict type (deletion conflicts store only sentinel data like `{status: 'missing_from_snapshot'}`, not full replacement state). For `curated_cluster_deleted`: delete the curated cluster row (the machine says it no longer exists). For `curated_member_deleted`: delete the curated member row. For `member_cluster_reassignment`: update the member's `cluster_uuid` to the machine-proposed value and set `is_curated = 0` via `accept_machine_cluster_assignment()` (distinct from the existing `reassign_to_cluster()` which sets `is_curated = 1` for user-initiated reassignment). Mark the conflict `accepted` after entity mutation.
  - **Projection conflict resolution (keep local)**: mark the conflict `dismissed` with no entity mutation. The local curated state is preserved and the machine proposal is discarded.

## Current State Analysis

- `SyncStatusIndicator` shows coarse states: syncing, stale+retry, fresh, unavailable. It displays conflict count and pending curation as badge text but is not a link or actionable control.
- `DashboardPage` shows library coverage, identity stats, quick actions, and job history. No sync health or conflict indicators exist on the dashboard.
- `SyncStatusResponse` TypeScript type already includes `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, `last_curation_conflict_at`, `last_curation_failed_at`, and `topology_commands` (pending/applied/failed/conflict). The data contract is already rich enough for Phase 4 summary indicators.
- `ConflictRepository` can `record_conflict()` and `record_projection_conflict()` but has no public query methods for listing, filtering, or resolving conflicts. Only the private `find_open_projection_conflict()` method exists.
- `SyncStateRepository` provides aggregate counts (`get_pending_curation_operations`, `get_conflict_count`, `get_failed_curation_operations`) but no detail queries for individual operations or conflicts.
- `OutboxDrain` handles retry with exponential backoff (max 5 attempts) and marks dead-letter operations as `failed`. No manual retry mechanism exists.
- `SyncStatusController` exposes `GET /acx/v1/recognition/sync-status` and `POST /acx/v1/recognition/sync/trigger` but no conflict list/detail/resolution endpoints, no outbox operation list, and no dead-letter retry endpoint. Its constructor accepts only `SyncStateRepositoryInterface` and `SyncPullJobInterface`; conflict and dead-letter routes need their own controller to avoid inflating this constructor.
- `SyncPullJobInterface` defines `perform(string $tenant_id): bool` and `perform_bypass_cooldown(string $tenant_id): bool`. The `bool` return type cannot distinguish between failure kinds (network unreachable vs. projection error), which blocks offline detection at pull sites outside `trigger_sync()` (inline stale refresh in `ClustersController::should_use_local_projection()`, bootstrap in `maybe_bootstrap_after_proxy_read()`).
- `SyncPullJob` does not persist sync results. The `do_sync()` method catches errors internally and returns `true`/`false` but writes nothing to `wp_acx_sync_state`. No reachability data survives for the GET status endpoint to derive offline state from.
- `wp_acx_sync_conflicts` table schema has `resolution_status` (`open` default) and `resolved_at` columns but no resolution infrastructure writes to them.
- `wp_acx_sync_outbox` has `status`, `attempts`, `last_error_code`, `last_error_message` columns that Phase 4 needs to surface.
- Person CRUD and cluster-person binding (`person_created`, `person_updated`, `person_deleted`, `cluster_person_bound`, `cluster_person_unbound`) already use the same outbox/conflict path delivered in earlier phases, so Phase 4 must give those conflicts an operator-visible resolution path even where "accept machine" remains out of scope.
- The deferred UX ergonomics document routes the **operator-facing person-name conflict UX foundation** to this phase, but backend-authored machine proposal generation for person names is still a separate follow-on dependency.

## Proposed Solution

Build Phase 4 in five layers, each independently testable:

1. **PHP: Conflict and outbox query/resolution API.** Add REST endpoints for listing conflicts, viewing conflict detail, resolving conflicts, listing dead-letter operations, and retrying or discarding dead-letter entries. Extend `ConflictRepository` with query and resolution methods. Extend `OutboxDrain` with dead-letter query, retry, and discard methods (outbox row persistence stays in the existing outbox classes, not in `SyncStateRepository` which owns only aggregate sync-state reads/writes).

2. **PHP: Sync status enrichment.** Extend `wp_acx_sync_state` with `last_sync_result` (`ok` | `failed` | `unreachable`) and `last_sync_attempted_at` timestamp, persisted by `SyncPullJob` after every real sync attempt (not just `trigger_sync()` -- also inline stale refresh and bootstrap pulls from `ClustersController`). This requires expanding `SyncPullJobInterface` to return a structured `SyncPullResult` (`ok` | `failed` | `unreachable` | `skipped`) instead of `bool` so callers can distinguish failure kinds and cooldown short-circuits, and injecting `SyncStateRepository` into `SyncPullJob` as a new constructor dependency. The `skipped` result covers `perform()`'s cooldown gate: no fetch was attempted, so `last_sync_result`/`last_sync_attempted_at` remain unchanged. Existing call sites (`ClustersController`, `SyncStatusController`) must adapt to the structured return type. Extend the sync status REST response with a computed `sync_health` field that classifies the overall state as `healthy`, `queued`, `stale`, `conflicts`, `failures`, or `offline`. The `sync_health` enum is limited to states that can be derived from the persisted GET payload; `syncing` is deliberately excluded because active-sync progress is only observable on the transient POST response. The classifier incorporates both curation outbox and topology command backlogs when determining `queued` state.

3. **Frontend: Sync health indicators.** Upgrade `SyncStatusIndicator` to surface the `sync_health` classification with distinct visual states and actionable links. When `sync_health` is `conflicts` or `failures`, the indicator must show a count breakdown distinguishing curation sync sources from topology-command sources (e.g., "3 conflicts (2 sync, 1 topology)") so operators know what contributes to the health state. Curation sync counts link to the conflict inbox / dead-letter panel; topology-command counts are informational-only until the stretch-goal topology-command panel is built. Add a condensed sync health badge to `DashboardPage` with the same source breakdown. Wire conflict count and failed count badges as navigation links to the detail views via the workbench panel contract defined below.

4. **Frontend: Conflict inbox and dead-letter management.** Add a conflict list component showing open conflicts with entity type, entity key, conflict code, timestamps, and local-vs-machine payload comparison. Add resolution actions (accept machine, keep local). Add a dead-letter list showing failed outbox operations with error details, and retry/discard actions.

5. **Frontend: Navigation contract.** Conflict inbox and dead-letter panel are rendered as overlay panels within the workbench, activated by a `panel` query parameter (`?panel=conflicts` or `?panel=dead-letter`). This avoids extending the existing `WorkbenchTab` type (`scan | batch | confirm`) which controls the primary workflow tabs. Panels overlay the active tab content and are dismissible. `WorkbenchContext` gains a `activePanel: WorkbenchPanel | null` state and `setActivePanel` setter. `SyncStatusIndicator` badges and `DashboardPage` links navigate to the workbench with the appropriate `panel` query param.

Retention/export/purge endpoints are explicitly out of scope for this task plan. The epic lists them as Phase 5 deliverables (Retention, Export, Purge), not Phase 4. They depend on backend tenant policy infrastructure that does not exist yet (no retention mode fields, no audit event tables). They should be scoped as a separate task plan once backend policy fields land.

## Patterns to Follow

### PHP: Conflict Query Pattern

```php
// In ConflictRepository -- new public query method
public function find_open_conflicts_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
    global $wpdb;
    return $wpdb->get_results(
        $wpdb->prepare(
            'SELECT id, entity_type, entity_key, conflict_code, backend_version, local_revision,
                    machine_payload, local_payload, resolution_status, outbox_id, created_at
             FROM %i WHERE tenant_id = %s AND resolution_status = %s
             ORDER BY created_at DESC LIMIT %d OFFSET %d',
            $this->table_name, $tenant_id, 'open', $limit, $offset
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
public function resolve( int $conflict_id, string $resolution, string $tenant_id ): bool {
    global $wpdb;
    $conflict = $this->conflict_repo->find_conflict_by_id( $conflict_id, $tenant_id );
    if ( ! $conflict || $conflict['resolution_status'] !== 'open' ) {
        return false;
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
                return false; // Compound topology conflicts only support 'keep local' in Phase 4.
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
        return false;
    }

    $marked = $this->conflict_repo->mark_resolved( $conflict_id, $resolution, $tenant_id );
    if ( ! $marked ) {
        $wpdb->query( 'ROLLBACK' );
        return false;
    }
    $wpdb->query( 'COMMIT' );
    return true;
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
        'curated_cluster_deleted'      => $this->clusters_repo->delete_cluster(
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
        OutboxDrain::maybe_schedule_drain();
    }
    return $updated !== false;
}
```

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

| File                                                                                             | Change                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`                 | Add `find_open_conflicts_for_tenant()`, `find_conflict_by_id()`, `mark_resolved()`, `count_open_conflicts()` public query/mutation methods.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php`         | New service. Dispatches conflict resolution per source, `operation_type`, and `conflict_code`. All entity mutations and conflict status updates within `resolve()` are wrapped in a `$wpdb` transaction (`START TRANSACTION` / `COMMIT` / `ROLLBACK`) to prevent partial state. Dependencies: `ConflictRepository`, `OutboxDrain`, `ClustersRepository`, `IdentityMembersRepository`. Outbox conflicts: joins to outbox row to read `operation_type`; gates "accept machine" to deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`); person CRUD (`person_created`, `person_updated`, `person_deleted`) and compound topology mutations (`cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) support only "keep local" (re-enqueue) in Phase 4. Accepted single-entity conflicts clear curation flags via `reset_curation()`, discard outbox row (convergence requires a subsequent sync pull, triggered by the operator via frontend "Sync Now" affordance). Projection conflicts: dispatch per `conflict_code` -- `curated_cluster_deleted` deletes the curated cluster, `curated_member_deleted` deletes the curated member, `member_cluster_reassignment` updates cluster assignment and clears curation (accepted); dismissed = no entity mutation. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`         | Add `reset_curation( string $cluster_uuid, string $tenant_id )`: sets `is_user_confirmed = 0`, clears curated label/person_id/curation_state so the next projection can overwrite. Note: the schema uses a single `is_user_confirmed` flag, so this resets ALL curated fields on that cluster -- limitation documented in terminology. Add `delete_cluster( string $cluster_uuid, string $tenant_id )` for projection conflict deletion acceptance. Used by `ConflictResolutionService`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | Add `reset_curation( string $identity_uuid, string $tenant_id )`: sets `is_curated = 0` so the next projection can overwrite cluster assignment. Add `delete_member( string $identity_uuid, string $tenant_id )` for projection conflict deletion acceptance. Add `accept_machine_cluster_assignment( string $identity_uuid, string $cluster_uuid, string $tenant_id )`: updates `cluster_uuid` to the machine-proposed value AND sets `is_curated = 0` in a single tenant-scoped query. This is distinct from the existing `reassign_to_cluster()` which sets `is_curated = 1` (correct for user-initiated reassignment, wrong for machine acceptance). Used by `ConflictResolutionService` for `member_cluster_reassignment` projection conflict acceptance.                                                                                                                                                                                                                                                                                                                                                                                                          |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`       | Add `get_last_sync_result()` and `set_last_sync_result()` for persisted reachability state. SyncStateRepository retains its existing aggregate-only scope; dead-letter queries and mutations belong in the outbox classes.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/sync/interface-sync-pull-job.php`                   | Change return type of `perform(string $tenant_id)` and `perform_bypass_cooldown(string $tenant_id)` from `bool` to `SyncPullResult` (new enum/value object: `ok`, `failed`, `unreachable`, `skipped`). `skipped` covers `perform()`'s cooldown short-circuit where no fetch is attempted. This allows callers to distinguish failure kinds for offline detection and to recognize non-attempt early returns.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`                       | Add `SyncStateRepository` as a constructor dependency. After each real sync attempt (`do_sync()`), persist the result via `set_last_sync_result()`: network errors from `SnapshotClient::fetch_snapshot()` map to `unreachable`; projection failures (before acknowledgement) map to `failed`; successful local projection maps to `ok` **even if acknowledgement fails** (acknowledgement is coordination metadata only -- existing semantics must be preserved). `perform()`'s cooldown short-circuit returns `SyncPullResult::skipped` and must NOT overwrite `last_sync_result` or `last_sync_attempted_at` (no fetch was attempted, so the previous result stays authoritative). Return `SyncPullResult` instead of `bool`. Update `perform()` and `perform_bypass_cooldown()` signatures to match the expanded interface.                                                                                                                                                                                                                                                                                                                                         |
| `apps/prototype-wp-alt-context/src/api/class-clusters-controller.php`                            | Adapt `should_use_local_projection()` and `maybe_bootstrap_after_proxy_read()` to accept the structured `SyncPullResult` return type from `SyncPullJob` instead of `bool`. Update `resolve_sync_pull_job()` to pass `SyncStateRepository` when building `SyncPullJob`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`                         | Add `sync_health` and `last_sync_result` fields to `get_sync_status()` and `trigger_sync()` responses. Update `trigger_sync()` to read the already-persisted `last_sync_result` (written by `SyncPullJob`) rather than persisting it directly. Update `build_sync_pull_job()` to pass `SyncStateRepository` to `SyncPullJob` constructor. Adapt to `SyncPullResult` return type.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `apps/prototype-wp-alt-context/src/api/class-conflict-controller.php`                            | **New controller.** Owns all conflict and dead-letter REST routes: conflict list, conflict detail, conflict resolution, dead-letter list, dead-letter retry, dead-letter discard. Constructor dependencies: `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, `SyncStateRepository`. Registered in `RecognitionController` composition root alongside the existing controllers. This separates conflict management concerns from sync status reporting, avoiding the need to inflate `SyncStatusController`'s constructor with dependencies it doesn't need for its primary sync health role. The conflict list and detail responses include a server-computed `allowed_resolutions` array derived from conflict source: projection conflicts allow `['accepted', 'dismissed']`; outbox conflicts for deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) allow `['accepted', 'dismissed']`; outbox conflicts for person CRUD and compound topology operations allow only `['dismissed']`. This pushes resolution-gating logic to the server so the frontend renders correct action buttons without duplicating operation-type classification.                                                     |
| `apps/prototype-wp-alt-context/src/api/class-recognition-controller.php`                         | Update composition root to instantiate `ConflictController` with `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, and `SyncStateRepository`. Wire `ConflictController::register_routes()` alongside existing controller route registrations. Pass `SyncStateRepository` to `SyncPullJob` constructor (shared instance).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                        | Add `find_failed_operations()` and `find_operation_by_id()` for dead-letter inspection. Add `retry_failed_operation()` (reset to pending, clear errors, reschedule drain), `discard_operation()` (mark as discarded, refresh metrics), and `re_enqueue_with_current_base()` (reset conflict row to pending with updated base version). Outbox row persistence stays in the outbox classes rather than SyncStateRepository.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                         | Add `last_sync_result varchar(20) DEFAULT 'ok'` and `last_sync_attempted_at datetime DEFAULT NULL` columns to `wp_acx_sync_state` table definition.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

### Frontend (TypeScript/React)

| File                                                                             | Change                                                                                                                                                                                                                                                                           |
| -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts`           | Add `SyncHealth` type, `sync_health` field and `last_sync_result` field to `SyncStatusResponse` / `SyncTriggerResponse`, add `ConflictRecord` (including `outbox_id: number` where `0` means projection conflict, and `allowed_resolutions: Array<'accepted' \| 'dismissed'>` fields), `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse` types.      |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Refactor to use `sync_health` discriminant for visual states. Add actionable links: conflict count links to conflict inbox panel (`?panel=conflicts`), failed count links to dead-letter panel (`?panel=dead-letter`). Add distinct offline, queued, and failures visual states. |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx`                 | Add sync health summary card showing current `sync_health` state, conflict count, failed count, and pending count with links to workbench detail panels (`?panel=conflicts`, `?panel=dead-letter`).                                                                              |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx`    | Add `WorkbenchPanel` type (`'conflicts' \| 'dead-letter' \| null`), `activePanel` state, and `setActivePanel` setter. Sync with `panel` URL query param via `useTabParam` or a new `usePanelParam` hook.                                                                         |
| `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`                 | Render `ConflictInbox` and `DeadLetterPanel` as overlay panels when `activePanel` is set. Add panel dismiss handler.                                                                                                                                                             |
| `apps/prototype-wp-alt-context/js/admin/hooks/`                                  | Add `useConflicts` hook (paginated conflict list query), `useResolveConflict` mutation hook, `useDeadLetterOperations` hook (failed outbox query), `useRetryOperation` and `useDiscardOperation` mutation hooks.                                                                 |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/`                        | Add `ConflictInbox.tsx` component: paginated list of open conflicts with entity info, conflict code, timestamps, and local-vs-machine payload side-by-side view. Add resolution actions (accept/keep/dismiss).                                                                   |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/`                        | Add `DeadLetterPanel.tsx` component: list of failed outbox operations with operation type, entity key, error details, attempt count. Add retry and discard actions.                                                                                                              |

## Related Files

| File                                                                                     | Note                                                                                                                        |
| ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`               | Outbox enqueue path. No changes needed -- Phase 4 reads from what Phase 3 writes.                                           |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php`           | Dispatch transport. No changes needed.                                                                                      |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-topology-command-repository.php` | Topology command state. Currently exposes only `find_pending()` and `find_reconcilable()` queries. A topology-command panel (stretch goal) would need additional failed/conflict/detail query methods not yet present. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`           | Curation mutation entrypoint. No changes needed.                                                                            |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts`                          | Existing sync status hook. May need stale-time adjustment but no structural changes.                                        |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts`                         | Existing sync trigger mutation. No changes needed.                                                                          |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx`            | Workbench context provider. Extended to add panel state (see Functions to Change).                                          |
| `docs/tasks/6.0/phase-3-minimal-durable-sync-replay-task-plan.md`                        | Phase 3 delivers the infrastructure Phase 4 depends on.                                                                     |
| `docs/tasks/6.0/deferred-ux-ergonomics-post-epic-task-plan.md`                           | Routes bidirectional conflict resolution for person name edits to this phase.                                               |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md`      | Parent epic with Phase 4 exit criteria.                                                                                     |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure from Phase 3)

- [x] `wp_acx_sync_conflicts` table with `resolution_status`, `resolved_at`, `machine_payload`, `local_payload` columns.
- [x] `ConflictRepository::record_conflict()` and `record_projection_conflict()` write conflict records from drain 409s and projection conflicts.
- [x] `SyncStateRepository` aggregates pending, failed, and conflict counts into `wp_acx_sync_state`.
- [x] `SyncStatusController` REST response includes `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, timestamps, and `topology_commands` status.
- [x] `SyncStatusResponse` TypeScript type includes all aggregate sync fields and `TopologyCommandStatus`.
- [x] `SyncStatusIndicator` displays conflict count badge, pending curation badge, and timestamp labels.
- [x] `OutboxDrain` handles retry (5 attempts, exponential backoff) and dead-letter (`failed` status).

## Phase 0: Scaffolding

- [ ] Add REST route registrations for conflict list, conflict detail, conflict resolution, dead-letter list, dead-letter retry, and dead-letter discard in new `ConflictController` (not `SyncStatusController`).
- [ ] Add `ConflictController` scaffold: constructor accepting `ConflictRepository`, `ConflictResolutionService`, `OutboxDrain`, `SyncStateRepository`. Register route stubs returning `501 Not Implemented`.
- [ ] Update `RecognitionController` composition root to instantiate `ConflictController` and call `register_routes()`.
- [ ] Expand `SyncPullJobInterface`: change `perform(string $tenant_id)` and `perform_bypass_cooldown(string $tenant_id)` return type from `bool` to `SyncPullResult`.
- [ ] Add `SyncPullResult` enum or value object: `ok`, `failed`, `unreachable`, `skipped`. The `skipped` value covers `perform()`'s cooldown short-circuit (no fetch attempted).
- [ ] Add `SyncStateRepository` as constructor parameter to `SyncPullJob`. Update `RecognitionController` and `SyncStatusController::build_sync_pull_job()` to pass the shared `SyncStateRepository` instance.
- [ ] Adapt `ClustersController` call sites (`should_use_local_projection()`, `maybe_bootstrap_after_proxy_read()`) to handle `SyncPullResult` instead of `bool`.
- [ ] Add `ConflictRepository` method signatures: `find_open_conflicts_for_tenant()`, `find_conflict_by_id()`, `mark_resolved()`, `count_open_conflicts()`.
- [ ] Add `ConflictResolutionService` scaffold for source-aware resolution dispatch.
- [ ] Add `SyncStateRepository` method signatures: `get_last_sync_result()`, `set_last_sync_result()`.
- [ ] Add `OutboxDrain` method signatures: `find_failed_operations()`, `find_operation_by_id()`, `retry_failed_operation()`, `discard_operation()`, `re_enqueue_with_current_base()`.
- [ ] Add `ClustersRepository` method signature: `reset_curation()`, `delete_cluster()`.
- [ ] Add `IdentityMembersRepository` method signature: `reset_curation()`, `delete_member()`, `accept_machine_cluster_assignment()`.
- [ ] Add `last_sync_result varchar(20) DEFAULT 'ok'` and `last_sync_attempted_at datetime DEFAULT NULL` columns to `wp_acx_sync_state` table definition in `LifecycleManager`.
- [ ] Add TypeScript type stubs: `SyncHealth`, `last_sync_result` on sync payloads, `ConflictRecord` (with `outbox_id: number` where `0` = projection conflict, and `allowed_resolutions: Array<'accepted' | 'dismissed'>` fields), `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse`, conflict resolution request/response types, and workbench panel state types.
- [ ] Create React component file stubs: `ConflictInbox.tsx`, `DeadLetterPanel.tsx` with `NotImplementedError` placeholder renders.
- [ ] Create hook file stubs: `useConflicts.ts`, `useResolveConflict.ts`, `useDeadLetterOperations.ts`, `useRetryOperation.ts`, `useDiscardOperation.ts`.
- [ ] Create PHPUnit test scaffolding for conflict query, resolution, and dead-letter endpoints.
- [ ] Create Vitest test scaffolding for conflict inbox, dead-letter panel, and sync health indicator states.
- [ ] Verify scaffolds compile: `cd apps/prototype-wp-alt-context && composer phpstan` and `cd apps/prototype-wp-alt-context && npm run typecheck`.

## Phase 1: PHP -- Conflict Query and Resolution API

- [ ] Implement `ConflictRepository::find_open_conflicts_for_tenant()`: paginated query returning open conflicts ordered by `created_at DESC`. Query includes `outbox_id` column so the controller can derive `allowed_resolutions`.
- [ ] Implement `ConflictRepository::find_conflict_by_id()`: single conflict with full payload fields, tenant-scoped.
- [ ] Implement `ConflictRepository::mark_resolved()`: update `resolution_status` and `resolved_at`, tenant-scoped. Valid transitions: `open` to `accepted`, `dismissed`. Does not reconcile entity state -- that is the resolution service's job.
- [ ] Implement `ConflictRepository::count_open_conflicts()`: count query for pagination headers.
- [ ] Implement `ConflictResolutionService::resolve()`: dispatch per source, `operation_type`, and `conflict_code`. Wrap all entity mutations and conflict status updates in a `$wpdb` transaction (`START TRANSACTION` / `COMMIT` / `ROLLBACK`). Every return path after `START TRANSACTION` must issue `ROLLBACK` first; intermediate mutation results (`clear_curation_for_entity`, `discard_operation`, `re_enqueue_with_current_base`, `resolve_projection_accepted`) must be checked and must abort with `ROLLBACK` on failure before reaching `mark_resolved` or `COMMIT`. Join to outbox row via `outbox_id` to read `operation_type`. Gate outbox "accept machine" to deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`); `ROLLBACK` and return error for person CRUD and compound topology mutations (`person_created`, `person_updated`, `person_deleted`, `cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, `cluster_created_for_identity`) -- these only support "keep local" (re-enqueue). Accepted single-entity outbox conflicts: clear curation flags on entity via `reset_curation()`, discard outbox row (convergence on next sync pull -- operator triggers via frontend). Outbox conflict dismissed = re-enqueue with updated base version (available for all operation types). Projection conflict accepted = dispatch per `conflict_code`: `curated_cluster_deleted` deletes the curated cluster row; `curated_member_deleted` deletes the curated member row; `member_cluster_reassignment` updates member's `cluster_uuid` to machine-proposed value and clears `is_curated`. Projection conflict dismissed = no entity mutation.
- [ ] Implement conflict endpoints in `ConflictController`: `GET /acx/v1/recognition/conflicts` (paginated list with `resolution_status` filter param -- response includes `outbox_id` and computed `allowed_resolutions` per row), `GET /acx/v1/recognition/conflicts/{id}` (detail with decoded payloads, `outbox_id`, and `allowed_resolutions`), `POST /acx/v1/recognition/conflicts/{id}/resolve` (accepts `resolution_status` (`accepted` | `dismissed`), validates against `allowed_resolutions` server-side, calls `ConflictResolutionService::resolve()`, refreshes sync state metrics). Permission: `manage_options`. The `allowed_resolutions` array is derived per row: projection conflicts (`outbox_id = 0`) -> `['accepted', 'dismissed']`; outbox conflicts with deterministic single-row `operation_type` (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) -> `['accepted', 'dismissed']`; outbox conflicts with person CRUD or compound topology `operation_type` -> `['dismissed']`. For outbox conflicts, the controller joins to the outbox row via `OutboxDrain::find_operation_by_id()` to read `operation_type`.
- [ ] Implement `OutboxDrain::discard_operation()`: mark outbox row as `discarded` (new status value -- not present in current codebase), refresh metrics. Tenant-scoped, only operates on `conflict` or `failed` rows.
- [ ] Implement `OutboxDrain::re_enqueue_with_current_base()`: reset outbox row to `pending` with `attempts = 0`, update `expected_base_version` to given value, reschedule drain. Tenant-scoped, only operates on `conflict` rows.
- [ ] Implement `ClustersRepository::reset_curation()`: set `is_user_confirmed = 0`, clear curated label/person_id/curation_state for a given cluster_uuid. Used by outbox conflict acceptance.
- [ ] Implement `ClustersRepository::delete_cluster()`: delete a cluster row by cluster_uuid. Used by projection conflict acceptance (`curated_cluster_deleted`).
- [ ] Implement `IdentityMembersRepository::reset_curation()`: set `is_curated = 0` for a given identity_uuid. Used by outbox conflict acceptance.
- [ ] Implement `IdentityMembersRepository::delete_member()`: delete a member row by identity_uuid. Used by projection conflict acceptance (`curated_member_deleted`).
- [ ] Implement `IdentityMembersRepository::accept_machine_cluster_assignment()`: update `cluster_uuid` to machine-proposed value AND set `is_curated = 0`, tenant-scoped. Distinct from existing `reassign_to_cluster()` which sets `is_curated = 1` for user-initiated reassignment. Used by projection conflict acceptance (`member_cluster_reassignment`).
- [ ] Implement `OutboxDrain::find_operation_by_id()`: single outbox operation detail, tenant-scoped. Required by `ConflictResolutionService::resolve()` to look up `operation_type` for acceptance gating.
- [ ] Add PHPUnit tests: conflict list returns open conflicts ordered by date with `outbox_id` and `allowed_resolutions`; `allowed_resolutions` is `['accepted', 'dismissed']` for projection conflicts, `['accepted', 'dismissed']` for deterministic single-row outbox conflicts, and `['dismissed']` for person CRUD plus compound topology outbox conflicts; conflict detail returns decoded payloads with `allowed_resolutions`; resolve endpoint rejects resolution not in `allowed_resolutions`; outbox conflict accepted for single-row cluster/member operations clears curation flags (`is_user_confirmed`/`is_curated` reset), discards outbox row (verify the next manual sync can converge the projection to machine state -- resolution does NOT trigger sync automatically); outbox conflict accepted for person CRUD or compound topology operation (`person_updated`, `cluster_merged` etc.) returns error/false; outbox conflict dismissed re-enqueues with updated base version across supported operation families; projection conflict accepted dispatches per conflict_code -- `curated_cluster_deleted` deletes cluster, `curated_member_deleted` deletes member, `member_cluster_reassignment` updates cluster assignment and clears curation; projection conflict dismissed preserves local state; resolution rejects invalid status transitions; tenant isolation is enforced.

## Phase 2: PHP -- Dead-Letter Query and Management API

- [ ] Implement `OutboxDrain::find_failed_operations()`: paginated query for `status = 'failed'` outbox rows with operation type, entity key, error details, attempt count. Outbox row persistence stays in the outbox classes.
- [ ] Implement `OutboxDrain::retry_failed_operation()`: reset `status` to `pending`, `attempts` to `0`, clear error fields, reschedule drain. Tenant-scoped, only operates on `failed` rows.
- [ ] Implement dead-letter endpoints in `ConflictController`: `GET /acx/v1/recognition/outbox/failed` (paginated list), `POST /acx/v1/recognition/outbox/{id}/retry` (calls retry, returns updated state), `POST /acx/v1/recognition/outbox/{id}/discard` (marks discarded, refreshes metrics). Permission: `manage_options`.
- [ ] Add PHPUnit tests: dead-letter list returns failed operations with error details; retry resets operation to pending and triggers drain; discard marks operation and updates metrics; operations scoped to tenant; retry and discard reject non-failed operations.

## Phase 3: PHP -- Sync Health Classification

- [ ] Add `classify_sync_health()` private method to `SyncStatusController`: computes `sync_health` from existing metrics plus persisted `last_sync_result` (offline and failure detection), topology command failed/conflict/pending counts, curation failed/conflict/pending counts, and staleness. Priority: offline > stale-from-failed (`last_sync_result = 'failed'` returns `stale` immediately since the projection did not update `last_synced_at`) > failures > conflicts > stale > queued > healthy.
- [ ] Implement `SyncStateRepository::get_last_sync_result()` and `set_last_sync_result()` methods after the Phase 0 method signatures/columns land. The result is persisted by `SyncPullJob` (not by `SyncStatusController`) so all pull sites -- `trigger_sync()`, inline stale refresh, and bootstrap -- update the reachability state.
- [ ] Implement `SyncPullJob` result persistence: after each `do_sync()` call, classify the outcome (`ok` | `failed` | `unreachable`) and persist via `SyncStateRepository::set_last_sync_result()`. Network errors from `SnapshotClient::fetch_snapshot()` map to `unreachable`; projection failures (before acknowledgement) map to `failed`; successful local projection maps to `ok` even if `maybe_acknowledge_projection()` fails (acknowledgement is coordination metadata only -- this preserves the existing contract where `do_sync()` returns `true` after projection success regardless of acknowledgement outcome). `perform()`'s cooldown short-circuit returns `SyncPullResult::skipped` without calling `do_sync()` and must NOT call `set_last_sync_result()` -- no fetch was attempted, so the previous result stays authoritative.
- [ ] Update `SyncStatusController::trigger_sync()` to read `last_sync_result` from `SyncStateRepository` (already persisted by `SyncPullJob`) instead of persisting it directly. Adapt to `SyncPullResult` return type.
- [ ] Add `sync_health` and `last_sync_result` fields to `get_sync_status()` REST response.
- [ ] Add `sync_health` and `last_sync_result` fields to `trigger_sync()` REST response (computed from the persisted sync result after the attempt completes).
- [ ] Add PHPUnit tests: health classification returns correct state for each condition; priority ordering is correct (offline > stale-from-failed > failures > conflicts > stale > queued > healthy); `last_sync_result = 'failed'` immediately returns `stale` (not healthy); topology command failures and conflicts contribute to their respective health states; `last_sync_result` field is persisted and read correctly; both `get_sync_status()` and `trigger_sync()` return the documented `last_sync_result`; `SyncPullJob` persists `unreachable` on network error, `failed` on projection error, `ok` on success (including when acknowledgement fails after successful projection -- acknowledgement failure must NOT set `failed`); `SyncPullJob::perform()` returns `skipped` when cooldown is active and does NOT overwrite `last_sync_result` or `last_sync_attempted_at`; `ClustersController` inline refresh and bootstrap pulls also persist the result (not just `trigger_sync()`); all three call sites (`trigger_sync`, stale refresh, bootstrap) update `last_sync_result` on real attempts.

## Phase 4: Frontend -- Sync Health Indicator Upgrade

- [ ] Add `SyncHealth` union type (`'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline'`), plus `sync_health` and `last_sync_result` fields to `SyncStatusResponse` and `SyncTriggerResponse` in TypeScript types. Note: `syncing` is excluded from the GET-derivable enum.
- [ ] Refactor `SyncStatusIndicator` to use `sync_health` as the **idle-state** visual discriminant. Preserve the existing transient-state precedence: `pipelinePhase === 'projecting'` (projecting/acknowledging) and `syncTrigger.isPending` (active trigger) remain authoritative while a job is running. `sync_health` only drives the badge and links when no transient operation is active. This avoids regressing the Phase 1 unified pipeline lifecycle indicators.
- [ ] Add distinct visual states for `offline` (error styling, manual retry), `failures` (warning styling, link to dead-letter panel), `conflicts` (warning styling, link to conflict inbox), `queued` (info styling with pending count -- includes both curation and topology command backlogs), `stale` (warning with sync-now), `healthy` (success). For `failures` and `conflicts` states, show a source breakdown: curation sync counts (actionable via panels) versus topology-command counts (informational-only -- detailed topology-command management is a stretch goal). The breakdown uses `failed_curation_operations` / `topology_commands.failed` for failures, and `conflict_count` / `topology_commands.conflict` for conflicts.
- [ ] Make conflict count badge clickable/linked to conflict inbox panel (`?panel=conflicts`).
- [ ] Make failed count badge clickable/linked to dead-letter panel (`?panel=dead-letter`).
- [ ] Add sync health summary card to `DashboardPage`: compact display of current health state, conflict count, failed count, pending count, with links to workbench panels (`?panel=conflicts`, `?panel=dead-letter`). When topology-command failures or conflicts contribute to the health state, show the topology-command counts alongside the actionable curation counts so operators understand the full breakdown.
- [ ] Add `WorkbenchPanel` type (`'conflicts' | 'dead-letter' | null`) to `WorkbenchContext`. Add `activePanel` state synced with `panel` URL query param. Add `setActivePanel` setter.
- [ ] Render `ConflictInbox` and `DeadLetterPanel` as overlay panels in `WorkbenchPage` when `activePanel` is set. Add dismiss handler that clears the `panel` query param.
- [ ] Add Vitest tests: each `sync_health` value renders the correct visual state when idle (no transient operation active); transient states (projecting, acknowledging, trigger pending) override `sync_health` badges even when sync_health is `conflicts` or `failures`; conflict badge links to `?panel=conflicts`; failed badge links to `?panel=dead-letter`; dashboard card renders correct summary with panel links; `WorkbenchPanel` state syncs with URL query param; `failures` and `conflicts` states show source breakdown (curation vs topology-command counts) and only curation counts are linked to panels.

## Phase 5: Frontend -- Conflict Inbox

- [ ] Implement `useConflicts` hook: paginated query for `GET /acx/v1/recognition/conflicts` with `resolution_status` filter, React Query config.
- [ ] Implement `useResolveConflict` mutation hook: `POST /acx/v1/recognition/conflicts/{id}/resolve`, invalidates conflict and sync-status queries on success.
- [ ] Implement `ConflictInbox` component: paginated list of open conflicts. Each row shows entity type, entity key (with cluster label if available), conflict code (human-readable), created timestamp.
- [ ] Add conflict detail expansion or modal: side-by-side comparison of `machine_payload` (what backend proposed) vs `local_payload` (what operator curated). Highlight differing fields.
- [ ] Add resolution actions per conflict, driven by the `allowed_resolutions` field from the REST response (no client-side operation-type classification needed). If `allowed_resolutions` includes `'accepted'`, show "Accept machine version"; if it includes `'dismissed'`, show "Keep local version". Projection conflicts: `allowed_resolutions` is `['accepted', 'dismissed']` -- show both actions. Outbox conflicts for deterministic single-row operations (`cluster_label_updated`, `cluster_dismissed`, `cluster_undismissed`, `identity_reassigned`, `cluster_person_bound`, `cluster_person_unbound`) use `['accepted', 'dismissed']`. For cluster conflicts, the acceptance confirmation must warn that ALL curated fields on the cluster will be reset (label, person assignment, dismissal state) due to the single `is_user_confirmed` flag. Outbox conflicts for person CRUD and compound topology operations use `['dismissed']` only; show an explanation that Phase 4 supports re-enqueue/retry for those operations but not machine acceptance because the overwrite/delete contract is not yet defined. Show confirmation before action.
- [ ] Add empty state for zero conflicts.
- [ ] Wire `ConflictInbox` into workbench navigation: rendered as overlay panel when `activePanel === 'conflicts'`. Accessible from `SyncStatusIndicator` conflict badge link and `DashboardPage` summary card.
- [ ] After successful conflict resolution, show a "Sync Now" affordance (reuse existing `useSyncTrigger`) so the operator can trigger convergence to the machine state immediately. Resolution itself does not trigger a sync -- the `ConflictResolutionService` clears curation and discards the outbox row, but the next projection (via sync pull) is what actually converges the entity.
- [ ] Add Vitest tests: conflict list renders with correct data; resolution actions are driven by `allowed_resolutions` (buttons present/absent match server-provided array); compound topology conflicts show only "Keep local" with explanation; empty state renders; loading and error states handled; "Sync Now" affordance appears after successful resolution.

## Phase 6: Frontend -- Dead-Letter Management Panel

- [ ] Implement `useDeadLetterOperations` hook: paginated query for `GET /acx/v1/recognition/outbox/failed`, React Query config.
- [ ] Implement `useRetryOperation` mutation hook: `POST /acx/v1/recognition/outbox/{id}/retry`, invalidates dead-letter and sync-status queries on success.
- [ ] Implement `useDiscardOperation` mutation hook: `POST /acx/v1/recognition/outbox/{id}/discard`, invalidates dead-letter and sync-status queries on success.
- [ ] Implement `DeadLetterPanel` component: list of failed outbox operations. Each row shows operation type (human-readable), entity key, attempt count, last error code, last error message, last attempted timestamp.
- [ ] Add per-operation actions: "Retry" (resets to pending), "Discard" (marks discarded). Show confirmation before discard.
- [ ] Add empty state for zero failed operations.
- [ ] Wire `DeadLetterPanel` into workbench navigation: rendered as overlay panel when `activePanel === 'dead-letter'`. Accessible from `SyncStatusIndicator` failed badge link.
- [ ] Add Vitest tests: dead-letter list renders with correct data; retry calls correct endpoint and shows success; discard calls correct endpoint; empty state renders.

## Phase 7: Integration Tests

- [ ] PHPUnit integration test: create conflict via projection, query via REST, resolve via REST, verify sync state metrics update.
- [ ] PHPUnit integration test: create failed outbox operation, query via dead-letter REST, retry via REST, verify operation resets to pending and drain is rescheduled.
- [ ] PHPUnit integration test: sync health classification returns correct values across all state combinations.
- [ ] Vitest integration test: `SyncStatusIndicator` renders all `sync_health` states correctly with real sync status data shapes. Panel navigation links resolve to correct `panel` query params.
- [ ] All PHPUnit, PHPStan, Vitest, and ESLint checks pass.

## Stretch Goals

- [ ] Topology command status panel (surface `wp_acx_topology_commands` pending/failed/conflict state alongside outbox dead-letter).
- [ ] Conflict resolution preview: show what the entity would look like after accepting the machine version before committing.
- [ ] Outbox operation timeline: full history view showing all operations (not just failed) with status transitions.
- [ ] Batch conflict resolution: select multiple conflicts and resolve them in one action.
- [ ] Compound topology conflict acceptance: per-operation revert contracts for `cluster_merged`, `revert_merge_cluster`, `assign_outlier_to_cluster`, and `cluster_created_for_identity` that unwind multi-entity local state changes when the operator accepts the machine version. Requires defining which rows to delete, restore, or reassign for each operation type.
- [ ] Export and purge controls for machine-derived biometric state (requires backend tenant policy infrastructure not yet built).
- [ ] Operator-visible audit history for retain, export, and purge actions (requires backend audit event tables not yet built).

## Success Criteria

- [ ] Operators can distinguish offline, stale, queued, conflicted, failed, and healthy sync states from the workbench and dashboard without database access.
- [ ] Operators can view a list of open conflicts, inspect local-vs-machine payload differences, and resolve each conflict through a source-aware workflow that reconciles the underlying projection or outbox state.
- [ ] Operators can view failed outbox operations with error details, retry individual operations, or discard them.
- [ ] Sync health badge on the dashboard provides at-a-glance status with links to detail views.
- [ ] Dashboard and sync badge links open stable workbench overlay panels via the `panel` query parameter.
- [ ] Resolving all conflicts and retrying/discarding all dead-letter operations returns the sync health indicator to `healthy` when no stale/offline/topology backlog remains. Topology-command backlogs are visible in the health badge source breakdown even though detailed inspection/management requires the stretch-goal topology-command panel.
- [ ] All PHPUnit, PHPStan, Vitest, and ESLint checks pass.

## Out of Scope

- **Export and purge endpoints**: depend on backend tenant policy fields (`retention_mode`, audit event tables) that do not exist yet. They belong to Phase 5 (Retention, Export, Purge) in the parent epic.
- **Delta ingest**: tracked in deferred/post-v0.2.0 scope. Phase 4 works with existing snapshot-based sync.
- **Backend-authored machine proposals for person names**: Phase 4 covers the operator-facing conflict inbox, person-side outbox conflict review, and the UI affordances needed to surface person-name drift. What remains out of scope is new backend proposal generation/storage (`machine_proposals` table or equivalent) for machine-authored person-name suggestions, which still needs a separate follow-on once that backend contract exists.
- **Admin retry controls for topology commands**: topology command retry/discard follows the same pattern as outbox dead-letter but is listed as stretch because `TopologyCommandRepository` currently exposes only `find_pending()` and `find_reconcilable()` -- failed/conflict/detail query methods would still need to be added.
