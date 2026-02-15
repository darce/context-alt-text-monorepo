# Sovereign Phase 2: Read-Path Flip Task Plan (v4.13.1)

## Problem Statement

Cluster UI currently proxies all reads through the backend. If the backend is unreachable, cluster views show empty state despite local projection tables containing valid data (populated by Phase 1 snapshot ingestion). The read path must flip to local-first so previously projected clusters render from WordPress-owned storage.

## Workflow Principles

- Read-path changes only; no mutation changes in this phase (dual-write is Phase 3).
- Controllers fall back to proxy when local projection is empty or uninitialized (graceful migration, not hard cutover).
- Backend snapshot endpoint (`GET /tenants/{tenant_id}/clusters/snapshot`) is a parallel dependency. This task can proceed with fixture-projected data.
- Response shape mapping must produce the same JSON structure frontend consumers expect.

## Terminology

- **Local-first read**: controller queries WordPress-owned tables first; falls through to proxy only when local projection has no data for the given tenant.
- **Response mapper**: translates repository row arrays into the JSON shape the frontend already expects from proxied backend responses.
- **Sync status**: metadata surfaced to the UI indicating last successful sync time and projection age.

## Current State Analysis

What works:

- `ClustersRepository::list_for_tenant()` and `::find_by_uuid()` can serve paginated cluster list and single-cluster detail from local tables.
- `IdentityMembersRepository::list_for_cluster()` can serve cluster member lists from local tables.
- `SyncStateRepository::get_snapshot_version()` tracks the last ingested snapshot version and timestamp.
- All three controllers (`ClustersController`, `ClusterMutationsController`, `MediaIdentitiesController`) extend `AbstractRecognitionProxyController` which provides `proxy_request()` as a shared HTTP gateway.
- Frontend API layer (`clusterApiQueries.ts`, `clusterApiMembers.ts`) calls WP REST proxy endpoints and expects the same JSON shapes the backend returns.

What is missing for Phase 2:

- **No query filtering on repositories** -- `list_for_tenant()` has no `search`, `labeled_only`, or `top-unlabeled` filter support.
- **No `list_labels()` method** -- `ClustersController::list_cluster_labels()` needs a `SELECT DISTINCT label` query.
- **No `list_for_media_ids()` method** -- `MediaIdentitiesController::get_media_identities()` needs members grouped by `attachment_id`.
- **No response mapper** -- repository rows are raw database arrays; frontend expects backend-shaped JSON with nested objects.
- **No sync status endpoint** -- frontend has no way to surface last-sync time or stale-age indicator.
- **No fallback logic** -- controllers don't check local tables first, then fall through to proxy.

## Proposed Solution

Add repository query methods and response mappers to cover all six read endpoints. Modify controllers to check local projection first (via a local-read service facade), falling back to `proxy_request()` only when local data is empty (zero rows for tenant). Add a lightweight REST endpoint that returns sync-state metadata for frontend consumption. Add a frontend sync-status indicator component that displays last-sync time and connects via React Query.

Scope boundary: mutations (`ClusterMutationsController`) remain proxy-only. Dual-write is Phase 3.

## Patterns to Follow

### Pattern A: Local-First Read with Proxy Fallback

```php
<?php
declare(strict_types=1);

public function list_clusters(WP_REST_Request $request): WP_REST_Response|WP_Error {
    $tenant_id = $this->get_tenant_id();
    $limit     = (int) $request->get_param('limit') ?: 50;
    $offset    = (int) $request->get_param('offset') ?: 0;
    $search    = (string) ($request->get_param('search') ?? '');

    // Local-first: read from projection tables.
    $local_rows = $this->clusters_repository->list_for_tenant(
        $tenant_id,
        $limit,
        $offset,
        ['search' => $search, 'labeled_only' => (bool) $request->get_param('labeled_only')]
    );

    if (null !== $local_rows) {
        return new WP_REST_Response(
            $this->response_mapper->map_cluster_list($local_rows, $tenant_id),
            200
        );
    }

    // Fallback: proxy to backend when local projection is uninitialized.
    return $this->proxy_request('GET', '/recognition/clusters', [], [
        'tenant_id' => $tenant_id,
        'limit'     => $limit,
        'offset'    => $offset,
    ]);
}
```

### Pattern B: Response Shape Mapping

```php
<?php
declare(strict_types=1);

final class ClusterResponseMapper {
    /**
     * @param array<int, array<string, mixed>> $rows
     * @return array<string, mixed>
     */
    public function map_cluster_list(array $rows, string $tenant_id): array {
        return [
            'clusters'  => array_map([$this, 'map_cluster_row'], $rows),
            'tenant_id' => $tenant_id,
        ];
    }

    /**
     * @param array<string, mixed> $row
     * @return array<string, mixed>
     */
    public function map_cluster_row(array $row): array {
        return [
            'cluster_id'               => $row['cluster_uuid'] ?? '',
            'label'                    => $row['label'] ?? null,
            'curation_state'           => $row['curation_state'] ?? 'uncurated',
            'identity_count'           => (int) ($row['identity_count'] ?? 0),
            'representative_thumb_url' => $this->resolve_thumb_url($row),
            'is_user_confirmed'        => (bool) ($row['is_user_confirmed'] ?? false),
            'updated_at'               => $row['updated_at'] ?? '',
        ];
    }
}
```

### Pattern C: Sync Status REST Endpoint

```php
<?php
declare(strict_types=1);

public function get_sync_status(WP_REST_Request $request): WP_REST_Response {
    $tenant_id = $this->get_tenant_id();
    $version   = $this->sync_state_repository->get_snapshot_version($tenant_id);
    $updated   = $this->sync_state_repository->get_last_updated($tenant_id);

    return new WP_REST_Response([
        'last_snapshot_version' => $version,
        'last_synced_at'        => $updated,
        'is_stale'              => $this->is_projection_stale($updated),
    ], 200);
}
```

### Pattern D: Frontend Sync Indicator (React Query)

```tsx
const useSyncStatus = () => {
  return useQuery({
    queryKey: ["acx", "sync-status"],
    queryFn: () =>
      apiFetch<SyncStatus>({ path: "/acx/v1/recognition/sync-status" }),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
};
```

## Functions to Change

| File                                                                   | Change                                                                                                                  |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `src/sovereign/repositories/class-clusters-repository.php`             | Add `search` and `labeled_only` filters to `list_for_tenant()`. Add `list_labels()` and `list_top_unlabeled()` methods. |
| `src/sovereign/repositories/interface-clusters-repository.php`         | Add method signatures for new query methods.                                                                            |
| `src/sovereign/repositories/class-identity-members-repository.php`     | Add `list_for_media_ids()` method (SELECT by attachment_id IN (...)).                                                   |
| `src/sovereign/repositories/interface-identity-members-repository.php` | Add `list_for_media_ids()` signature.                                                                                   |
| `src/sovereign/repositories/class-sync-state-repository.php`           | Add `get_last_updated()` method.                                                                                        |
| `src/sovereign/mappers/class-cluster-response-mapper.php`              | **New.** Maps repository rows to backend-compatible JSON shapes.                                                        |
| `src/sovereign/mappers/class-member-response-mapper.php`               | **New.** Maps member rows to backend-compatible JSON shapes.                                                            |
| `src/api/class-clusters-controller.php`                                | Inject repositories + mapper. Replace proxy reads with local-first + fallback pattern.                                  |
| `src/api/class-media-identities-controller.php`                        | Inject member repository + mapper. Replace proxy read with local-first grouping.                                        |
| `src/api/class-recognition-controller.php`                             | Wire repositories and mappers into sub-controller construction.                                                         |
| `src/api/class-api.php`                                                | Register sync-status REST route.                                                                                        |
| `js/admin/api/recognition/syncApi.ts`                                  | **New.** `fetchSyncStatus()` API call.                                                                                  |
| `js/admin/hooks/useSyncStatus.ts`                                      | **New.** React Query hook for sync status.                                                                              |
| `js/admin/components/SyncStatusIndicator.tsx`                          | **New.** Displays last-sync time and stale warning.                                                                     |

## Related Files

| File                                                                                         | Note                                                         |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md`                                             | Source epic; Phase 2 definition and exit criteria.           |
| `docs/tasks/4.0/4.13.1/wp-sovereign-phase1-local-projection-task-plan.md`                    | Phase 1 foundation this task builds on (closed).             |
| `src/sovereign/sync/class-snapshot-projector.php`                                            | Unchanged; already complete for write side.                  |
| `src/api/class-cluster-mutations-controller.php`                                             | Remains proxy-only. Phase 3 adds dual-write.                 |
| `src/api/class-suggestions-controller.php`                                                   | Remains proxy-only. Suggestions are backend-computed.        |
| `docs/agentic/contracts/cluster-snapshot-api.md`                                             | Snapshot contract (draft); backend dependency for live data. |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/clusters.py` | Backend snapshot route implementation target.                |

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add `ClusterResponseMapper` and `MemberResponseMapper` class shells with typed method signatures.
- [x] Add `list_labels()`, `list_top_unlabeled()` method stubs to `ClustersRepositoryInterface`.
- [x] Add `list_for_media_ids()` stub to `IdentityMembersRepositoryInterface`.
- [x] Add `get_last_updated()` stub to `SyncStateRepositoryInterface`.
- [x] Add test stubs for new repository methods, mappers, and controller local-read paths.
- [x] Verify scaffolds compile: `composer test`, `composer cs-check`, `npm run typecheck`.

## Phase 1: Repository Query Extensions

- [x] Implement `search` filter in `ClustersRepository::list_for_tenant()` (`WHERE label LIKE %search%`).
- [x] Implement `labeled_only` filter (`WHERE label IS NOT NULL AND label != ''`).
- [x] Implement `list_labels()` (`SELECT DISTINCT label WHERE tenant_id = ? AND label IS NOT NULL`).
- [x] Implement `list_top_unlabeled()` (filter by empty label, order by identity_count DESC, include representative data).
- [x] Implement `IdentityMembersRepository::list_for_media_ids()` (SELECT by attachment_id IN with cluster join for tenant scope).
- [x] Implement `SyncStateRepository::get_last_updated()`.
- [x] Add unit tests for all new query methods with fixture data.

## Phase 2: Response Mappers

- [x] Implement `ClusterResponseMapper::map_cluster_list()` and `::map_cluster_row()`.
- [x] Implement `ClusterResponseMapper::map_cluster_detail()` (single cluster with expanded fields).
- [x] Implement `ClusterResponseMapper::map_labels_list()`.
- [x] Implement `MemberResponseMapper::map_cluster_members()`.
- [x] Implement `MemberResponseMapper::map_media_identities()` (grouped by attachment_id).
- [x] Resolve representative thumbnail URLs (local `acx://` keys to `wp_get_attachment_url()` URLs).
- [x] Add mapper tests verifying output matches expected backend JSON shapes.

## Phase 3: Controller Read-Path Flip

- [x] Modify `ClustersController` constructor to accept repositories + mapper.
- [x] Flip `list_clusters()` to local-first with proxy fallback.
- [x] Flip `get_cluster_detail()` to local-first with proxy fallback.
- [x] Flip `get_cluster_members()` to local-first with proxy fallback.
- [x] Flip `list_cluster_labels()` to local-first with proxy fallback.
- [x] Flip `list_top_unlabeled_clusters()` to local-first with proxy fallback.
- [x] Modify `MediaIdentitiesController` to read local projection with proxy fallback.
- [x] Update `RecognitionController` composition root to wire repositories and mappers.
- [x] Add controller tests verifying local-read path returns expected responses.
- [x] Add controller tests verifying proxy fallback when local projection is empty.

## Phase 4: Sync Status Endpoint and Frontend

- [x] Register `GET acx/v1/recognition/sync-status` route in `class-api.php`.
- [x] Implement sync-status handler returning `last_snapshot_version`, `last_synced_at`, `is_stale`.
- [x] Add `syncApi.ts` with `fetchSyncStatus()`.
- [x] Add `useSyncStatus` React Query hook with polling.
- [x] Add `SyncStatusIndicator` component displaying last-sync time and stale warning.
- [x] Integrate indicator into cluster list view.
- [x] Add frontend tests for sync status hook and indicator component.

## Phase 5: Verification Gate

- [x] `composer test` passes with zero failures.
- [x] `composer phpstan` passes with zero errors.
- [x] `npm run test` passes with zero failures.
- [x] All existing tests pass (PHP + JS).
- [x] New repository query tests pass with fixture data.
- [x] New mapper tests verify backend-compatible JSON shapes.
- [x] Controller tests verify local-first reads and proxy fallback.
- [ ] Manual smoke: activate plugin with projected fixture data, disable backend, confirm cluster list renders.

## External Dependencies (Carried from Phase 1)

| Dependency                                                      | Owner               | Last Updated | Status        | Blocker                                                                 |
| --------------------------------------------------------------- | ------------------- | ------------ | ------------- | ----------------------------------------------------------------------- |
| `GET /tenants/{tenant_id}/clusters/snapshot` contract finalized | recognition-service | 2026-02-10   | Not started   | Required for live snapshot pulls; plugin fixture projection is complete |
| `GET /tenants/{tenant_id}/clusters/snapshot` route implemented  | recognition-service | 2026-02-10   | Not started   | Backend API required before end-to-end sync validation                  |
| Snapshot endpoint dependency tracked with owner/date/blocker    | this plan           | 2026-02-14   | Tracked above | --                                                                      |

## Stretch Goals (Carried from Phase 1)

- [ ] Add optional admin diagnostics panel for last snapshot version and last sync timestamp (natural extension of Phase 4 sync-status work).

## Success Criteria

- [x] Cluster list, detail, members, labels, and top-unlabeled endpoints read from local projection when data exists.
- [ ] Disabling backend connectivity does not empty cluster UI when local projection has data.
- [x] Proxy fallback activates transparently when local projection is uninitialized.
- [x] Frontend displays sync status indicator with last-sync time.
- [x] Snapshot endpoint contract/route dependency is explicitly tracked with owner/date and blocker status.
- [x] All six automated gates pass after changes.
