# Batch Processing Resilience & Progress Tracking (v4.10.3)

## Implementation Phases

- [x] **Phase 0: Scaffolding** (Frontend)

  - [x] Scaffold `hooks/useJobPersistence.ts`
  - [x] Scaffold `WorkbenchPage.tsx` updates

- [x] **Phase 1: Job Persistence** (Critical - Frontend Only)

  - [x] Create `hooks/useJobPersistence.ts`
  - [x] Persist active job IDs to localStorage
  - [x] Purge stale jobs (>1 hour old) on mount
  - [x] Update `WorkbenchPage.tsx` to hydrate from localStorage
  - [x] Test: reload page during scan → verify UI reconnects

- [x] **Phase 2: Real-Time Progress via SSE** (High - Full Stack)

  - [x] Backend: Add `sse-starlette` dependency
  - [x] Backend: Implement `get_scan_queue_repo` and `get_job_repo` dependencies
  - [x] Backend: Create `GET /recognition/jobs/{id}/stream` implementation
  - [x] Backend: Emit progress events on item completion (Verified via DB polling)
  - [x] Backend: Implement 500ms event batching
  - [x] Frontend: Create `useJobProgressStream.ts` implementation
  - [x] Frontend: Replace polling with SSE in `WorkbenchPage`
  - [x] Frontend: Handle offline (pause SSE, resume on reconnect)
  - [x] Frontend: Show reconnection status (`!isOnline` banner)
  - [x] Test: verify progress updates every 500ms (not 2s)

- [x] **Phase 3: Clustering Progress** (Medium - Full Stack)

  - [x] Backend: Instrument `cluster_unclustered_identities` with progress callback
  - [x] Backend: Update `ClusterService` to report clustering phase progress
  - [x] Backend: `ScanWorker` handles `clustering` job types with callback
  - [x] Frontend: Updated UI (`ConfirmPanel`) to display clustering progress bar
  - [x] Frontend: Show "Clustering X/Y identities..." label in scan status text
  - [x] Frontend: Add estimated time remaining (ETA)
  - [x] Test: run clustering → verify progress bar increments

- [x] **Phase 4: Label Integrity** (High - Backend)

  - [x] Write integration test: cancel preserves cluster labels (`test_cancel_labels.py`)
  - [x] Trace `cancel_scan_job` SQL mutations (logging added)
  - [x] Fix transaction boundaries via Identity ID Recycling (`ScanService._persist_identities`)
  - [ ] Add DB constraint preventing orphaned clusters (see note below)
  - [x] Test: scan → label → cancel → verify label unchanged

- [x] **Phase 5: Multi-Tab Coordination** (Low - Frontend Only)
  - [x] Create `hooks/useJobCoordination.ts` with BroadcastChannel
  - [x] Implement primary/secondary tab roles
  - [x] Add handoff logic when primary closes
  - [x] Show "Synced from another tab" indicator
  - [x] Test: open 2 tabs → verify single SSE connection

### Deferred: Orphaned Cluster Constraint

**Status**: Not implemented (deferred per greenfield policy)

**What it would do**: A database-level constraint (trigger or periodic cleanup) that removes `IdentityCluster` rows with zero members in `identity_members`.

**Benefits if implemented**:

- Prevents UI clutter from empty clusters with stale labels
- Ensures cluster counts are always accurate
- Simplifies queries (no need to filter `identity_count = 0`)

**Current state without constraint**:

- Orphaned clusters can exist if all member identities are deleted (e.g., media item removed from library)
- No data integrity issue—clusters are simply unused
- Identity ID Recycling (Phase 4 fix) prevents the primary cause of orphans (re-scan cascade deletion)
- Manual cleanup possible via admin action or future maintenance task

**Recommendation**: Defer until post-MVP. Add as periodic cleanup job if orphan accumulation becomes noticeable in production.

## Acceptance Criteria

- [x] Page refresh → job continues, UI reconnects within 2s
- [x] Progress updates every 500ms (smooth, not jumps)
- [x] Clustering phase visible with progress
- [x] Canceling scan → cluster labels remain intact (Identity ID Recycling)
- [x] Offline → show banner, resume when network returns
- [x] Multi-tab → single SSE connection, synced UI
- [x] Stale jobs (>1 hour) auto-purge from localStorage
