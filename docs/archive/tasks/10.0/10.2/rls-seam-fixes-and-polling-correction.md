# Fix RLS Context Gaps and Frontend Polling Stall

## Problem Statement

The clustering pipeline has four confirmed broken code paths where RLS context is missing, causing silent data loss: the centroid MV refresh always produces 0 rows, progress checkpoints are silently discarded, scheduled disposal purges nothing, and HTTP sync clustering loses context after commit. Separately, the frontend stops polling too early for `completed + awaiting_projection` jobs, leaving the UI stuck on "Projecting."

## Workflow Principles

- RLS context (`app.current_tenant`, `app.bypass_rls`) must be explicitly established on every fresh session and re-established after every commit.
- Silent 0-row results from known-ID queries are bugs, not valid outcomes. Assert rowcounts where the target is known to exist.
- Frontend polling must track composite state (`status` + `progress.phase`), not just terminal `status`.

## Terminology

- **RLS bypass**: Setting `app.bypass_rls = 'true'` on a PostgreSQL session to disable row-level security filtering. Transaction-scoped via `SET LOCAL`; cleared by `COMMIT`/`ROLLBACK`.
- **Tenant context**: Setting `app.current_tenant` to a tenant UUID so RLS policies allow access to that tenant's rows. Also transaction-scoped.
- **AUTOCOMMIT connection**: A new connection created outside any transaction; `SET LOCAL` has no effect, so `SET` (session-level) must be used instead.
- **Seam**: A code path boundary where RLS context may be missing or invalidated.

## Current State Analysis

- **Seam 1 (HIGH)**: `refresh_centroids_view_concurrent()` in `cluster_repository.py` creates an AUTOCOMMIT connection without bypass. All 18 MV source tables carry `relforcerowsecurity = true` (FORCE ROW LEVEL SECURITY), which applies even to the table owner; a session without `app.bypass_rls = 'true'` sees zero rows regardless of ownership. MV refreshes to 0 rows. Verified via direct DB query.
- **Seam 2 (HIGH)**: `progress_callback` in `clustering.py` opens a fresh session without bypass. `UPDATE identity_clustering_jobs` matches 0 rows. Progress checkpoints silently lost.
- **Seam 3 (HIGH)**: `ScheduledDisposalWorker.run_once()` in `purge_service.py` opens purge sessions without bypass. Disposal silently deletes nothing.
- **Seam 4 (MEDIUM)**: `cluster_unclustered_identities()` in `orchestrator.py` continues after `commit(True)` without re-establishing context. Post-commit suggestion backfill and MV refresh fail silently. Only the HTTP sync path is affected (worker passes `commit=False`).
- **Issue A (Frontend)**: `refetchInterval` in `useRecognitionHooks.ts` stops polling when `status === 'completed'`, missing the brief `awaiting_projection` phase.

## Proposed Solution

Fix each seam by adding the appropriate `enable_rls_bypass()` or `set_tenant_context()` call. Add rowcount assertions where UPDATE/DELETE targets known rows. Fix the frontend polling predicate. Add MV refresh observability (before/after row counts, duration logging, return success/failure signal).

## Patterns to Follow

### RLS bypass on fresh sessions

```python
async with session_factory() as fresh_session:
    await enable_rls_bypass(fresh_session)
    # ... all queries now see all tenants' data
```

### RLS bypass on AUTOCOMMIT connections

```python
async with bind.connect() as conn:
    conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
    await conn.execute(text("SET app.bypass_rls = 'true'"))
    await conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY ..."))
    await conn.execute(text("RESET app.bypass_rls"))
```

### Context restoration after commit

```python
if commit:
    await self._session.commit()
    await set_tenant_context(self._session, uuid.UUID(tenant_id))
    await enable_rls_bypass(self._session)
```

### Rowcount assertion after known-ID UPDATE

```python
result = await session.execute(
    sa_update(Model).where(Model.id == known_id).values(...)
)
assert result.rowcount >= 1, f"UPDATE {Model.__name__} id={known_id} affected 0 rows; RLS context may be missing"
```

### Frontend polling with composite state

```typescript
refetchInterval: (query) => {
  const data = query.state.data;
  if (!data) return 1500;
  const isActive = data.status === 'running' || data.status === 'pending';
  const isAwaitingProjection = data.progress?.phase === 'awaiting_projection';
  return isActive || isAwaitingProjection ? 1500 : false;
},
```

## Functions to Change

| File                                                                  | Function                                                      | Change                                                                                                                                 |
| --------------------------------------------------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `recognition/infrastructure/repositories/cluster_repository.py`       | `refresh_centroids_view_concurrent`                           | Add `SET app.bypass_rls = 'true'` on AUTOCOMMIT connection before REFRESH; add `RESET` after; log before/after row counts and duration |
| `recognition/infrastructure/repositories/cluster_repository.py`       | `refresh_centroids_view`                                      | Add `enable_rls_bypass` as defense-in-depth; log row count after refresh                                                               |
| `recognition/worker/handlers/clustering.py`                           | `progress_callback` (nested in `ClusteringJobHandler.handle`) | Add `await enable_rls_bypass(chk_session)` before UPDATE; assert `result.rowcount >= 1`                                                |
| `recognition/domain/services/purge_service.py`                        | `ScheduledDisposalWorker.run_once`                            | Add `await enable_rls_bypass(purge_session)` before constructing `TenantPurgeService`                                                  |
| `recognition/application/orchestration/clustering/orchestrator.py`    | `_finalize_job`                                               | After `self._session.commit()`, call `set_tenant_context` + `enable_rls_bypass` (only when `self._commit is True`)                     |
| `recognition/worker/scan_worker.py`                                   | `_refresh_mv_if_needed`                                       | Stamp refresh interval from completion time, not start time; log refresh result                                                        |
| `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts` | `refetchInterval` callbacks                                   | Continue polling when `progress.phase === 'awaiting_projection'` even if `status === 'completed'`                                      |

## Related Files

| File                                                                   | Note                                                                                             |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `db/tenant_context.py`                                                 | Provides `set_tenant_context()`, `enable_rls_bypass()`; not modified but called from all fixes   |
| `recognition/worker/handlers/utils.py`                                 | `ensure_job_context()` sets both tenant context and bypass; reference pattern                    |
| `recognition/interface_adapters/http/routers/clusters.py`              | HTTP sync endpoint that triggers Seam 4 via `cluster_unclustered_identities(commit=True)`        |
| `recognition/interface_adapters/http/deps/services.py`                 | `build_cluster_service()` wires the session; context set there but lost after commit             |
| `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts` | Maps `progress.phase` to UI states; confirms `awaiting_projection` is a valid transitional state |
| `db/migrations/versions/001_identity_schema.py`                        | Defines RLS policies and `TENANT_TABLES` list; not modified                                      |

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID          | Owned Paths                                                                                                                                                                                                                                                                                                                                              | Upstream Dependencies | Required Tests                                                                          |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | --------------------------------------------------------------------------------------- |
| `backend-domain` | `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`, `apps/prototype-description-service/recognition/worker/**`, `apps/prototype-description-service/recognition/domain/services/purge_service.py`, `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py` | None                  | `PYENV_VERSION=description-service pytest recognition/tests/unit/ -q`                   |
| `frontend`       | `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`                                                                                                                                                                                                                                                                                    | None (independent)    | `cd apps/prototype-wp-alt-context && npx vitest run js/admin/hooks/ --reporter=verbose` |

### Merge Order

1. `backend-domain` (all RLS seam fixes + observability)
2. `frontend` (polling fix; independent, can merge in any order)

---

# Consolidated Checklist

## Phase 0: Scaffolding

- [x] Add test files for RLS bypass verification: `recognition/tests/unit/test_rls_context_seams.py`
- [x] Add test file for polling fix: `js/admin/hooks/__tests__/useRecognitionPolling.test.ts`
- [x] Verify scaffolds compile: `mypy .` / `npm run typecheck`

## Phase 1: Critical RLS Fixes (Seams 1-3)

- [x] **Seam 1**: In `refresh_centroids_view_concurrent()`, add `SET app.bypass_rls = 'true'` before REFRESH and `RESET` after on the AUTOCOMMIT connection
- [x] **Seam 1**: Add before/after row count logging and duration measurement to `refresh_centroids_view_concurrent()`
- [x] **Seam 1**: Return success/failure boolean from `refresh_centroids_view_concurrent()` instead of swallowing all exceptions
- [x] **Seam 1 defense-in-depth**: Add `enable_rls_bypass` to non-concurrent `refresh_centroids_view()` before the REFRESH
- [x] **Seam 2**: In `progress_callback`, add `await enable_rls_bypass(chk_session)` before the UPDATE statement
- [x] **Seam 2**: Assert `result.rowcount >= 1` after the progress UPDATE to catch future RLS regressions
- [x] **Seam 3**: In `ScheduledDisposalWorker.run_once()`, add `await enable_rls_bypass(purge_session)` before constructing `TenantPurgeService`

## Phase 2: Post-Commit Context Restoration (Seam 4)

- [x] In `_finalize_job()`, after `self._session.commit()` (when `self._commit is True`), call `set_tenant_context()` + `enable_rls_bypass()` to restore context for post-commit work
- [x] Verify that `ClusterService.cluster_unclustered_identities()` post-commit suggestion backfill and MV refresh now execute with context

## Phase 3: MV Refresh Scheduling Improvement

- [x] Change `_refresh_mv_if_needed()` to stamp the refresh interval from completion time, not start time
- [x] Add health check: after refresh, compare MV row count against expected count from `identity_clusters`; log warning if they diverge

## Phase 4: Frontend Polling Fix

- [x] Change `refetchInterval` in `useRecognitionHooks.ts` to continue polling when `progress.phase === 'awaiting_projection'` even if `status === 'completed'`
- [x] Add test: first response `status=completed, phase=awaiting_projection`; second response `status=completed, phase=complete, projection_acknowledged_at!=null`; assert workbench leaves Projecting state

## Phase 5: Tests

- [x] Unit test: `refresh_centroids_view_concurrent` sets bypass before REFRESH (mock session/connection; verify `SET app.bypass_rls` is called)
- [x] Unit test: `progress_callback` calls `enable_rls_bypass` on checkpoint session
- [x] Unit test: `ScheduledDisposalWorker.run_once` calls `enable_rls_bypass` on purge sessions
- [x] Unit test: `_finalize_job` re-establishes tenant context after commit when `commit=True`
- [x] Unit test: `_finalize_job` does not call `set_tenant_context` when `commit=False`
- [x] Vitest: polling continues during `awaiting_projection` phase
- [x] Vitest: polling stops after `phase=complete`

## Stretch Goals

- [x] Move MV refresh to a dedicated maintenance path (`POST /clusters/maintenance/refresh-centroids` endpoint in `clusters.py`)
- [x] Add automated MV health check endpoint (`GET /clusters/centroid-health` in `clusters.py`)
- [x] Add `set_tenant_context` to error recovery path in `scan_worker.py` (Seam 5; defense-in-depth)
- [x] Add docstring/assertion to `post_merge_retry_matching()` documenting implicit session contract (Seam 6)

## Success Criteria

- [x] `refresh_centroids_view_concurrent()` populates MV with correct row count (verified by health check log)
- [x] Progress checkpoints persist during clustering (assert rowcount > 0)
- [x] Scheduled disposal actually deletes data for acknowledged tenants
- [x] HTTP sync clustering generates merge suggestions after commit
- [x] Frontend leaves "Projecting" state within one poll cycle after backend acknowledges projection
- [x] All existing tests continue to pass (658 Python, 407 TypeScript)
