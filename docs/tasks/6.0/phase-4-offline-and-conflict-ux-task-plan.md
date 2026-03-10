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

- **Conflict record**: a `wp_acx_sync_conflicts` row written when a backend snapshot proposes a change to a curated entity (projection conflict) or when a curation push returns 409 (outbox conflict). Resolution status is `open`, `accepted`, `dismissed`, or `resolved`.
- **Dead-letter operation**: an outbox row with `status = 'failed'` after exhausting its retry budget (default 5 attempts). Requires manual inspection and retry or discard.
- **Stale state**: `is_stale = true` in sync status, meaning the local projection has not been refreshed within the staleness threshold.
- **Queued state**: `pending_curation_operations > 0` or `topology_commands.pending > 0`, indicating local mutations awaiting backend sync.
- **Offline**: the backend recognition service is unreachable. Determined from persisted `last_sync_result` field in `wp_acx_sync_state`: when the most recent sync attempt failed with a network/connection error, the service is considered offline until the next successful sync. The `trigger_sync()` POST response persists this result so that subsequent GET requests can derive the offline state without a live probe.
- **Conflict resolution**: the operator reviews a machine proposal vs. local curation and chooses to accept the machine version or keep the local version. Resolution is not just a status flag update -- it must reconcile the underlying local/backend divergence per conflict source:
  - **Outbox conflict resolution (accept machine)**: discard the conflicted outbox row, mark the conflict `accepted`, and trigger a resync so the backend's current state becomes the local projection. The local curation that caused the conflict is abandoned.
  - **Outbox conflict resolution (keep local)**: re-enqueue the outbox operation with the current `backend_version` as the new `expected_base_version`, mark the conflict `dismissed`, and let the next drain attempt replay the curation against the updated base.
  - **Projection conflict resolution (accept machine)**: apply the `machine_payload` to the local entity via the projector/repository layer, mark the conflict `accepted`. The local override is replaced by the machine-proposed values.
  - **Projection conflict resolution (keep local)**: mark the conflict `dismissed` with no entity mutation. The local curated state is preserved and the machine proposal is discarded.

## Current State Analysis

- `SyncStatusIndicator` shows coarse states: syncing, stale+retry, fresh, unavailable. It displays conflict count and pending curation as badge text but is not a link or actionable control.
- `DashboardPage` shows library coverage, identity stats, quick actions, and job history. No sync health or conflict indicators exist on the dashboard.
- `SyncStatusResponse` TypeScript type already includes `pending_curation_operations`, `failed_curation_operations`, `conflict_count`, `last_curation_conflict_at`, `last_curation_failed_at`, and `topology_commands` (pending/applied/failed/conflict). The data contract is already rich enough for Phase 4 summary indicators.
- `ConflictRepository` can `record_conflict()` and `record_projection_conflict()` but has no public query methods for listing, filtering, or resolving conflicts. Only the private `find_open_projection_conflict()` method exists.
- `SyncStateRepository` provides aggregate counts (`get_pending_curation_operations`, `get_conflict_count`, `get_failed_curation_operations`) but no detail queries for individual operations or conflicts.
- `OutboxDrain` handles retry with exponential backoff (max 5 attempts) and marks dead-letter operations as `failed`. No manual retry mechanism exists.
- `SyncStatusController` exposes `GET /acx/v1/recognition/sync-status` and `POST /acx/v1/recognition/sync/trigger` but no conflict list/detail/resolution endpoints, no outbox operation list, and no dead-letter retry endpoint.
- `wp_acx_sync_conflicts` table schema has `resolution_status` (`open` default) and `resolved_at` columns but no resolution infrastructure writes to them.
- `wp_acx_sync_outbox` has `status`, `attempts`, `last_error_code`, `last_error_message` columns that Phase 4 needs to surface.
- The deferred UX ergonomics document (`deferred-ux-ergonomics-post-epic-task-plan.md`) explicitly routes bidirectional conflict resolution for person name edits to this phase.

## Proposed Solution

Build Phase 4 in four layers, each independently testable:

1. **PHP: Conflict and outbox query/resolution API.** Add REST endpoints for listing conflicts, viewing conflict detail, resolving conflicts, listing dead-letter operations, and retrying or discarding dead-letter entries. Extend `ConflictRepository` and `SyncStateRepository` with the required query and mutation methods.

2. **PHP: Sync status enrichment.** Extend `wp_acx_sync_state` with `last_sync_result` (`ok` | `failed` | `unreachable`) and `last_sync_attempted_at` timestamp, persisted by `trigger_sync()` after each attempt. Extend the sync status REST response with a computed `sync_health` field that classifies the overall state as `healthy`, `queued`, `stale`, `conflicts`, `failures`, or `offline`. The `sync_health` enum is limited to states that can be derived from the persisted GET payload; `syncing` is deliberately excluded because active-sync progress is only observable on the transient POST response. The classifier incorporates both curation outbox and topology command backlogs when determining `queued` state.

3. **Frontend: Sync health indicators.** Upgrade `SyncStatusIndicator` to surface the `sync_health` classification with distinct visual states and actionable links. Add a condensed sync health badge to `DashboardPage`. Wire conflict count and failed count badges as navigation links to the detail views via the workbench panel contract defined below.

4. **Frontend: Conflict inbox and dead-letter management.** Add a conflict list component showing open conflicts with entity type, entity key, conflict code, timestamps, and local-vs-machine payload comparison. Add resolution actions (accept machine, keep local). Add a dead-letter list showing failed outbox operations with error details, and retry/discard actions.

5. **Frontend: Navigation contract.** Conflict inbox and dead-letter panel are rendered as overlay panels within the workbench, activated by a `panel` query parameter (`?panel=conflicts` or `?panel=dead-letter`). This avoids extending the existing `WorkbenchTab` type (`scan | batch | confirm`) which controls the primary workflow tabs. Panels overlay the active tab content and are dismissible. `WorkbenchContext` gains a `activePanel: WorkbenchPanel | null` state and `setActivePanel` setter. `SyncStatusIndicator` badges and `DashboardPage` links navigate to the workbench with the appropriate `panel` query param.

Retention/export/purge endpoints are explicitly out of scope for this task plan. The epic lists them as Phase 4 deliverables, but they depend on backend tenant policy infrastructure that does not exist yet (no retention mode fields, no audit event tables). They should be scoped as a separate task plan once backend policy fields land.

## Patterns to Follow

### PHP: Conflict Query Pattern

```php
// In ConflictRepository -- new public query method
public function find_open_conflicts_for_tenant( string $tenant_id, int $limit = 50, int $offset = 0 ): array {
    global $wpdb;
    return $wpdb->get_results(
        $wpdb->prepare(
            'SELECT id, entity_type, entity_key, conflict_code, backend_version, local_revision,
                    machine_payload, local_payload, resolution_status, created_at
             FROM %i WHERE tenant_id = %s AND resolution_status = %s
             ORDER BY created_at DESC LIMIT %d OFFSET %d',
            $this->table_name, $tenant_id, 'open', $limit, $offset
        ),
        ARRAY_A
    );
}
```

### PHP: Conflict Resolution Pattern

Resolution is a two-step operation: reconcile the entity state, then update the conflict record. The `ConflictResolutionService` owns the dispatch to the correct reconciliation path per conflict source.

```php
// In ConflictResolutionService -- dispatch per source
public function resolve( int $conflict_id, string $resolution, string $tenant_id ): bool {
    $conflict = $this->conflict_repo->find_conflict_by_id( $conflict_id, $tenant_id );
    if ( ! $conflict || $conflict['resolution_status'] !== 'open' ) {
        return false;
    }

    $has_outbox_id = ! empty( $conflict['outbox_id'] );

    if ( 'accepted' === $resolution ) {
        if ( $has_outbox_id ) {
            // Outbox conflict: discard the stale outbox row + trigger resync.
            $this->outbox_drain->discard_operation( (int) $conflict['outbox_id'], $tenant_id );
        } else {
            // Projection conflict: apply machine_payload to local entity.
            $this->projector->apply_machine_payload(
                $conflict['entity_type'],
                $conflict['entity_key'],
                json_decode( $conflict['machine_payload'], true ),
                $tenant_id
            );
        }
    } elseif ( 'dismissed' === $resolution ) {
        if ( $has_outbox_id ) {
            // Outbox conflict: re-enqueue with updated base version.
            $this->outbox_drain->re_enqueue_with_current_base(
                (int) $conflict['outbox_id'],
                (int) $conflict['backend_version'],
                $tenant_id
            );
        }
        // Projection conflict dismissed: no entity mutation, local state preserved.
    }

    return $this->conflict_repo->mark_resolved( $conflict_id, $resolution, $tenant_id );
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
// In OutboxDrain or a new DeadLetterService
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

The classifier uses persisted `last_sync_result` for offline detection and checks both curation outbox and topology command backlogs for queued state. `syncing` is excluded -- it is a transient state visible only during the POST `trigger_sync()` response, not derivable from GET.

```php
// In SyncStatusController -- computed from existing + new persisted metrics
private function classify_sync_health( array $curation_state, bool $is_stale, string $last_sync_result ): string {
    if ( 'unreachable' === $last_sync_result ) {
        return 'offline';
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
// Extend SyncStatusResponse
// Note: 'syncing' is excluded from SyncHealth -- it is only observable during
// the transient POST trigger_sync response, not from GET sync-status.
export type SyncHealth = 'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline';

export interface SyncStatusResponse {
  // ... existing fields ...
  sync_health: SyncHealth;
}
```

### Frontend: Conflict List Hook Pattern

```typescript
// New hook: useConflicts
export const useConflicts = (options?: { status?: string }) => {
  return useQuery({
    queryKey: ['acx', 'conflicts', options?.status ?? 'open'],
    queryFn: () => apiFetch<ConflictListResponse>({
      path: `/acx/v1/recognition/conflicts?status=${options?.status ?? 'open'}`,
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
    mutationFn: (params: { conflictId: number; resolution: 'accepted' | 'dismissed' }) =>
      apiFetch({
        path: `/acx/v1/recognition/conflicts/${params.conflictId}/resolve`,
        method: 'POST',
        data: { resolution_status: params.resolution },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['acx', 'conflicts'] });
      queryClient.invalidateQueries({ queryKey: ['acx', 'sync-status'] });
    },
  });
};
```

## Functions to Change

### Plugin (WordPress)

| File | Change |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php` | Add `find_open_conflicts_for_tenant()`, `find_conflict_by_id()`, `mark_resolved()`, `count_open_conflicts()` public query/mutation methods. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-resolution-service.php` | New service. Dispatches conflict resolution to the correct reconciliation path per conflict source: outbox conflicts route to outbox drain discard/re-enqueue, projection conflicts route to projector apply or no-op. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Add `apply_machine_payload()` method: applies decoded machine payload fields to the local entity via existing repository update methods, scoped by entity type. Used by projection conflict `accepted` resolution. |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | Add `find_failed_outbox_operations()` and `find_outbox_operation_by_id()` for dead-letter inspection. Add `retry_failed_operation()` and `discard_failed_operation()` for dead-letter management. Add `get_last_sync_result()` and `set_last_sync_result()` for persisted reachability state. |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Add `sync_health` computed field to `get_sync_status()` response. Register new REST routes for conflict list/detail/resolution and dead-letter list/retry/discard. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php` | Add `retry_failed_operation()` method that resets a failed outbox row to `pending` with `attempts = 0` and reschedules drain. |

### Frontend (TypeScript/React)

| File | Change |
| --- | --- |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/types/sync.ts` | Add `SyncHealth` type, `sync_health` field to `SyncStatusResponse`, add `ConflictRecord`, `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse` types. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | Refactor to use `sync_health` discriminant for visual states. Add actionable links: conflict count links to conflict inbox panel (`?panel=conflicts`), failed count links to dead-letter panel (`?panel=dead-letter`). Add distinct offline, queued, and failures visual states. |
| `apps/prototype-wp-alt-context/js/admin/pages/DashboardPage.tsx` | Add sync health summary card showing current `sync_health` state, conflict count, failed count, and pending count with links to workbench detail panels (`?panel=conflicts`, `?panel=dead-letter`). |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | Add `WorkbenchPanel` type (`'conflicts' \| 'dead-letter' \| null`), `activePanel` state, and `setActivePanel` setter. Sync with `panel` URL query param via `useTabParam` or a new `usePanelParam` hook. |
| `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx` | Render `ConflictInbox` and `DeadLetterPanel` as overlay panels when `activePanel` is set. Add panel dismiss handler. |
| `apps/prototype-wp-alt-context/js/admin/hooks/` | Add `useConflicts` hook (paginated conflict list query), `useResolveConflict` mutation hook, `useDeadLetterOperations` hook (failed outbox query), `useRetryOperation` and `useDiscardOperation` mutation hooks. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/` | Add `ConflictInbox.tsx` component: paginated list of open conflicts with entity info, conflict code, timestamps, and local-vs-machine payload side-by-side view. Add resolution actions (accept/keep/dismiss). |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/` | Add `DeadLetterPanel.tsx` component: list of failed outbox operations with operation type, entity key, error details, attempt count. Add retry and discard actions. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php` | Outbox enqueue path. No changes needed -- Phase 4 reads from what Phase 3 writes. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-dispatcher.php` | Dispatch transport. No changes needed. |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Projection conflict writer. Phase 4 adds `apply_machine_payload()` for projection conflict resolution (see Functions to Change). |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-topology-command-repository.php` | Topology command state. Phase 4 may surface topology command status in the UI but the repository already has query methods. |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php` | Curation mutation entrypoint. No changes needed. |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncStatus.ts` | Existing sync status hook. May need stale-time adjustment but no structural changes. |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts` | Existing sync trigger mutation. No changes needed. |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/WorkbenchContext.tsx` | Workbench context provider. Extended to add panel state (see Functions to Change). |
| `docs/tasks/6.0/phase-3-minimal-durable-sync-replay-task-plan.md` | Phase 3 delivers the infrastructure Phase 4 depends on. |
| `docs/tasks/6.0/deferred-ux-ergonomics-post-epic-task-plan.md` | Routes bidirectional conflict resolution for person name edits to this phase. |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Parent epic with Phase 4 exit criteria. |

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

- [ ] Add REST route registrations for conflict list, conflict detail, conflict resolution, dead-letter list, dead-letter retry, and dead-letter discard in `SyncStatusController`.
- [ ] Add `ConflictRepository` method signatures: `find_open_conflicts_for_tenant()`, `find_conflict_by_id()`, `mark_resolved()`, `count_open_conflicts()`.
- [ ] Add `ConflictResolutionService` scaffold for source-aware resolution dispatch.
- [ ] Add `SyncStateRepository` method signatures: `find_failed_outbox_operations()`, `find_outbox_operation_by_id()`, `get_last_sync_result()`, `set_last_sync_result()`.
- [ ] Add `OutboxDrain` method signature: `retry_failed_operation()`.
- [ ] Add TypeScript type stubs: `SyncHealth`, `ConflictRecord`, `ConflictListResponse`, `OutboxOperation`, `OutboxListResponse`, conflict resolution request/response types, and workbench panel state types.
- [ ] Create React component file stubs: `ConflictInbox.tsx`, `DeadLetterPanel.tsx` with `NotImplementedError` placeholder renders.
- [ ] Create hook file stubs: `useConflicts.ts`, `useResolveConflict.ts`, `useDeadLetterOperations.ts`, `useRetryOperation.ts`, `useDiscardOperation.ts`.
- [ ] Create PHPUnit test scaffolding for conflict query, resolution, and dead-letter endpoints.
- [ ] Create Vitest test scaffolding for conflict inbox, dead-letter panel, and sync health indicator states.
- [ ] Verify scaffolds compile: `composer phpstan`, `npm run typecheck`.

## Phase 1: PHP -- Conflict Query and Resolution API

- [ ] Implement `ConflictRepository::find_open_conflicts_for_tenant()`: paginated query returning open conflicts ordered by `created_at DESC`.
- [ ] Implement `ConflictRepository::find_conflict_by_id()`: single conflict with full payload fields, tenant-scoped.
- [ ] Implement `ConflictRepository::mark_resolved()`: update `resolution_status` and `resolved_at`, tenant-scoped. Valid transitions: `open` to `accepted`, `dismissed`. Does not reconcile entity state -- that is the resolution service's job.
- [ ] Implement `ConflictRepository::count_open_conflicts()`: count query for pagination headers.
- [ ] Implement `ConflictResolutionService::resolve()`: dispatch to correct reconciliation path per conflict source. Outbox conflict accepted = discard outbox row + trigger resync. Outbox conflict dismissed = re-enqueue with updated base version. Projection conflict accepted = apply machine_payload via projector. Projection conflict dismissed = no entity mutation.
- [ ] Register `GET /acx/v1/recognition/conflicts` endpoint: returns paginated conflict list with `status` filter param. Permission: `manage_options`.
- [ ] Register `GET /acx/v1/recognition/conflicts/{id}` endpoint: returns single conflict detail with decoded payloads. Permission: `manage_options`.
- [ ] Register `POST /acx/v1/recognition/conflicts/{id}/resolve` endpoint: accepts `resolution_status` (`accepted` | `dismissed`), calls `ConflictResolutionService::resolve()`, refreshes sync state metrics. Permission: `manage_options`.
- [ ] Implement `OutboxDrain::discard_operation()`: mark outbox row as `discarded`, refresh metrics. Tenant-scoped, only operates on `conflict` or `failed` rows.
- [ ] Implement `OutboxDrain::re_enqueue_with_current_base()`: reset outbox row to `pending` with `attempts = 0`, update `expected_base_version` to given value, reschedule drain. Tenant-scoped, only operates on `conflict` rows.
- [ ] Implement `SnapshotProjector::apply_machine_payload()`: apply decoded machine payload fields to the local entity via existing repository update methods, scoped by entity type.
- [ ] Add PHPUnit tests: conflict list returns open conflicts ordered by date; conflict detail returns decoded payloads; outbox conflict accepted discards outbox row and triggers resync; outbox conflict dismissed re-enqueues with updated base version; projection conflict accepted applies machine payload to local entity; projection conflict dismissed preserves local state; resolution rejects invalid status transitions; tenant isolation is enforced.

## Phase 2: PHP -- Dead-Letter Query and Management API

- [ ] Implement `SyncStateRepository::find_failed_outbox_operations()`: paginated query for `status = 'failed'` outbox rows with operation type, entity key, error details, attempt count.
- [ ] Implement `SyncStateRepository::find_outbox_operation_by_id()`: single outbox operation detail, tenant-scoped.
- [ ] Implement `OutboxDrain::retry_failed_operation()`: reset `status` to `pending`, `attempts` to `0`, clear error fields, reschedule drain. Tenant-scoped, only operates on `failed` rows.
- [ ] Implement discard for dead-letter: update `status` to `discarded` (add status value). Tenant-scoped, only operates on `failed` rows.
- [ ] Register `GET /acx/v1/recognition/outbox/failed` endpoint: returns paginated dead-letter list. Permission: `manage_options`.
- [ ] Register `POST /acx/v1/recognition/outbox/{id}/retry` endpoint: calls retry, returns updated operation state. Permission: `manage_options`.
- [ ] Register `POST /acx/v1/recognition/outbox/{id}/discard` endpoint: marks operation discarded, refreshes metrics. Permission: `manage_options`.
- [ ] Add PHPUnit tests: dead-letter list returns failed operations with error details; retry resets operation to pending and triggers drain; discard marks operation and updates metrics; operations scoped to tenant; retry and discard reject non-failed operations.

## Phase 3: PHP -- Sync Health Classification

- [ ] Add `classify_sync_health()` private method to `SyncStatusController`: computes `sync_health` from existing metrics plus persisted `last_sync_result` (offline detection), topology command failed/conflict/pending counts, curation failed/conflict/pending counts, and staleness. Priority: offline > failures > conflicts > stale > queued > healthy.
- [ ] Add `last_sync_result` (`ok` | `failed` | `unreachable`) and `last_sync_attempted_at` columns to `wp_acx_sync_state`. Persisted by `trigger_sync()` after each sync attempt. Add `SyncStateRepository::get_last_sync_result()` and `set_last_sync_result()` methods.
- [ ] Add `sync_health` and `last_sync_result` fields to `get_sync_status()` REST response.
- [ ] Add `sync_health` field to `trigger_sync()` REST response (computed after persisting the sync result).
- [ ] Add PHPUnit tests: health classification returns correct state for each condition; priority ordering is correct (offline > failures > conflicts > stale > queued > healthy); topology command failures and conflicts contribute to their respective health states; `last_sync_result` field is persisted and read correctly.

## Phase 4: Frontend -- Sync Health Indicator Upgrade

- [ ] Add `SyncHealth` union type (`'healthy' | 'queued' | 'stale' | 'conflicts' | 'failures' | 'offline'`) and `sync_health` field to `SyncStatusResponse` and `SyncTriggerResponse` in TypeScript types. Note: `syncing` is excluded from the GET-derivable enum.
- [ ] Refactor `SyncStatusIndicator` to use `sync_health` as the primary visual state discriminant instead of ad-hoc conditional chains.
- [ ] Add distinct visual states for `offline` (error styling, manual retry), `failures` (warning styling, link to dead-letter panel), `conflicts` (warning styling, link to conflict inbox), `queued` (info styling with pending count -- includes both curation and topology command backlogs), `stale` (warning with sync-now), `healthy` (success).
- [ ] Make conflict count badge clickable/linked to conflict inbox panel (`?panel=conflicts`).
- [ ] Make failed count badge clickable/linked to dead-letter panel (`?panel=dead-letter`).
- [ ] Add sync health summary card to `DashboardPage`: compact display of current health state, conflict count, failed count, pending count, with links to workbench panels (`?panel=conflicts`, `?panel=dead-letter`).
- [ ] Add `WorkbenchPanel` type (`'conflicts' | 'dead-letter' | null`) to `WorkbenchContext`. Add `activePanel` state synced with `panel` URL query param. Add `setActivePanel` setter.
- [ ] Render `ConflictInbox` and `DeadLetterPanel` as overlay panels in `WorkbenchPage` when `activePanel` is set. Add dismiss handler that clears the `panel` query param.
- [ ] Add Vitest tests: each `sync_health` value renders the correct visual state; conflict badge links to `?panel=conflicts`; failed badge links to `?panel=dead-letter`; dashboard card renders correct summary with panel links; `WorkbenchPanel` state syncs with URL query param.

## Phase 5: Frontend -- Conflict Inbox

- [ ] Implement `useConflicts` hook: paginated query for `GET /acx/v1/recognition/conflicts` with `status` filter, React Query config.
- [ ] Implement `useResolveConflict` mutation hook: `POST /acx/v1/recognition/conflicts/{id}/resolve`, invalidates conflict and sync-status queries on success.
- [ ] Implement `ConflictInbox` component: paginated list of open conflicts. Each row shows entity type, entity key (with cluster label if available), conflict code (human-readable), created timestamp.
- [ ] Add conflict detail expansion or modal: side-by-side comparison of `machine_payload` (what backend proposed) vs `local_payload` (what operator curated). Highlight differing fields.
- [ ] Add resolution actions per conflict: projection conflicts show "Accept machine version" (`accepted`) and "Keep local version" (`dismissed`); outbox conflicts show "Accept machine version" (discard local outbox change + resync, `accepted`) and "Keep local version" (re-enqueue local change against refreshed base, `dismissed`). Show confirmation before action.
- [ ] Add empty state for zero conflicts.
- [ ] Wire `ConflictInbox` into workbench navigation: rendered as overlay panel when `activePanel === 'conflicts'`. Accessible from `SyncStatusIndicator` conflict badge link and `DashboardPage` summary card.
- [ ] Add Vitest tests: conflict list renders with correct data; resolution actions call correct endpoint; empty state renders; loading and error states handled.

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
- [ ] Export and purge controls for machine-derived biometric state (requires backend tenant policy infrastructure not yet built).
- [ ] Operator-visible audit history for retain, export, and purge actions (requires backend audit event tables not yet built).

## Success Criteria

- [ ] Operators can distinguish offline, stale, queued, conflicted, failed, and healthy sync states from the workbench and dashboard without database access.
- [ ] Operators can view a list of open conflicts, inspect local-vs-machine payload differences, and resolve each conflict through a source-aware workflow that reconciles the underlying projection or outbox state.
- [ ] Operators can view failed outbox operations with error details, retry individual operations, or discard them.
- [ ] Sync health badge on the dashboard provides at-a-glance status with links to detail views.
- [ ] Dashboard and sync badge links open stable workbench overlay panels via the `panel` query parameter.
- [ ] Resolving all conflicts and retrying/discarding all dead-letter operations returns the sync health indicator to `healthy` when no stale/offline/topology backlog remains.
- [ ] All PHPUnit, PHPStan, Vitest, and ESLint checks pass.

## Out of Scope

- **Export and purge endpoints**: depend on backend tenant policy fields (`retention_mode`, audit event tables) that do not exist yet. They move to the follow-on retention/export/audit phase in the parent epic.
- **Delta ingest**: tracked in deferred/post-v0.2.0 scope. Phase 4 works with existing snapshot-based sync.
- **Bidirectional machine proposals for person names**: the deferred UX ergonomics document routes this here, but it requires backend proposal storage (`machine_proposals` table or equivalent) that does not exist. Scoped as a stretch goal or follow-on once backend proposal infrastructure is built.
- **Admin retry controls for topology commands**: topology command retry/discard follows the same pattern as outbox dead-letter but is listed as stretch because `TopologyCommandRepository` already has status query methods.
