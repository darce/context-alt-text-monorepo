# Phase 1: Unified Pipeline Lifecycle

## Problem Statement

Operators launch a scan and see it transition through "analyzing" and "clustering" phases, but the pipeline ends abruptly at clustering completion. The final step -- local projection of backend results into WordPress tables -- is invisible to the operator. If projection fails or is delayed, the operator sees stale cluster data with no explanation. The backend has no confirmation that WordPress successfully ingested its output, so it cannot distinguish "projection succeeded" from "projection never happened."

## Workflow Principles

- **One visible pipeline**: operators see a single flow from scan initiation through local visibility, not disjoint jobs that require mental stitching.
- **Backend work is not done until WordPress sees it**: clustering completion on the description service is a compute milestone, not a product milestone. The operator-facing pipeline completes only after local projection succeeds.
- **Projection acknowledgement closes the loop**: the plugin tells the backend "I received and projected version N," so the backend can mark its own job as fully delivered and align future proposals to that baseline.
- **No silent stale windows**: if projection is delayed or fails, the UI must show that the pipeline is waiting on sync rather than silently presenting outdated data.

## Terminology

- **Pipeline**: the full operator-visible lifecycle: analyze -> clustering -> projection -> acknowledged.
- **Pipeline job**: the backend job entity that tracks all phases. The frontend uses the original scan job ID throughout.
- **Projection**: the process of materializing backend clustering output into local WordPress tables (`wp_acx_clusters`, `wp_acx_identity_members`).
- **Projection acknowledgement**: a signal from the plugin to the backend confirming that a specific snapshot version has been projected locally.
- **Pipeline phase**: one of `analyzing`, `clustering`, `projecting`, `completed`, `failed`.
- **Resolve through pipeline**: the backend pattern of transparently presenting auto-chained follow-up jobs under the original scan job ID.

## Current State Analysis

- Backend auto-chains clustering after scan completion via `_refresh_job_progress()` in `scan.py`, creating an `IdentityClusteringJob` with `payload.scan_job_id`.
- `_resolve_pipeline_job()` in `analyze.py` transparently resolves a scan job ID to its follow-up clustering job when polled via `GET /jobs/{job_id}`.
- SSE stream at `/jobs/{job_id}/stream` emits phase transitions (`type: analyze` -> `type: clustering`) so the frontend sees the pipeline advance.
- Frontend `useJobStateMachineEffects` detects `backendHandledClustering` and skips redundant frontend-triggered clustering.
- After clustering completes, the frontend invalidates queries (`clusters.all`, `media.identities()`) which triggers `useSyncStatus` refetch and implicit sync pull.
- **Gap**: there is no explicit "projecting" or "awaiting projection" phase visible to the operator. The pipeline ends at "clustering completed."
- **Gap**: there is no backend endpoint for the plugin to confirm projection receipt. The backend cannot distinguish "WordPress projected successfully" from "WordPress never synced."
- **Gap**: if sync pull fails after clustering, the operator sees stale data and must manually trigger "Sync now" -- there is no automatic connection between pipeline completion and projection.
- **Gap**: `SyncStatusIndicator` and job status are independent UI surfaces with no integration. The operator must mentally combine them.
- **Gap**: the sync pull job uses a 30-second cooldown transient that can block post-pipeline sync even when triggered automatically after job completion.

## Proposed Solution

Extend the existing pipeline infrastructure with three additions:

1. **Backend projection-ready signaling**: after clustering completes, the backend marks the job as `projection_ready` with a `snapshot_version` field. The SSE stream and poll responses include this phase. The frontend knows it must sync before showing "completed."

2. **Plugin projection acknowledgement**: after successful snapshot projection, the plugin calls `POST /jobs/{job_id}/acknowledge-projection` with the projected `snapshot_version`. The backend transitions the job to `completed` and records the acknowledgement timestamp.

3. **Frontend unified pipeline state**: the job state machine gains a `projecting` phase between `clustering` and `completed`. During this phase, the frontend triggers a sync pull, monitors its outcome, and sends the acknowledgement. If projection fails, the pipeline shows a recoverable error with a "Retry sync" action.

This approach reuses the existing resolve-through-pipeline pattern, the existing sync pull infrastructure, and the existing SSE streaming. The new code is limited to: one backend endpoint, one new phase in the frontend state machine, and wiring between the job completion and sync pull.

## Patterns to Follow

### Backend: Projection-Ready Phase Transition

```python
# In scan.py, after auto-created clustering job completes:
# The clustering worker already marks the job as completed.
# Extend the job status response to include projection metadata.

# In analyze.py _job_to_pipeline_response():
if resolved_job.status == JobStatus.COMPLETED and resolved_job.type == JobType.CLUSTERING:
    # Check if projection has been acknowledged
    ack = await repo.get_projection_acknowledgement(requested_job_id)
    if ack is None:
        response.status = "projection_ready"
        response.progress.phase = "awaiting_projection"
        response.snapshot_version = await get_latest_snapshot_version(tenant_id)
    else:
        response.status = "completed"
        response.progress.phase = "complete"
```

### Backend: Acknowledge-Projection Endpoint

```python
@router.post("/jobs/{job_id}/acknowledge-projection")
async def acknowledge_projection(
    job_id: str,
    request: AcknowledgeProjectionRequest,
    tenant=Depends(get_tenant),
    session: AsyncSession = Depends(get_session),
):
    """
    WordPress confirms that snapshot_version N was projected locally.
    Idempotent: repeated calls with the same version are safe no-ops.
    """
    await repo.record_projection_acknowledgement(
        job_id=job_id,
        tenant_id=str(tenant.id),
        snapshot_version=request.snapshot_version,
        acknowledged_at=datetime.utcnow(),
    )
    return {"status": "acknowledged", "snapshot_version": request.snapshot_version}
```

### Plugin: Projection Acknowledgement After Sync Pull

```php
// In class-sync-pull-job.php, after successful projection:
private function do_sync(string $tenant_id, string $transient_key): bool {
    $snapshot = $this->client->fetch_snapshot( $tenant_id );
    if ( is_wp_error( $snapshot ) ) {
        set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
        return false;
    }

    try {
        $this->projector->project( $tenant_id, $snapshot );

        // NEW: acknowledge projection to backend
        $version = (int) ( $snapshot['snapshot_version'] ?? 0 );
        if ( $version > 0 && ! empty( $snapshot['source_job_id'] ) ) {
            $this->client->acknowledge_projection(
                $tenant_id,
                $snapshot['source_job_id'],
                $version
            );
        }

        return true;
    } catch ( Throwable $throwable ) {
        set_transient( $transient_key, 1, self::SYNC_COOLDOWN_SECONDS );
        do_action( 'acx_sync_pull_failed', [ /* ... */ ] );
        return false;
    }
}
```

### Frontend: Pipeline Phase with Projection Step

```typescript
// Extend job phase derivation in jobStateMachineUtils.ts:
type PipelinePhase = 'idle' | 'analyzing' | 'clustering' | 'projecting' | 'completed' | 'failed';

function derivePipelinePhase(
  sseStatus: string | undefined,
  sseProgress: JobProgress | undefined,
  syncStatus: SyncStatusResponse | undefined,
): PipelinePhase {
  if (!sseStatus) return 'idle';

  // SSE reports projection_ready -> we need to sync
  if (sseProgress?.phase === 'awaiting_projection') return 'projecting';

  // Clustering still running
  if (sseProgress?.phase === 'clustering') return 'clustering';

  // Analyzing
  if (sseStatus === 'running' && sseProgress?.phase === 'detecting') return 'analyzing';

  if (sseStatus === 'completed') return 'completed';
  if (sseStatus === 'failed') return 'failed';

  return 'analyzing';
}
```

### Frontend: Auto-Trigger Sync on Projection-Ready

```typescript
// In useJobStateMachineEffects.ts:
useEffect(() => {
  if (pipelinePhase !== 'projecting') return;

  // Trigger sync pull to project backend results locally
  syncTrigger.mutate(undefined, {
    onSuccess: (data) => {
      if (data.synced) {
        // Acknowledge projection to backend via the job endpoint
        acknowledgeProjection(latestJobId, data.last_snapshot_version);
      }
    },
  });
}, [pipelinePhase]);
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | `_job_to_pipeline_response()` | Add `projection_ready` / `awaiting_projection` phase when clustering is complete but not yet acknowledged |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` | new endpoint | Add `POST /jobs/{job_id}/acknowledge-projection` with idempotent acknowledgement recording |
| `apps/prototype-description-service/recognition/infrastructure/repositories/job_repository.py` | new methods | Add `record_projection_acknowledgement()` and `get_projection_acknowledgement()` |
| `apps/prototype-description-service/db/models/jobs.py` | `identity_clustering_jobs` or new table | Add projection acknowledgement tracking (job_id, tenant_id, snapshot_version, acknowledged_at) |
| `apps/prototype-description-service/recognition/domain/job.py` | `JobPhase` enum | Add `AWAITING_PROJECTION = "awaiting_projection"` |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-sync-pull-job.php` | `do_sync()` | After successful projection, call `acknowledge_projection()` on the backend client |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-client-transport.php` | new method | Add `acknowledge_projection(tenant_id, job_id, snapshot_version)` HTTP call |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts` | clustering-complete effect | Add `projecting` phase: trigger sync pull, then send acknowledgement on success |
| `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts` | `derivePipelinePhase()` | Add `projecting` phase between `clustering` and `completed` |
| `apps/prototype-wp-alt-context/js/admin/api/recognition/scanApi.ts` | new function | Add `acknowledgeProjection(jobId, snapshotVersion)` API call |
| `apps/prototype-wp-alt-context/js/admin/pages/workbench/SyncStatusIndicator.tsx` | status display | Integrate pipeline phase: show "Syncing results..." during `projecting` phase |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-wp-alt-context/src/sovereign/sync/class-snapshot-projector.php` | Existing atomic projection logic; not changed but must understand its transaction and version semantics |
| `apps/prototype-wp-alt-context/src/sovereign/repositories/class-sync-state-repository.php` | Existing sync state tracking; may need to expose `last_projected_job_id` for acknowledgement correlation |
| `apps/prototype-wp-alt-context/src/api/class-sync-status-controller.php` | Existing sync status REST surface; `trigger_sync` method is the entry point for the projecting phase |
| `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts` | SSE stream hook; must pass through `awaiting_projection` phase from backend |
| `apps/prototype-wp-alt-context/js/admin/hooks/useSyncTrigger.ts` | Existing sync trigger mutation; reused during projecting phase |
| `apps/prototype-description-service/recognition/worker/handlers/scan.py` | Auto-chains scan->clustering; no changes needed but must understand linkage via `payload.scan_job_id` |
| `apps/prototype-description-service/recognition/config/settings.py` | Backend configuration; may need snapshot version retrieval for projection-ready response |
| `docs/epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md` | Parent epic with full Phase 1 requirements and exit criteria |

---

# Consolidated Checklist

## Completed (Pre-existing Infrastructure)

- [x] Backend auto-chains scan -> clustering via worker handler.
- [x] `_resolve_pipeline_job()` transparently presents follow-up clustering under scan job ID.
- [x] SSE stream emits phase transitions (analyze -> clustering) to frontend.
- [x] Frontend `useJobStateMachineEffects` detects `backendHandledClustering` and avoids duplicate clustering.
- [x] Snapshot projector atomically merges backend output into local tables.
- [x] Sync pull job fetches and projects snapshots with cooldown and bypass-cooldown paths.
- [x] `SyncStatusIndicator` displays freshness, pending curation ops, and conflict counts.

## Phase 0: Scaffolding

- [ ] Add `AWAITING_PROJECTION = "awaiting_projection"` to backend `JobPhase` enum.
- [ ] Add `PipelinePhase` type to frontend with `'projecting'` state.
- [ ] Add `acknowledgeProjection()` function stub in `scanApi.ts`.
- [ ] Add `acknowledge_projection()` method stub in snapshot client transport (PHP).
- [ ] Add `record_projection_acknowledgement()` / `get_projection_acknowledgement()` stubs in `job_repository.py`.
- [ ] Add projection acknowledgement storage (column or table) in backend DB model.
- [ ] Create test files with `@pytest.mark.skip("scaffold")` / `it.todo()` stubs for backend acknowledge endpoint, plugin acknowledge call, and frontend projecting phase.
- [ ] Verify scaffolds compile: `mypy .` / `npm run typecheck`.

## Phase 1: Backend Projection-Ready Signaling

- [ ] Extend `_job_to_pipeline_response()` to return `status: "projection_ready"` and `phase: "awaiting_projection"` when clustering is complete but no acknowledgement exists.
- [ ] Add `POST /jobs/{job_id}/acknowledge-projection` endpoint with tenant auth, idempotency, and `snapshot_version` validation.
- [ ] Implement `record_projection_acknowledgement()` in job repository with upsert semantics.
- [ ] Implement `get_projection_acknowledgement()` for pipeline status resolution.
- [ ] Ensure SSE stream emits `awaiting_projection` phase after clustering completes.
- [ ] Add backend snapshot export to include `source_job_id` in snapshot payload so the plugin can correlate projection to a specific pipeline.
- [ ] Add pytest coverage: acknowledge-projection happy path, idempotent replay, wrong tenant rejection, pipeline status transitions.

## Phase 2: Plugin Projection Acknowledgement

- [ ] Implement `acknowledge_projection(tenant_id, job_id, snapshot_version)` in snapshot client transport.
- [ ] Call `acknowledge_projection()` in `class-sync-pull-job.php::do_sync()` after successful projection when `source_job_id` is present.
- [ ] Handle acknowledgement failure gracefully: log warning but do not fail the sync pull (projection is the product-critical step; acknowledgement is coordination metadata).
- [ ] Bypass sync pull cooldown when triggered by pipeline completion (not just user-triggered).
- [ ] Add PHPUnit coverage: sync pull with acknowledgement call, acknowledgement failure isolation, cooldown bypass on pipeline trigger.

## Phase 3: Frontend Unified Pipeline Phase

- [ ] Add `derivePipelinePhase()` utility that maps SSE progress + sync status into `PipelinePhase`.
- [ ] Extend `useJobStateMachineEffects` with `projecting` phase: auto-trigger sync pull when SSE reports `awaiting_projection`.
- [ ] On sync success during `projecting` phase, call `acknowledgeProjection()` and transition to `completed`.
- [ ] On sync failure during `projecting` phase, show recoverable error with "Retry sync" action.
- [ ] Update `SyncStatusIndicator` to show "Syncing results..." during `projecting` phase instead of generic stale indicator.
- [ ] Ensure pipeline phase resets to `idle` on job removal or page navigation.
- [ ] Add Vitest coverage: phase transitions through full pipeline, sync failure recovery, acknowledgement call after successful sync.

## Phase 4: Integration and Polish

- [ ] End-to-end manual test: scan -> clustering -> projection-ready SSE -> auto sync pull -> acknowledge -> completed pipeline.
- [ ] End-to-end manual test: scan -> clustering -> projection fails -> operator sees "Retry sync" -> manual retry succeeds -> pipeline completes.
- [ ] Verify pipeline status is correct after page reload mid-pipeline (SSE reconnects and resolves current phase).
- [ ] Verify that the 30-second cooldown does not block auto-sync after pipeline clustering completes.
- [ ] All PHPUnit, pytest, and Vitest tests pass.

## Success Criteria

- [ ] Launching analysis for media items yields a single visible pipeline that advances through analyzing, clustering, projecting, and completed.
- [ ] Operators do not need to manually infer whether clustering happened on the backend but failed to reach the UI.
- [ ] If projection fails, the operator sees a clear indicator and can retry without re-running the scan.
- [ ] The backend knows whether its clustering output was successfully projected into WordPress.
