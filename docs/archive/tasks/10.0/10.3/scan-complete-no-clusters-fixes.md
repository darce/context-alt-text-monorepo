# Fix Empty Cluster Cards After Scan Completion

## Problem Statement

After a scan completes and projection succeeds, the Workbench shows zero cluster cards and "No suggestions to review yet" because: (1) PHP returns singleton clusters that React silently filters out, (2) the projector can wipe all non-curated data on an empty snapshot with no recovery path, and (3) there is no user feedback when clusters exist but are all singletons.

## Workflow Principles

- When the client filters out all items from a response, it must explain why the list is empty rather than silently rendering nothing.
- Empty-snapshot projection must be a no-op, not a destructive wipe of existing data.
- Keep filtering close to the display layer when the filter result determines the UI feedback message.

## Terminology

- **Singleton cluster**: A cluster with `identity_count = 1`; a single face that matched no others.
- **Projection gate**: `should_use_local_projection_gate()` in `AbstractRecognitionProxyController`; returns TRUE when local sync state exists, causing the controller to read from WordPress DB instead of proxying to the backend.
- **Stale non-curated delete**: The `delete_stale_non_curated_rows()` path that removes all `is_user_confirmed = 0` rows when the incoming cluster ID list is empty.
- **Self-locking empty state**: After an empty-snapshot projection, `upsert_snapshot_version` writes `updated_at` with a real timestamp. The projection gate then locks TRUE (because `updated_at` is non-empty), but the local DB is empty; subsequent requests read from the empty local DB with no recovery path.

## Current State Analysis

- `ClustersRepository::list_top_unlabeled` SQL has no `identity_count` filter; it returns singletons that the frontend always discards (`TopClustersSection.tsx` line 371: `identity_count > 1`).
- `SnapshotProjector::project()` calls `merge_snapshot_for_tenant()` unconditionally, even when the snapshot is empty (HTTP 404 converted to `clusters: []` by `SnapshotClient`).
- `delete_stale_non_curated_rows()` with empty incoming IDs runs `DELETE FROM wp_acx_clusters WHERE tenant_id = ? AND is_user_confirmed = 0`, wiping all non-curated data.
- After empty-snapshot projection, `upsert_snapshot_version` writes `updated_at` regardless of cluster count. The projection gate then returns TRUE based on `updated_at`, so subsequent `top-unlabeled` requests read from empty local DB.
- `TopClustersSection` returns `null` (unmounts entirely) when all clusters are singletons; the user sees no explanation.
- Python backend `get_top_unlabeled` (in `cluster_repository.py`) uses `min_identity_count=2` at the SQL level. The PHP layer intentionally does NOT apply this filter so the React client can distinguish "no clusters" from "only singletons" and show appropriate feedback.

## Proposed Solution

Two independent fixes targeting two layers:

1. **PHP empty-snapshot guard**: In `SnapshotProjector::project()`, skip ALL writes (merge, upsert, metrics) when the snapshot is empty. The check should be: `$snapshot['empty'] === true` OR (clusters array is empty AND `snapshot_version === 0`). Commit the empty transaction and return immediately. This prevents both the destructive delete AND the self-locking empty state; `upsert_snapshot_version` must NOT be called because it writes `updated_at`, which makes `should_use_local_projection_gate` return TRUE even when the local DB is empty and `snapshot_version` is 0. The caller (`SyncPullJob::do_sync`) still records `SyncPullResult::OK` after projection. `wp_schedule_single_event` deduplication prevents multiple bootstrap syncs from being queued simultaneously, so the backend is not hammered with retries.

2. **React singleton feedback**: When `TopClustersSection` receives clusters from the API and all have `identity_count <= 1`, show an informational message instead of returning `null`.

3. **Stretch hardening follow-up**: Filter singleton clusters in PHP `list_top_unlabeled`, return `singleton_count` metadata in the REST payload so React can still explain the singleton-only state, and normalize local cluster/person label state so confirmed clusters cannot drift back into the naming queue.

Implementation update: the follow-up optimization is now complete. The local `top-unlabeled` response is an envelope with `clusters` plus `singleton_count`, `list_top_unlabeled` excludes `identity_count < 2` and `is_user_confirmed = 1` rows, and local bind/rename read paths now normalize synthetic `cluster-*` labels and person-backed labels consistently.

## Patterns to Follow

### PHP empty-snapshot guard

```php
// class-snapshot-projector.php project() -- after extracting clusters/members/version
$clusters         = is_array( $snapshot['clusters'] ?? null ) ? $snapshot['clusters'] : array();
$members          = is_array( $snapshot['members'] ?? null ) ? $snapshot['members'] : array();
$is_empty_snapshot = ( true === ( $snapshot['empty'] ?? false ) )
    || ( empty( $clusters ) && 0 === $snapshot_version );

if ( $is_empty_snapshot ) {
    // Skip ALL writes: no conflict detection, no merge (prevents destructive delete),
    // no upsert_snapshot_version (prevents self-locking empty state via updated_at),
    // no refresh_curation_metrics. SyncPullJob::do_sync() still records SyncPullResult::OK.
    $wpdb->query( 'COMMIT' );
    return;
}
```

### PHP observability logging

```php
// class-snapshot-projector.php -- after merge calls
$non_singleton_count = count( array_filter(
    $clusters,
    static function ( $c ) {
        return ( (int) ( $c['identity_count'] ?? 0 ) ) > 1;
    }
) );
do_action(
    'acx_snapshot_projected',
    $normalized_tenant_id,
    count( $clusters ),
    $non_singleton_count,
    $snapshot_version
);
```

### React singleton-aware empty state

```tsx
// TopClustersSection.tsx -- replace the null return after singleton filter
// topClusters.length > 0 means API returned clusters;
// nonSingletons.length === 0 means they were all identity_count <= 1
if (topClusters.length > 0 && nonSingletons.length === 0) {
  return (
    <div className="acx-top-clusters-section acx-top-clusters-section--empty">
      <p>{__('All detected groups contain only a single photo. Groups with multiple photos will appear here.', 'alt-context')}</p>
    </div>
  );
}
```

## Functions to Change

| File | Function/Target | Change |
| --- | --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | `project` | Add early return when snapshot is empty (skip ALL writes: merge, upsert, metrics) |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | `project` | Add observability logging after merge (cluster count, non-singleton count, version) |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/TopClustersSection.tsx` | `TopClustersSection` | Replace `return null` after singleton filter with informational message |
| `apps/prototype-wp-alt-context/tests/Unit/sovereign/sync/SnapshotProjectorTest.php` | new test | Verify empty-snapshot guard skips ALL writes (merge, upsert, metrics) |
| `apps/prototype-wp-alt-context/tests/Unit/sovereign/sync/SnapshotProjectorTest.php` | new test | Verify project-then-read: projected non-singleton clusters appear in `list_top_unlabeled` |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/__tests__/TopClustersSection.test.tsx` | new test | Verify singleton-only empty state renders informational message |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-clusters-repository.php` `delete_stale_non_curated_rows` | The destructive delete path that the empty-snapshot guard prevents from firing |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client.php` `fetch_snapshot` | Synthesizes empty snapshot on 404; sets `empty: true` flag |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` `upsert_snapshot_version` | Writes `updated_at` unconditionally; empty-snapshot guard prevents this call to avoid the self-locking empty state |
| `apps/prototype-wp-alt-context/src/api/class-abstract-recognition-proxy-controller.php` `should_use_local_projection_gate` | Returns TRUE when `updated_at` is non-empty OR `version > 0`; skipping `upsert_snapshot_version` on empty snapshots keeps the gate FALSE |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` `do_sync` | Calls `projector->project()` then records `SyncPullResult::OK`; cooldown transient is set only on error paths; `wp_schedule_single_event` deduplication prevents retry storms |
| `apps/prototype-wp-alt-context/src/sovereign/class-cluster-facade.php` `list_top_unlabeled` | Delegates to repository; no changes needed |
| `apps/prototype-wp-alt-context/src/sovereign/mappers/class-cluster-response-mapper.php` `map_top_unlabeled_clusters` | Maps DB rows to REST response; no changes needed |
| `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` `get_top_unlabeled` | Python backend uses `min_identity_count=2`; PHP intentionally omits this filter so React can detect singletons |
| `docs/tasks/10.0/10.3/scan-complete-no-clusters-root-cause-report.md` | Root cause investigation that produced these fixes |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `wp-proxy` | `apps/prototype-wp-alt-context/src/**`, `apps/prototype-wp-alt-context/tests/Unit/**` | None | `cd apps/prototype-wp-alt-context && vendor/bin/phpunit 2>&1 \| tee /tmp/phpunit_wp-proxy.txt` |
| `frontend` | `apps/prototype-wp-alt-context/js/**` | `wp-proxy` (contract only; REST response shape unchanged; singletons still included) | `cd apps/prototype-wp-alt-context && npx vitest run 2>&1 \| tee /tmp/vitest_frontend.txt` |

### Merge Order

1. `wp-proxy` (empty-snapshot guard + observability)
2. `frontend` (singleton-aware empty state)

### Manifest

```bash
make lane-manifest-init TASK=scan-complete-no-clusters-fixes LANE_IDS='wp-proxy frontend' TASK_PLAN=docs/tasks/10.0/10.3/scan-complete-no-clusters-fixes.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools (`worker_start_all`, `worker_status`, `worker_stop`) with `backend="codex-subagent"`.
- **Shell fallback**: Use `make lane-open`, `make lane-run`, `make lane-handoff`, and `make lane-intake` from the orchestrator root.

---

# Consolidated Checklist

## Completed

- [x] Root cause investigation (see `scan-complete-no-clusters-root-cause-report.md`)
- [x] Second-pass pipeline audit confirming H1 as most likely root cause

## Phase 0: Scaffolding

- [x] Add empty-snapshot guard stub in `SnapshotProjector::project`.
- [x] Create PHPUnit test file for empty-snapshot guard.
- [x] Create Vitest test stub for singleton-aware empty state.
- [x] Verify scaffolds compile: `vendor/bin/phpunit --filter scaffold` / `npx vitest run --reporter=verbose`.

## Phase 1: PHP Fixes (wp-proxy lane)

- [x] Add empty-snapshot guard in `SnapshotProjector::project()`: skip ALL writes (merge, upsert, metrics) when snapshot is empty AND `snapshot_version === 0`.
- [x] Add `acx_snapshot_projected` action hook with cluster count, non-singleton count, and snapshot version after successful merge.
- [x] PHPUnit test: `SnapshotProjector::project()` with empty snapshot skips ALL writes; `get_snapshot_version` returns 0 and `get_last_updated` returns null/empty afterward.
- [x] PHPUnit test: `SnapshotProjector::project()` with non-empty snapshot proceeds normally.
- [x] PHPUnit test: `SnapshotProjector::project()` with empty clusters but `snapshot_version > 0` still merges (delta sync, not error). Covered by `testProjectRecordsCuratedClusterDeletionConflictsAndRefreshesMetrics()` and `testProjectEmitsConflictHookForMemberConflictsAfterMetricsRefresh()`. (BR-SCANCLUSTERS-04 invalid)
- [x] PHPUnit test: project non-singleton clusters then verify `list_top_unlabeled` returns them (projection/read path regression for BR-SCANCLUSTERS-01).

## Phase 2: React Fixes (frontend lane)

- [x] Replace `return null` after singleton filter in `TopClustersSection` with informational message.
- [x] Style the singleton-aware empty state using `--acx-*` design tokens.
- [x] Vitest test: `TopClustersSection` renders informational message when API returns clusters but all are singletons.
- [x] Vitest test: `TopClustersSection` renders normally when non-singleton clusters exist.
- [x] Vitest test: `TopClustersSection` renders nothing (returns null) when API returns zero clusters.

## Phase 3: Integration Verification

- [x] Run full PHP test suite: `cd apps/prototype-wp-alt-context && vendor/bin/phpunit`. (395 tests, 1664 assertions)
- [x] Run full Vitest suite: `cd apps/prototype-wp-alt-context && npx vitest run`. (51 files, 415 tests)
- [ ] Manual verification: confirm no regressions in cluster card rendering when non-singleton clusters exist.

## Stretch Goals

- [x] Add `identity_count >= 2` filter to PHP `list_top_unlabeled` SQL with a companion `singleton_count` metadata field in the REST response, so the endpoint stops returning singletons while React retains the ability to explain the singleton-only state.
- [x] Complete Option B state normalization for local cluster/person labeling so `c.label`, `person_id`, `is_user_confirmed`, and `curation_state` cannot drift apart across bind, rename, unbind, and local read paths.

### Stretch Goal: Complete Option B State Normalization

Treat this as a follow-up hardening pass after the immediate queue fix. The goal is to remove the current antipattern where different parts of the local projection infer cluster label state from different columns.

#### Target invariants

- If `person_id` is non-null, the cluster is locally curated and must never be eligible for `top-unlabeled`.
- If `person_id` is non-null, the canonical local display label must resolve to the bound person's name.
- If `is_user_confirmed = 0`, the cluster is eligible for unlabeled/auto-label logic only when the stored label is null, empty, or synthetic `cluster-*`.
- Read paths must not infer manual-vs-auto semantics from "non-empty label string" alone.

#### Write-path changes

- Update the bind-to-person flow in `apps/prototype-wp-alt-context/src/api/class-api.php` so the same transaction that sets `person_id`, `curation_state = 'confirmed'`, and `is_user_confirmed = 1` also writes `c.label = person.name` (or the newly created person name).
- Keep the current unbind/delete-person behavior of preserving confirmed curation, but make that rule explicit: once a person-bound cluster is dissociated, the last curated human-readable label remains in `c.label` unless the operation is a full curation reset.
- Update the person rename flow in `apps/prototype-wp-alt-context/src/api/class-api.php` so renaming a person also updates `c.label` for all bound clusters in the same transaction, increments the affected cluster revisions, and queues the necessary replay metadata. Without this, bind-time synchronization alone still leaves stale labels behind after person edits.
- Preserve the existing reset path semantics in `ClustersRepository::reset_curation()` where a true curation reset clears `label`, `person_id`, and `is_user_confirmed` together.

#### Read-path normalization

- Tighten `ClustersRepository::list_top_unlabeled()` to require `c.is_user_confirmed = 0` in addition to the existing synthetic-label predicate. This is still the immediate correctness guard even under Option B.
- Normalize local top-unlabeled payload semantics in `ClusterResponseMapper::map_top_unlabeled_clusters()` so synthetic `cluster-*` labels serialize as auto/unlabeled (`is_labeled = false`, `is_auto_label = true`, and either `label = null` or another explicitly documented representation).
- Audit other local read paths that still select raw `c.label` directly, especially `IdentityMembersRepository`, and either:
  - switch them to `COALESCE(p.name, c.label)` when a bound person exists, or
  - funnel them through a shared normalization rule so person-bound clusters do not depend on stale copied labels.
- Keep XMP/export behavior aligned with the same rule set so a bound person name is treated as curated while synthetic `cluster-*` labels remain non-curated.

#### Regression coverage required

- PHPUnit: binding a `cluster-*` row to a person removes it from `list_top_unlabeled()` even if the raw label started synthetic.
- PHPUnit: binding a cluster to a person updates both `person_id` and `c.label` in one transaction.
- PHPUnit: renaming a person cascades the new name to all bound clusters and increments the expected local revisions.
- PHPUnit: deleting or unbinding a person does not reintroduce the cluster into `top-unlabeled` unless curation is explicitly reset.
- PHPUnit: `ClusterResponseMapper::map_top_unlabeled_clusters()` marks synthetic labels as auto/unlabeled.
- PHPUnit or integration: member list/XMP-facing reads return the person name for bound clusters after rename, not a stale copied label.

#### Success criteria for the stretch goal

- A confirmed or person-bound cluster cannot reappear in the naming queue in local-authority mode.
- Renaming a person updates every local UI/export surface that depends on cluster labels without requiring a projection refresh.
- Synthetic `cluster-*` labels are treated consistently as auto/unlabeled across repository queries, REST payloads, React, and metadata/export code.

## Success Criteria

- [x] Empty-snapshot projection does not delete existing cluster data and does not write sync state (no self-locking empty state).
- [x] Workbench shows informational message when all clusters are singletons instead of showing nothing.
- [x] Projection-then-read path test proves non-singleton clusters survive the project/query round-trip.
- [x] Confirmed or person-bound clusters cannot reappear in the local naming queue after bind/rename flows.
- [x] Singleton-only tenants still produce an explanatory UI state after the local API filters singleton rows.
- [x] All existing PHPUnit and Vitest tests continue to pass.
