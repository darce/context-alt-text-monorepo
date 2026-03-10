# Phase 2: Curation-First Merge Contract

## Problem Statement

When the backend re-clusters identities and WordPress projects the new snapshot, the merge logic unconditionally overwrites identity member assignments (cluster moves) and deletes members whose clusters are not `is_user_confirmed`. Curated membership state -- operator-assigned identities, manually reorganized clusters -- is silently destroyed by the next backend snapshot. The projector must distinguish machine-derived rows from curated overrides and record conflicts instead of overwriting.

## Workflow Principles

- **User curation is ground truth.** Machine clustering is advisory until projected into uncurated local state. Curated labels, assignments, merges, splits, and dismissals are never silently overwritten.
- **Curation protection is field-level, not row-level.** A cluster can have a machine-updated `identity_count` while preserving a curated `label` and `person_id`.
- **Conflicts are explicit records, not silent drops.** When a backend snapshot proposes a change to a curated entity, the system writes a conflict record for human review rather than applying or ignoring the proposal.
- **Machine state flows downstream only.** Backend compute outputs are proposals. WordPress projects them locally. The projector decides what auto-applies (uncurated) and what becomes a conflict (curated).

## Terminology

- **Curated row**: a local cluster or member row where the operator has made an explicit decision (label, person assignment, dismiss, confirm, or membership reassignment). Identified by `is_user_confirmed = 1` on clusters or `is_curated = 1` on members.
- **Machine row**: a row produced entirely by backend clustering, with no operator curation. Safe to overwrite on next snapshot.
- **Projection version**: the `snapshot_version` value from the backend snapshot that last wrote to a specific row.
- **Local revision**: a monotonic counter incremented on every local curation mutation, used for staleness detection.
- **Conflict record**: a `wp_acx_sync_conflicts` row that captures what the backend proposed vs what the operator curated, awaiting human review.
- **Auto-apply**: merge rule outcome where the backend change is applied without conflict because the target row is uncurated.
- **Conflict-record**: merge rule outcome where the backend change is recorded as a conflict because the target row has curation that would be overwritten.

## Current State Analysis

- `wp_acx_clusters` already has `is_user_confirmed`, `local_revision`, and `snapshot_version` columns. The current `merge_snapshot_for_tenant()` SQL reliably protects `label`, `curation_state`, and `is_user_confirmed` on curated clusters, and it preserves local `person_id` / `local_revision` by never writing snapshot values into those fields. This is a useful foundation for curation preservation, but it still does not protect membership composition.
- `wp_acx_identity_members` has **zero curation awareness**. The `ON DUPLICATE KEY UPDATE` unconditionally overwrites `cluster_uuid`, `attachment_id`, `bbox_json`, `thumb_path`, and `similarity`. If the backend moves an identity to a different cluster, the member row is silently reassigned even if the operator previously curated that membership.
- `delete_stale_non_curated_rows()` for members only checks the parent cluster's `is_user_confirmed` flag. If a cluster is uncurated but its individual member was manually reassigned by the operator, that member is still deleted.
- The `wp_acx_sync_conflicts` table already exists with the correct schema (`entity_type`, `entity_key`, `machine_payload`, `local_payload`, `conflict_code`, `resolution_status`), but the projector never writes to it.
- The `wp_acx_sync_outbox` table and `OutboxWriter` exist and are wired for dismiss/undismiss mutations only. Label updates are proxied directly to the backend without outbox durability -- label curation could be lost if the backend write fails. Merge, split, and reassign mutations are also backend-first (proxied) and do not touch the outbox.
- `ClusterMutationsController` sets `is_user_confirmed = 1` and increments `local_revision` on dismiss, undismiss, and label updates. But reassign (moving an identity between clusters) is proxied to the backend with no local curation marker on the member row.

## Proposed Solution

Extend the snapshot projection merge with three layers:

1. **Identity member curation lineage**: add `is_curated` and `projection_version` columns to `wp_acx_identity_members`. Mark members as curated when the operator reassigns, and prevent auto-overwrite of curated members during projection.

2. **Conflict-aware projector**: before writing to any row, check whether it is curated. If curated and the backend proposes a conflicting value, write a `wp_acx_sync_conflicts` record instead of applying the change. If uncurated, auto-apply normally.

3. **Conflict metrics refresh**: after projection, update `wp_acx_sync_state` conflict counters so the UI can surface "N conflicts require review" without additional queries.

The merge rules are defined per-field to avoid over-broad protection that would prevent harmless machine updates (like `identity_count` refresh) from reaching curated clusters.

## Patterns to Follow

### Cluster Merge Rules (per-field)

```
Field                    | Curated cluster (is_user_confirmed=1)        | Uncurated cluster
-------------------------|----------------------------------------------|------------------
label                    | PRESERVE local (already working)             | OVERWRITE from backend
curation_state           | PRESERVE local (already working)             | OVERWRITE from backend
is_user_confirmed        | PRESERVE local (already working)             | OVERWRITE from backend
person_id                | PRESERVE local (already working)             | PRESERVE local until backend snapshots carry person_id
local_revision           | PRESERVE (already working)                   | PRESERVE local until snapshot lineage for this field exists
representative_thumb_path| OVERWRITE (machine-derived, always safe)     | OVERWRITE from backend
identity_count           | OVERWRITE (machine-derived, always safe)     | OVERWRITE from backend
snapshot_version         | GREATEST (already working)                   | GREATEST
```

### Member Merge Rules (per-field)

```
Field           | Curated member (is_curated=1)                          | Uncurated member
----------------|--------------------------------------------------------|------------------
cluster_uuid    | PRESERVE + CONFLICT if backend moves to different cluster | OVERWRITE from backend
attachment_id   | OVERWRITE (immutable identity property, always safe)   | OVERWRITE from backend
bbox_json       | OVERWRITE (machine detection output, always safe)      | OVERWRITE from backend
thumb_path      | OVERWRITE (derived from identity, always safe)         | OVERWRITE from backend
similarity      | OVERWRITE (machine similarity score, always safe)      | OVERWRITE from backend
```

### Conflict Record Structure

```php
// Written to wp_acx_sync_conflicts when backend proposes change to curated entity.
$conflict = [
    'tenant_id'             => $tenant_id,
    'entity_type'           => 'cluster' | 'member',
    'entity_key'            => $cluster_uuid | $identity_uuid,
    'outbox_id'             => 0,  // no outbox entry for backend-initiated proposals
    'expected_base_version' => $current_local_snapshot_version,
    'backend_version'       => $incoming_snapshot_version,
    'local_revision'        => $current_local_revision,
    'conflict_code'         => 'member_cluster_reassignment' | 'curated_cluster_deleted',
    // NOTE: cluster_person_conflict deferred until backend snapshots include person_id.
    'machine_payload'       => json_encode($backend_proposed_values),
    'local_payload'         => json_encode($current_local_values),
    'resolution_status'     => 'open',
    'created_at'            => current_time('mysql'),
];
```

### Projector: Cluster Conflict Detection

```php
// In merge_snapshot_for_tenant(), before the INSERT ON DUPLICATE KEY UPDATE:
// Detect curated clusters that the backend no longer includes (curated_cluster_deleted).
// The existing IF(is_user_confirmed = 1, ...) SQL already preserves label, person_id,
// curation_state, and local_revision on curated clusters -- no additional field-level
// conflict detection needed for clusters in this phase.
//
// NOTE: cluster_person_conflict detection deferred until backend snapshots include
// person_id. Today the backend ClusterSnapshotResponse does not carry person_id,
// so field-level person conflict detection is impossible with the current contract.
// The existing IF guard already PRESERVES local person_id on curated clusters,
// which is the safe default.
```

### Projector: Member Conflict Detection

```php
// In members merge_snapshot_for_tenant(), for each member:
$existing_member = $this->get_curated_member($identity_uuid);
if ($existing_member !== null && $existing_member->is_curated) {
    $incoming_cluster = $cluster_uuid;
    if ($existing_member->cluster_uuid !== $incoming_cluster) {
        // Backend wants to move this identity to a different cluster than operator assigned.
        $this->record_conflict($tenant_id, 'member', $identity_uuid, 'member_cluster_reassignment',
            $existing_member->projection_version ?? 0, $snapshot_version, 0,
            ['cluster_uuid' => $incoming_cluster, 'similarity' => $similarity],
            ['cluster_uuid' => $existing_member->cluster_uuid]
        );
        continue; // Skip this member -- do NOT overwrite curated assignment.
    }
}
// Then proceed with normal INSERT ON DUPLICATE KEY UPDATE for non-curated members.
```

### Member ON DUPLICATE KEY with Curation Guard

```sql
INSERT INTO wp_acx_identity_members
    (identity_uuid, cluster_uuid, attachment_id, bbox_json, thumb_path, similarity,
     projection_version, is_curated, created_at, updated_at)
SELECT %s, %s, %d, %s, %s, NULLIF(%s, ''), %d, 0, %s, %s
FROM DUAL
WHERE EXISTS (
    SELECT 1 FROM wp_acx_clusters c
    WHERE c.cluster_uuid = %s AND c.tenant_id = %s
)
ON DUPLICATE KEY UPDATE
    cluster_uuid = IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid)),
    attachment_id = VALUES(attachment_id),
    bbox_json = VALUES(bbox_json),
    thumb_path = VALUES(thumb_path),
    similarity = NULLIF(%s, ''),
    projection_version = IF(is_curated = 1, projection_version, VALUES(projection_version)),
    updated_at = VALUES(updated_at)
```

## Functions to Change

| File                                                                                             | Line     | Change                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`                         | ~210     | Add `is_curated tinyint(1) NOT NULL DEFAULT 0` and `projection_version bigint(20) unsigned NOT NULL DEFAULT 0` columns to `wp_acx_identity_members` CREATE TABLE |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | 80-120   | Rewrite `merge_snapshot_for_tenant()` ON DUPLICATE KEY to guard `cluster_uuid` with `IF(is_curated = 1, ...)` and write `projection_version`                     |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | 287-339  | Rewrite `delete_stale_non_curated_rows()` to also preserve `is_curated = 1` members, not just members of `is_user_confirmed` clusters                            |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | new      | Add `mark_as_curated(identity_uuid)` method to set `is_curated = 1`                                                                                              |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-identity-members-repository.php` | new      | Add `get_curated_members_for_tenant(tenant_id)` method to return curated members for conflict detection                                                          |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php`         | new      | Add `get_curated_clusters_for_tenant(tenant_id)` method that returns curated clusters indexed by uuid                                                            |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php`                  | 62-72    | Extend `project()` to compare incoming cluster UUIDs against curated local clusters, record curated-cluster-deletion conflicts before merge, and refresh sync state conflict counters after merge |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-conflict-repository.php`                 | existing | Extend with `record_projection_conflict()` method using upsert semantics for idempotent re-projection                                                            |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php`       | existing | Verify `refresh_curation_metrics()` correctly counts new conflict records                                                                                        |
| `apps/prototype-wp-alt-context/src/api/class-cluster-mutations-controller.php`                   | reassign | After backend reassign succeeds and local rows update, mark affected member as `is_curated = 1`                                                                  |

## Related Files

| File                                                                                         | Note                                                                                               |
| -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php`                   | Calls `project()` -- no changes needed but must test end-to-end with conflict projection           |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-writer.php`                   | Already writes to outbox; may need conflict_code for new conflict types                            |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-outbox-drain.php`                    | Drains outbox to backend; no changes needed for Phase 2 (Phase 3 scope)                            |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php`                     | Reads `conflict_count` from sync state; already wired to surface conflict numbers in REST response |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx`             | Already reads `conflict_count`; no changes needed unless conflict UI is Phase 2 scope              |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Backend snapshot endpoint; no changes needed -- snapshot format unchanged                          |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md`          | Parent epic with Phase 2 exit criteria                                                             |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure)

- [x] `wp_acx_clusters` has `is_user_confirmed`, `local_revision`, `snapshot_version` columns.
- [x] Cluster merge SQL preserves curated label / curation_state today and preserves local person_id / local_revision by not projecting backend values for those fields yet.
- [x] `delete_stale_non_curated_rows()` preserves `is_user_confirmed = 1` clusters from deletion.
- [x] `wp_acx_sync_conflicts` table exists with correct schema (entity_type, entity_key, machine_payload, local_payload, resolution_status).
- [x] `wp_acx_sync_state` has `conflict_count` and `refresh_curation_metrics()`.
- [x] `SyncStatusIndicator` reads and displays `conflict_count` from REST response.
- [x] `ClusterMutationsController` sets `is_user_confirmed = 1` on dismiss, undismiss, and label mutations.
- [x] `OutboxWriter` enqueues durable curation operations for dismiss/undismiss (note: label and reassign are NOT yet on the outbox path).

## Phase 0: Scaffolding

- [x] Add `is_curated TINYINT(1) NOT NULL DEFAULT 0` column to `wp_acx_identity_members` CREATE TABLE in lifecycle manager.
- [x] Add `projection_version BIGINT(20) UNSIGNED NOT NULL DEFAULT 0` column to `wp_acx_identity_members` CREATE TABLE in lifecycle manager.
- [x] Extend existing `ConflictRepository` (in `src/sovereign/sync/class-conflict-repository.php`) with a `record_projection_conflict()` method that accepts projection-specific parameters (entity_type, entity_key, conflict_code, backend_version, local values, machine values) and uses upsert semantics with a unique key on `(tenant_id, entity_type, entity_key, conflict_code, backend_version)` to prevent duplicate conflicts on snapshot re-projection.
- [x] Add `IdentityMembersRepositoryInterface::mark_as_curated()` and `get_curated_members_for_tenant()` method stubs.
- [x] Add `ClustersRepositoryInterface::get_curated_clusters_for_tenant()` method stub.
- [x] Add PHPUnit merge-scenario scaffolding with data-provider-backed coverage for curated vs uncurated member projection behavior.
- [x] Verify scaffolds compile: `composer phpstan`.

## Phase 1: Identity Member Curation Lineage

- [x] Implement `mark_as_curated(string $identity_uuid)` in `IdentityMembersRepository`: sets `is_curated = 1` where identity_uuid matches.
- [x] Implement `get_curated_members_for_tenant(string $tenant_id)` that returns identity_uuid => member associative array for curated members.
- [x] Wire `mark_as_curated()` into `ClusterMutationsController::reassign_cluster_identity()` after successful backend reassignment to mark the moved member as curated locally.
- [x] Update `merge_snapshot_for_tenant()` SQL to use `IF(is_curated = 1, cluster_uuid, VALUES(cluster_uuid))` in ON DUPLICATE KEY UPDATE.
- [x] Update `merge_snapshot_for_tenant()` to write `projection_version` on insert and non-curated update.
- [x] Update `delete_stale_non_curated_rows()` to preserve `is_curated = 1` members (currently only checks parent cluster's `is_user_confirmed`).
- [x] Add PHPUnit coverage: member marked as curated survives snapshot merge; uncurated member is overwritten normally.

## Phase 2: Conflict-Aware Cluster Projection

- [x] Implement `get_curated_clusters_for_tenant(string $tenant_id)` in `ClustersRepository` returning uuid-indexed curated clusters.
- [x] Implement `ConflictRepository::record_projection_conflict()` with upsert semantics: ON DUPLICATE KEY UPDATE on `(tenant_id, entity_type, entity_key, conflict_code, backend_version)` so re-projecting the same snapshot does not create duplicate open conflicts.
- [x] In `SnapshotProjector::project()`, pre-load curated clusters for the tenant (single query).
- [x] Before stale cleanup, detect curated cluster deletion: curated cluster not in incoming snapshot. Currently `delete_stale_non_curated_rows()` preserves it from deletion, but no conflict is recorded to tell the operator "backend no longer includes your curated cluster."
- [x] Write conflict records for each detected curated cluster deletion.
- [x] Add PHPUnit coverage: missing curated cluster conflict recorded; no conflict for uncurated cluster changes; re-projection of same snapshot does not duplicate conflicts.

## Phase 3: Conflict-Aware Member Projection

- [x] In `IdentityMembersRepository::merge_snapshot_for_tenant()`, pre-load curated members for the tenant (single query).
- [x] Before each member upsert, detect membership reassignment conflict: backend moves a curated member to a different cluster.
- [x] Skip curated member upsert when conflict is detected (preserve local assignment).
- [x] Write conflict record with `conflict_code = 'member_cluster_reassignment'`, including both the backend-proposed cluster_uuid and the locally curated cluster_uuid.
- [x] Update `delete_stale_non_curated_rows()` to skip curated members and record conflicts for curated members absent from incoming snapshot.
- [x] Add PHPUnit coverage: curated member reassignment conflict recorded; curated member not deleted by stale cleanup; uncurated member moves freely.

## Phase 4: Projector Integration and Metrics

- [x] Wire `ConflictRepository` into `SnapshotProjector::project()` (constructor injection).
- [x] After merge completes, call `sync_state_repository->refresh_curation_metrics()` to update `conflict_count`.
- [x] Fire `do_action('acx_projection_conflicts_detected', $conflict_count, $tenant_id)` when conflicts are generated, for observability hooks.
- [x] Ensure `SyncStatusController` REST response includes up-to-date conflict count after projection.
- [x] Add PHPUnit integration test: full `project()` call with mixed curated/uncurated data produces expected conflict records and updated sync state metrics.

## Phase 5: Tests

- [x] Unit tests for `ConflictRepository::record_projection_conflict()`: correct table writes, required field validation, idempotent re-projection does not duplicate conflicts for same entity + backend_version (upsert semantics).
- [x] Unit tests for `ClustersRepository::merge_snapshot_for_tenant()` with conflict detection: curated cluster deletion conflict recorded, label preserved, curated cluster survives stale cleanup.
- [x] Unit tests for `IdentityMembersRepository::merge_snapshot_for_tenant()` with curation guard: curated member not overwritten, curated member not deleted, conflict recorded.
- [x] Integration test for `SnapshotProjector::project()`: mixed scenario with curated clusters, curated members, uncurated rows, and expected conflict count.
- [x] Integration test for end-to-end: `SyncPullJob` pulls snapshot, projects with conflicts, sync state updated, REST response shows conflict count.
- [x] All PHPUnit, PHPStan checks pass.

## Stretch Goals

- [ ] Conflict resolution API endpoints (resolve/dismiss individual conflicts) -- likely Phase 4 scope.
- [ ] Frontend conflict inbox UI surface -- likely Phase 4 scope.
- [ ] ~~Conflict de-duplication~~: addressed in Phase 2 via `record_projection_conflict()` upsert semantics.

## Success Criteria

- [x] Snapshot projection never overwrites a curated cluster label, person_id, curation_state, or dismissal.
- [x] Snapshot projection never silently reassigns a curated identity member to a different cluster.
- [x] When backend proposes a change that conflicts with existing curation, a `wp_acx_sync_conflicts` record is written with accurate machine_payload and local_payload.
- [x] `conflict_count` in sync state is updated after every projection that generates conflicts.
- [x] Curated members survive `delete_stale_non_curated_rows()` even when absent from the incoming snapshot.
- [x] All PHPUnit and PHPStan checks pass. Backend tests unaffected.
