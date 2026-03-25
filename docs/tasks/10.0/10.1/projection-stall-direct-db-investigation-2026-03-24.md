# Projection Stall Investigation via Direct DB Query

Date: 2026-03-24

## Scope

This report re-investigates the batch that appeared in the UI as:

- Job `bb1cad30-88be-4d0e-ab3b-be220b792979`
- Status text: `Syncing projected results...`
- Phase: `Projecting`
- Progress: `937/937 images`

Unlike the first pass, this investigation uses direct PostgreSQL queries through:

- `apps/prototype-description-service/scripts/db_shell.sh`

## Executive Summary

Direct database inspection shows the batch was not actually stuck on the backend.

The key timeline is:

1. Scan job `bb1cad30-88be-4d0e-ab3b-be220b792979` completed at `2026-03-24 18:47:24.344189 -04`.
2. Follow-up clustering job `c2e831f4-c24e-4b1a-b70e-c0fee716bc0d` completed at `2026-03-24 18:47:37.879067 -04`.
3. Projection acknowledgement was already persisted at `2026-03-24 18:47:39.664973 -04`.

That means the backend finished the full scan -> cluster -> project/acknowledge flow in about 15 seconds after the scan completed. The UI's continued `Projecting` state was stale.

At the same time, direct DB inspection also uncovered a separate backend health issue:

- the tenant has `480` clusters and `937` members,
- the materialized-view definition computes `480` centroid rows,
- but `mv_identity_cluster_centroids` currently contains `0` rows for that tenant.

So the accurate conclusion is:

- The observed "stuck in Projecting" state was not caused by the backend being blocked on projection acknowledgement.
- The most likely immediate cause of the stale UI is frontend polling that stops too early for `completed + awaiting_projection` jobs.
- Separately, the centroid MV maintenance path is unhealthy and likely responsible for the repeated refresh-loop log spam, but it did not block this batch's acknowledgement.

## Direct DB Evidence

### 1. Scan job finished normally

Query:

```sql
SELECT id, tenant_id, status, processed_media, total_media, identities_detected,
       created_at, started_at, completed_at, error_message
FROM identity_scan_jobs
WHERE id = 'bb1cad30-88be-4d0e-ab3b-be220b792979';
```

Result:

- `status = completed`
- `processed_media = 500`
- `total_media = 500`
- `identities_detected = 937`
- `completed_at = 2026-03-24 18:47:24.344189 -04`

### 2. Follow-up clustering job also finished normally

Query:

```sql
SELECT id, source_job_id, tenant_id, job_type, status,
       processed_identities, total_identities, progress,
       snapshot_version, projection_acknowledged_at,
       created_at, started_at, completed_at,
       payload->>'scan_job_id' AS scan_job_id
FROM identity_clustering_jobs
WHERE payload->>'scan_job_id' = 'bb1cad30-88be-4d0e-ab3b-be220b792979';
```

Result:

- clustering job id: `c2e831f4-c24e-4b1a-b70e-c0fee716bc0d`
- `status = completed`
- `processed_identities = 937`
- `total_identities = 937`
- `progress = 1`
- `completed_at = 2026-03-24 18:47:37.879067 -04`

### 3. Projection acknowledgement had already happened

Same clustering-row query showed:

- `projection_acknowledged_at = 2026-03-24 18:47:39.664973 -04`

That is the decisive fact. The backend had already moved past `awaiting_projection` roughly 2 seconds after clustering completed.

### 4. There was no active live refresh at investigation time

Query against `pg_stat_activity` showed only the investigation `psql` sessions active. There was no running `REFRESH MATERIALIZED VIEW` command at the time of inspection.

This means the worker was not actively stuck in a live refresh at `19:11 -04`, even though the log had shown repeated refresh starts up through `19:10 -04`.

## Log Evidence

The worker log still matters because it shows a real maintenance problem after clustering finished:

- `18:47:37`: clustering `batch_complete`
- `18:48:09` through `19:10:23`: repeated `[worker] Refreshing centroids MV (elapsed=60.xs)`

Source:

- `apps/prototype-description-service/logs/scan_worker.log`

However, because the database already shows `projection_acknowledged_at` at `18:47:39`, this repeated MV refresh cannot be the cause of the user-visible projection wait for this specific batch. It is a separate backend issue.

## Root Cause of the User-Visible "Projecting" Stall

The strongest root cause for the stale workbench state is frontend polling behavior.

### Why

The workbench derives `projecting` from backend `progress.phase === 'awaiting_projection'`:

- `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`

But the polling hook stops refetching as soon as job `status` becomes `completed` or `failed`:

```ts
refetchInterval: (query) =>
  query.state.data?.status === "running" ||
  query.state.data?.status === "pending"
    ? 1500
    : false;
```

Source:

- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`

That is the bug. A job can be:

- `status = completed`
- `progress.phase = awaiting_projection`

for a short window. In that state the query stops polling, so the UI may never observe the subsequent transition to:

- `progress.phase = complete`
- `projection_acknowledged_at != null`

This matches the live data exactly:

1. backend reached completed clustering,
2. backend briefly entered `awaiting_projection`,
3. frontend likely cached that terminal-status response,
4. polling stopped,
5. acknowledgement landed seconds later in the database,
6. UI kept showing `Projecting`.

## Separate Backend Finding: MV Refresh Path Is Broken Due to RLS

The centroid materialized view is empty because `REFRESH MATERIALIZED VIEW` runs without RLS bypass, and all three source tables enforce row-level security even for the table owner.

### Root Cause: RLS Blocks MV Refresh

All three source tables have `relforcerowsecurity = true`:

```sql
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class
WHERE relname IN ('identity_members', 'media_identities', 'identity_clusters');
```

Result:

| relname           | relrowsecurity | relforcerowsecurity |
| ----------------- | -------------- | ------------------- |
| media_identities  | t              | t                   |
| identity_clusters | t              | t                   |
| identity_members  | t              | t                   |

The RLS policy on each table requires either `app.current_tenant` to match the row's `tenant_id`, or `app.bypass_rls` to be `'true'`:

```sql
(tenant_id = (NULLIF(current_setting('app.current_tenant', true), ''))::uuid)
OR (COALESCE(NULLIF(current_setting('app.bypass_rls', true), ''), 'false'))::boolean
```

The MV is owned by `context_alt_text` (the application user, not a superuser). `relforcerowsecurity = true` means RLS applies even to the table owner.

The `refresh_centroids_view_concurrent()` method in `cluster_repository.py` creates a **new AUTOCOMMIT connection** for the refresh:

```python
bind = self._session.bind
async with bind.connect() as conn:
    conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
    await conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY ..."))
```

This new connection has neither `app.current_tenant` nor `app.bypass_rls` set. Both RLS policy branches evaluate to false, so every row is filtered out.

### Verification: Refresh Without Bypass Produces 0 Rows

```sql
-- Without bypass (simulates what the worker does)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids;
SELECT COUNT(*) FROM mv_identity_cluster_centroids;
-- Result: 0
```

### Verification: Refresh With Bypass Produces 480 Rows

```sql
SET app.bypass_rls = 'true';
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids;
SELECT COUNT(*) FROM mv_identity_cluster_centroids;
-- Result: 480
RESET app.bypass_rls;
```

This is the definitive proof. The MV has been empty since its creation because every refresh attempt ran without RLS bypass.

### Why the Non-Concurrent Path Is Not Affected

The non-concurrent `refresh_centroids_view()` runs on the current session. When called from the clustering pipeline, `ensure_job_context()` (in `recognition/worker/handlers/utils.py`) calls `enable_rls_bypass(session)` which sets `app.bypass_rls = 'true'` on the session. So the inline refresh after clustering would succeed.

However, the **scheduled background refresh** in `scan_worker.py` calls `refresh_centroids_view_concurrent()`, which creates a fresh connection. This is the path that runs every ~60 seconds in the worker log and always produces 0 rows.

### Direct DB Evidence

Query 1:

```sql
SELECT COUNT(*) AS clusters, COALESCE(SUM(identity_count),0) AS summed_identity_count
FROM identity_clusters
WHERE tenant_id = 'cc42f496-c7e1-5631-b3b5-cfa270c763f8';
```

Result:

- `clusters = 480`
- `summed_identity_count = 937`

Query 2:

```sql
SELECT COUNT(*) AS members
FROM identity_members im
JOIN identity_clusters ic ON ic.id = im.cluster_id
WHERE ic.tenant_id = 'cc42f496-c7e1-5631-b3b5-cfa270c763f8';
```

Result:

- `members = 937`

Query 3:

```sql
SELECT COUNT(*) AS mv_rows_for_tenant
FROM mv_identity_cluster_centroids
WHERE tenant_id = 'cc42f496-c7e1-5631-b3b5-cfa270c763f8';
```

Result (before fix):

- `mv_rows_for_tenant = 0`

Query 4: Execute the MV definition logic directly (with admin/bypass RLS):

Result:

- `computed_rows = 480`
- `rows_with_centroid = 480`

That means:

- base data is present,
- the view definition produces correct centroid rows when RLS is bypassed,
- but the materialized view was always empty because every concurrent refresh ran without bypass.

## ADDITION: Full RLS Seam Audit of the Clustering Pipeline

_Added 2026-03-24. The MV refresh RLS failure prompted a systematic audit of every code path in the clustering pipeline where RLS context might be missing._

### Background: How RLS Context Works

All tables in `TENANT_TABLES` (defined in `db/migrations/versions/001_identity_schema.py`) have `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`. The policy requires one of:

- `app.current_tenant` matches the row's `tenant_id` (tenant-scoped access), OR
- `app.bypass_rls = 'true'` (global access for maintenance operations)

Both are set with `SET LOCAL`, meaning they are **transaction-scoped**. A `COMMIT` or `ROLLBACK` clears them. A new connection starts with neither set.

RLS-protected tables (all have `relforcerowsecurity = true`):

`media_identities`, `identity_clusters`, `identity_members`, `identity_scan_jobs`, `identity_scan_job_items`, `identity_cluster_representatives`, `identity_clustering_jobs`, `identity_suggestions`, `cluster_merge_suggestions`, `name_suggestions`, `identity_cluster_blocks`, `identity_constraints`, `recognition_runs`, `recognition_events`, `clustering_feedback`, `audit_events`, `curation_replay_records`, `export_jobs`

### Seam 1 (HIGH): `refresh_centroids_view_concurrent()` -- ALREADY DOCUMENTED ABOVE

File: `recognition/infrastructure/repositories/cluster_repository.py`, function `refresh_centroids_view_concurrent()`

New AUTOCOMMIT connection with no `app.bypass_rls`. All MV source table rows filtered. MV refreshes to 0 rows silently.

Callers:

- `scan_worker.py::_refresh_mv_if_needed()` -- scheduled background refresh every ~60s
- `purge_service.py::_purge_rows()` -- after tenant data purge
- `cluster_service.py::cluster_unclustered_identities()` -- after merge suggestion generation (when `commit=True`)

### Seam 2 (HIGH): Progress callback session in `ClusteringJobHandler.handle()`

File: `recognition/worker/handlers/clustering.py`, lines 87-113

```python
async def progress_callback(completed: int, total: int):
    ...
    try:
        async with session_factory() as chk_session:   # <-- fresh session, no context
            await chk_session.execute(
                sa_update(IdentityClusteringJob)
                .where(IdentityClusteringJob.id == job_id)
                .values(
                    processed_identities=completed,
                    total_identities=total,
                    progress=compute_progress(completed, total),
                )
            )
            await chk_session.commit()
```

`identity_clustering_jobs` is RLS-protected. The fresh `chk_session` has no `app.current_tenant` or `app.bypass_rls`. The `UPDATE ... WHERE id = job_id` will match 0 rows because RLS filters the job row from visibility. The update silently does nothing; progress checkpoints are lost.

**Impact:** Progress updates are silently discarded during clustering. If the worker crashes mid-clustering, the progress checkpoint is not durable, so the job resumes from 0. The clustering result is still correct because the main session (which has context) handles the final status update.

**Fix:** Add `await enable_rls_bypass(chk_session)` before the UPDATE.

### Seam 3 (HIGH): `ScheduledDisposalWorker.run_once()` -- purge session has no context

File: `recognition/domain/services/purge_service.py`, lines 396-410

```python
async def run_once(self) -> dict[str, object]:
    async with self._session_factory() as session:
        result = await session.execute(select(Tenant.id)...)  # <-- tenants table; no RLS
        tenant_ids = list(result.scalars().all())

    for tenant_id in tenant_ids:
        async with self._session_factory() as purge_session:  # <-- fresh session, no context
            purge_service = TenantPurgeService(purge_session)
            purge_result = await purge_service.purge_tenant_data(
                tenant_id=str(tenant_id), ...)
```

`purge_session` has neither `app.current_tenant` nor `app.bypass_rls`. The `TenantPurgeService.purge_tenant_data()` method queries and deletes from RLS-protected tables (`media_identities`, `identity_clusters`, `identity_members`, etc.). All queries return 0 rows silently, so the scheduled disposal silently purges nothing.

Additionally, `_purge_rows()` calls `refresh_centroids_view_concurrent()` at the end (Seam 1), compounding the issue.

**Impact:** Scheduled automatic disposal of acknowledged data is completely non-functional. Data that should be purged after acknowledgement is never actually deleted.

**Fix:** Add `await enable_rls_bypass(purge_session)` (or `set_tenant_context(purge_session, tenant_id)`) before constructing `TenantPurgeService`.

### Seam 4 (MEDIUM): Post-commit context loss in `ClusterService.cluster_unclustered_identities()`

File: `recognition/application/orchestration/cluster_service.py`, lines 157-212

When called with `commit=True` (the default; used by HTTP sync endpoints), the orchestrator commits inside `_finalize_job()`, which clears `SET LOCAL` variables. The method then continues to:

1. `suggestion_refresh_service.backfill_for_new_unlabeled_clusters()` -- queries RLS-protected tables
2. `session.commit()` -- clears any remaining context
3. `assignment_writer.refresh_centroids_view()` -- the non-concurrent path on the same session
4. `merge_suggestion_service.generate_for_tenant()` -- queries `identity_clusters`, `identity_members`, `cluster_merge_suggestions`

All of these run after the commit, so the session has no `app.current_tenant` and no `app.bypass_rls`. Suggestion backfill and merge suggestion generation silently produce 0 results.

**Mitigating factor:** The worker handler calls this with `commit=False` (line 130 of `clustering.py`), so the worker path avoids this seam. Only the HTTP sync clustering endpoint (`POST /clusters/cluster` with `mode=sync`) is affected.

**Impact:** No merge suggestions generated after HTTP-triggered sync clustering. Suggestion backfill silently fails. Non-concurrent MV refresh also silently produces 0 rows on this path.

**Fix:** Re-establish `set_tenant_context()` after each commit in `cluster_unclustered_identities()`, or restructure so post-commit work runs in a new transaction with context set.

### Seam 5 (LOW): Error recovery session missing `set_tenant_context()`

File: `recognition/worker/scan_worker.py`, lines 244-280

```python
async with self._session_factory() as fresh_session:
    await enable_rls_bypass(fresh_session)    # <-- bypass set, but no tenant context
    failed_stmt = (
        select(IdentityClusteringJob)
        .where(IdentityClusteringJob.id == job_id)
        .with_for_update(skip_locked=True)
    )
```

The error recovery path sets `enable_rls_bypass` (which is sufficient to bypass all RLS policies), but does not set `app.current_tenant`. This works today because the bypass OR branch is enough. However, if any future audit or logging code assumes `app.current_tenant` is set in the session, it will see an empty string.

**Impact:** No current data loss. Defense-in-depth gap only.

**Fix:** Add `await set_tenant_context(fresh_session, job.tenant_id)` before bypass.

### Seam 6 (LOW): `post_merge_retry_matching()` implicit session contract

File: `recognition/application/orchestration/cluster_merge.py`, lines 34-65

This function accepts a pre-configured `session` and does not call `set_tenant_context()` or `enable_rls_bypass()` itself. It relies entirely on the caller having set up the session. Currently all callers (`ClusterService.merge_clusters()`, `ClusterService.retry_matching()`) use the service-level session which has context from `build_cluster_service()`.

**Impact:** No current data loss. But the function is fragile; a new caller that passes an unconfigured session would get silent empty results.

**Fix:** Document the requirement as a function-level assertion, or add a defensive `assert` that verifies RLS context is set.

### Summary of RLS Seam Audit

| #   | Severity | File                  | Function                              | Issue                          | Currently Broken?                                     |
| --- | -------- | --------------------- | ------------------------------------- | ------------------------------ | ----------------------------------------------------- |
| 1   | HIGH     | cluster_repository.py | `refresh_centroids_view_concurrent()` | New AUTOCOMMIT conn, no bypass | Yes; MV always 0 rows                                 |
| 2   | HIGH     | clustering.py         | progress_callback                     | Fresh session, no context      | Yes; progress checkpoints silently lost               |
| 3   | HIGH     | purge_service.py      | `ScheduledDisposalWorker.run_once()`  | Purge session lacks context    | Yes; disposal silently purges nothing                 |
| 4   | MEDIUM   | cluster_service.py    | `cluster_unclustered_identities()`    | Post-commit context loss       | Yes (HTTP sync path only); suggestions silently empty |
| 5   | LOW      | scan_worker.py        | error recovery path                   | Missing `set_tenant_context`   | No; bypass is sufficient                              |
| 6   | LOW      | cluster_merge.py      | `post_merge_retry_matching()`         | Implicit session contract      | No; all current callers set context                   |

## Why This Matches the Literature

### 1. Queueing and head-of-line blocking

Kleppmann notes that response time includes queueing delays, and a small number of slow operations can hold up subsequent work via head-of-line blocking. See:

- `docs/literature/extracted/Designing Data-Intensive Applications - The Big Ideas Behind -- Martin Kleppmann -- 6 [early release], 2017 -- O'Reilly Media, Incorporated -- 9781449373320 -- bf7c3fecfe5dcffceb170b2aa6d34c31 -- Anna’s Archive.txt` around `1248-1260`
- the same file around `1332-1355`

This fits the repeated worker-side MV refresh attempts: a heavyweight maintenance task sits on the same serialized worker control path and creates avoidable control-plane delay.

### 2. Background maintenance can interfere with foreground work

Kleppmann also describes how background compaction/maintenance competes for finite shared resources and can hurt high-percentile latency even if average throughput looks acceptable. See:

- the same DDIA extract around `4037-4063`

That maps well to the repeated `REFRESH MATERIALIZED VIEW CONCURRENTLY` attempts seen in the worker log.

### 3. Latency compounds through dependent stages

Enberg emphasizes that latency is the delay between cause and observed effect, and that end-to-end latency compounds across dependent steps. See:

- `docs/literature/extracted/Latency- Reduce delay in software systems -- Pekka Enberg -- 1, 2025 nov 25 -- Manning Publications Co_ LLC -- 9781633438088 -- 1e5b0046b5f8e592148d71d26be0de76 -- Anna’s Archive.txt` around `548-569`

The UI pipeline here depends on:

- backend status fetch
- projection sync
- acknowledgement persistence
- frontend refetch

If the frontend stops polling one step too early, the user still experiences a stall even though the backend completed.

### 4. Incremental maintenance is preferable to repeated global recomputation

Enberg's discussion of incremental computation argues for maintaining derived state as updates happen so users do not pay the cost later. See:

- the same Latency extract around `4781-4827`

The empty MV plus repeated refresh starts suggests the current derived-state maintenance is both expensive and unreliable.

## Root Cause Summary

There are two different issues:

### Issue A: User-visible stale "Projecting" state

Root cause:

- frontend polling stops based on `status`,
- but the user-visible pipeline state depends on `progress.phase`,
- and `completed + awaiting_projection` is a legitimate transitional state.

This is the likely explanation for what the user saw.

### Issue B: Backend centroid MV always empty due to RLS during refresh

Root cause:

- `refresh_centroids_view_concurrent()` creates a new AUTOCOMMIT connection without `app.bypass_rls`,
- all three source tables have `relforcerowsecurity = true`,
- so the RLS policies filter out every row during `REFRESH MATERIALIZED VIEW CONCURRENTLY`,
- the refresh completes without error but produces 0 rows.

This was confirmed by running the refresh with and without `app.bypass_rls = 'true'`; only the bypass variant populates the MV to 480 rows.

The worker's repeated 60s refresh-loop log spam is this broken refresh running over and over, each time successfully producing 0 rows.

The non-concurrent `refresh_centroids_view()` called inline during clustering is not affected because `ensure_job_context()` sets `app.bypass_rls = 'true'` on the same session.

### ADDITION: Issue C: Systemic RLS context gaps across the clustering pipeline

The MV refresh bug is not an isolated case. The full seam audit (see section above) found that the same class of RLS failure; a fresh session or post-commit continuation without context; affects three additional code paths that are **currently broken in production**:

- **Progress checkpoints** (Seam 2): `ClusteringJobHandler` progress callback opens a fresh session without bypass. Progress UPDATEs silently affect 0 rows.
- **Scheduled disposal** (Seam 3): `ScheduledDisposalWorker.run_once()` opens purge sessions without context. Automatic data disposal silently deletes nothing.
- **HTTP sync post-clustering** (Seam 4): After `commit(True)` clears `SET LOCAL` vars, suggestion backfill and MV refresh run without context. Merge suggestions silently not generated.

The common pattern is: any code path that creates a new session via `session_factory()`, or continues after a `commit()`, without explicitly calling `set_tenant_context()` or `enable_rls_bypass()`, will silently produce empty results against RLS-protected tables.

## Proposed Fix

### Fix the stale UI first

1. Keep polling while `progress.phase === 'awaiting_projection'`, even if `status === 'completed'`.

Concretely, change the query refetch policy in:

- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`

so polling continues for:

- `status in ('running', 'pending')`
- or `progress.phase === 'awaiting_projection'`

2. Add a focused test that reproduces:

- first response: `status=completed`, `phase=awaiting_projection`
- second response: `status=completed`, `phase=complete`, `projection_acknowledged_at!=null`

and asserts the workbench leaves `Projecting`.

### Fix observability of the MV path

3. Add refresh completion logging.

For every refresh attempt, log:

- start time
- finish time
- duration
- success/failure
- resulting MV row count, or at least tenant/global row count delta

Without this, operators can only see the start of the maintenance loop.

4. Surface refresh failures to the caller.

`refresh_centroids_view_concurrent()` currently swallows errors with a warning log. The worker cannot tell whether refresh succeeded. Return a success/failure signal so the scheduler can react appropriately.

### Fix the RLS bypass for MV refresh (CRITICAL)

5. In `refresh_centroids_view_concurrent()`, set `app.bypass_rls = 'true'` on the AUTOCOMMIT connection before the REFRESH command.

Concretely, in `cluster_repository.py`:

```python
async def refresh_centroids_view_concurrent(self) -> None:
    try:
        if is_sqlite(self._session):
            await self.refresh_centroids_view()
            return

        bind = self._session.bind
        if isinstance(bind, AsyncConnection):
            conn = await bind.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("SET app.bypass_rls = 'true'"))
            await conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids"))
            await conn.execute(text("RESET app.bypass_rls"))
            return

        async with bind.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text("SET app.bypass_rls = 'true'"))
            await conn.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids"))
            await conn.execute(text("RESET app.bypass_rls"))
    except Exception:
        logger.warning("Failed to refresh centroid materialized view concurrently", exc_info=True)
```

This is the one-line fix that makes the MV actually populate. Verified against the live DB: refresh with bypass produces 480 rows; without produces 0.

6. Also add `app.bypass_rls` to the non-concurrent `refresh_centroids_view()` as defense-in-depth, in case it is ever called outside a session that already has bypass set.

### ADDITION: Fix RLS context on progress checkpoint session (Seam 2)

7. In `ClusteringJobHandler.handle()` progress callback, add `await enable_rls_bypass(chk_session)` before the UPDATE:

```python
async with session_factory() as chk_session:
    await enable_rls_bypass(chk_session)
    await chk_session.execute(
        sa_update(IdentityClusteringJob)
        .where(IdentityClusteringJob.id == job_id)
        .values(...)
    )
    await chk_session.commit()
```

### ADDITION: Fix RLS context on scheduled disposal sessions (Seam 3)

8. In `ScheduledDisposalWorker.run_once()`, add `await enable_rls_bypass(purge_session)` before constructing `TenantPurgeService`:

```python
for tenant_id in tenant_ids:
    async with self._session_factory() as purge_session:
        await enable_rls_bypass(purge_session)
        purge_service = TenantPurgeService(purge_session)
        ...
```

Since disposal is a cross-tenant maintenance operation, `enable_rls_bypass` is the correct choice (not `set_tenant_context`). The purge service already scopes its deletes by `tenant_id` in WHERE clauses.

### ADDITION: Fix post-commit context loss in HTTP sync clustering (Seam 4)

9. In `ClusterService.cluster_unclustered_identities()`, re-establish tenant context after each `session.commit()` call:

```python
if commit:
    await self.session.commit()
    await set_tenant_context(self.session, uuid.UUID(tenant_id))
```

This is needed at both commit sites: after suggestion backfill (line ~190) and implicitly via the orchestrator's `_finalize_job` commit. The non-concurrent `refresh_centroids_view()` and `generate_for_tenant()` that follow need the context restored.

### Fix refresh scheduling and isolation

10. Stamp the refresh interval from completion time, not start time.

This avoids the "refresh takes ~60s, so the next loop is immediately eligible to refresh again" feedback loop.

11. Move MV refresh off the worker's critical control path.

Run it in:

- a dedicated maintenance worker,
- or a coalesced low-priority scheduler,
- or only after explicit dirty-state detection.

This follows the literature's guidance to isolate background maintenance from latency-sensitive paths.

### Fix derived-state correctness

12. Add an automated health check comparing:

- expected centroid rows from the underlying cluster/member join
- actual rows in `mv_identity_cluster_centroids`

If they diverge, alert and suppress repeated blind refresh retries until inspected.

## ADDITION: Structural Refactoring Findings (Code Smell Audit)

_Added 2026-03-24. With the RLS seam audit complete, a broader structural review of the clustering pipeline identified code smells and design weaknesses that made this class of silent failure harder to detect, debug, and reason about. Findings are grounded in Fowler's refactoring catalog (Refactoring, 2nd ed.) and Refactoring UI principles._

### Why This Section Exists

The RLS investigation revealed a systemic pattern: fresh sessions and post-commit continuations silently produce empty results, and no layer in the pipeline raises an alarm. That symptom points to deeper structural issues. The code smells documented here are the conditions that allowed four HIGH/MEDIUM bugs to ship undetected.

### RF-1: Silent Failures as the Default Contract (Primitive Obsession + Missing Assertions)

**Fowler smell:** Primitive Obsession (returning raw empty lists where a Result/Error type would force callers to handle failure), Introduce Assertion (missing invariant checks).

**Where it matters most:**

| File                    | Function                                    | Silent behavior                                                                                                     |
| ----------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `cluster_repository.py` | `coerce_uuid()`                             | Returns `None` on invalid UUID; callers get empty query results silently                                            |
| `cluster_merge.py`      | `post_merge_retry_matching()` lines 88, 176 | Identity with `None` embedding skipped with `continue`; no log                                                      |
| `purge_service.py`      | predicate builders (lines 218-260)          | Return `None` to mean "delete nothing"; consuming code doesn't distinguish "nothing to delete" from "filter failed" |
| `orchestrator.py`       | `_coerce_tenant()`                          | Returns `None`; caller returns default-zero result with no audit trail                                              |

**Why it blocked detection:** Every RLS-related failure manifests as "0 rows returned" or "0 rows affected." Because the codebase treats empty results as a valid outcome everywhere, there is no tripwire to distinguish "legitimately empty" from "RLS filtered everything."

**Actionable fix:** Add assertion guards at domain boundaries. Specifically:

- After any `UPDATE ... WHERE id = <known_id>`, assert `rowcount >= 1` (the progress callback in Seam 2 would have been caught immediately).
- After `DELETE` in purge paths, log `deleted_count` per model and alert if all models return 0 for a tenant that was queried as having data.
- Replace `coerce_uuid(...) -> None` with a `Result[UUID, InvalidIdError]` return or raise explicitly at the boundary.

### RF-2: Transaction Lifecycle Not Encoded in Types (Temporary Field)

**Fowler smell:** Temporary Field; the `SET LOCAL` context variables (`app.current_tenant`, `app.bypass_rls`) exist only within a transaction and become invisible after commit.

**Current state:** `SET LOCAL` variables are set imperatively and cleared implicitly by PostgreSQL on `COMMIT`/`ROLLBACK`. No type or wrapper makes this lifecycle visible to the programmer. The orchestrator has a manual "restore after chunk commit" block (orchestrator.py lines 640-645) that was itself a previous bug fix. The HTTP sync path (Seam 4) has no such restoration.

**Why it blocked detection:** A developer reading `cluster_service.py` sees `self.session` used throughout and has no visual signal that the session's RLS context was invalidated by a mid-function commit. The session object itself does not change; only its invisible server-side state does.

**Actionable fix (Extract Class, Fowler p. 182):** Create a `TenantSession` wrapper that:

1. Wraps `AsyncSession` and tracks whether tenant context is currently valid.
2. Invalidates its tracked state on `commit()` and `rollback()`.
3. Provides `ensure_context()` that re-establishes context if invalidated.
4. Raises `ContextLostError` if any query is attempted on an invalidated session without explicit re-establishment.

This makes the invisible lifecycle visible. The chunk-commit restoration in `orchestrator.py` and the missing restoration in `cluster_service.py` would both be handled uniformly.

### RF-3: ClusterService Constructor Takes 16 Parameters (Long Parameter List + Data Clumps)

**Fowler smell:** Long Parameter List (p. 74), Data Clumps (p. 78), Introduce Parameter Object (p. 140).

`ClusterService.__init__()` accepts 16 parameters (gate, 3 discovery services, assignment_writer, 3 suggestion services, 2 repositories, settings, logger, visualizer, decision_store, observability_repo, session). This violates sr-008.

**Why it matters for debugging:** When constructing `ClusterService` in `build_cluster_service()` (services.py, 69 lines), it is easy to pass the wrong service or omit one. The long signature makes it hard to verify that all dependencies are wired correctly, and nearly impossible to write a focused unit test without mocking 10+ collaborators.

**Actionable fix (Introduce Parameter Object):** Group into 3 cohesive objects:

- `DiscoveryServices(representative, centroid, graph)`
- `SuggestionServices(suggestion, refresh, merge)`
- `ObservabilityServices(logger, visualizer, decision_store, observability_repo)`

This reduces the constructor to `(gate, discovery, suggestions, assignment_writer, observability, session, block_repo?, constraint_repo?)`.

### RF-4: cluster_repository.py is a 1,374-line God Class (Large Class + Extract Class)

**Fowler smell:** Large Class (p. 82), Extract Class (p. 182).

`ClusterRepository` has 50+ methods spanning cluster CRUD, representative management, snapshot generation, MV refresh, member queries, and domain conversion. The `_to_domain()` converter alone is a complex function that handles ORM-to-domain mapping, pose bucket computation, and debug metrics assembly.

**Why it matters for debugging:** When investigating the MV refresh RLS failure, the relevant method (`refresh_centroids_view_concurrent`) sits in a 1,374-line file alongside unrelated cluster CRUD. Searching for all "session-creating" methods requires scanning the entire file. The file's size discourages thorough review.

**Actionable fix (Extract Class):** Split along natural seams:

- `ClusterRepository` (core CRUD: create, read, update, delete clusters and members)
- `ClusterRepresentativeRepository` (representative selection, confirmation, cleanup)
- `ClusterSnapshotRepository` (snapshot generation, versioning)
- `CentroidViewRepository` (MV refresh, health checks); this isolates the RLS-sensitive path

### RF-5: Duplicated Identity Evaluation Logic (Duplicated Code)

**Fowler smell:** Duplicated Code (p. 72), Extract Function (p. 106).

`cluster_merge.py::post_merge_retry_matching()` contains two blocks (lines 67-92 and 149-182) that both: fetch an identity model, convert to domain, compute embedding similarity against cluster representatives, and evaluate against the gate. The pattern is identical; only the source of identity IDs differs (pending suggestions vs. unclustered identities).

**Why it matters:** A bug fix in one path (e.g., adding an RLS context check) must be duplicated in the other. The RLS audit found both paths are equally fragile; they share the same implicit session contract.

**Actionable fix (Extract Function):**

```python
async def _evaluate_identity_against_cluster(
    identity_model: MediaIdentityModel,
    cluster_id: str,
    representatives: list[DomainMember],
    gate: AssignmentGate,
) -> EvaluationResult | None:
    ...
```

### RF-6: Hardcoded Magic Values Across the Pipeline (Replace Magic Literal with Symbolic Constant)

**Fowler smell:** not named explicitly, but addressed in "Limit your choices" (Refactoring UI, p. 28) and general constant extraction.

| File                    | Value                                          | Meaning                            |
| ----------------------- | ---------------------------------------------- | ---------------------------------- |
| `scan_worker.py`        | `poll_interval_seconds=1.0`                    | Worker polling frequency           |
| `scan_worker.py`        | `stale_after_seconds=600`                      | Job staleness threshold            |
| `scan_worker.py`        | `mv_refresh_interval_seconds=60`               | MV refresh interval                |
| `orchestrator.py`       | `total_identities <= 100`                      | Verbose decision logging threshold |
| `cluster_merge.py`      | `max_unclustered: int = 200`                   | Unclustered retry limit            |
| `cluster_merge.py`      | `min_similarity_for_unclustered: float = 0.95` | Similarity threshold               |
| `cluster_repository.py` | `_TOP_UNLABELED_FALLBACK_REP_LIMIT = 4`        | Fallback representative count      |
| `purge_service.py`      | `DEFAULT_PURGE_BATCH_SIZE = 1000`              | Purge batch size                   |

**Why it matters for debugging:** When investigating the 60-second MV refresh loop, the interval is buried in a dataclass default. When tuning similarity thresholds, the value is a function parameter default. There is no single place to see all operational tuning knobs.

**Actionable fix:** Consolidate into a `ClusteringPipelineSettings` config object (or extend the existing `HACSettings`) that loads from environment variables with documented defaults. This also enables per-environment tuning without code changes.

### RF-7: Repeated try/except Recovery Pattern in tenant_context.py (Duplicated Code)

**Fowler smell:** Duplicated Code (p. 72), Extract Function (p. 106).

`set_tenant_context()`, `enable_rls_bypass()`, and `disable_rls_bypass()` each contain an identical try/except pattern:

```python
try:
    await session.execute(text("..."))
except DBAPIError as e:
    if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
        await session.rollback()
        await session.execute(text("..."))
    else:
        raise
```

This appears 4 times across 3 functions (once more in `set_tenant_context` for the bypass env-var branch).

**Actionable fix (Extract Function):**

```python
async def _execute_with_failed_txn_recovery(session: AsyncSession, sql: str) -> None:
    try:
        await session.execute(text(sql))
    except DBAPIError as e:
        if e.orig and isinstance(e.orig.__cause__, InFailedSQLTransactionError):
            await session.rollback()
            await session.execute(text(sql))
        else:
            raise
```

Then each function becomes a one-liner calling this helper.

### RF-8: SQL String Interpolation in tenant_context.py (Security + Primitive Obsession)

**Fowler smell:** Primitive Obsession (raw string manipulation where a parameterized query would be safer).

`set_tenant_context()` builds SQL via f-string with manual escaping:

```python
tenant_value = str(tenant_id).replace("'", "''")
await session.execute(text(f"SET LOCAL app.current_tenant = '{tenant_value}'"))
```

While `tenant_id` comes from a `UUID` type (limiting injection surface), this pattern is fragile. PostgreSQL's `SET LOCAL` does not support `$1` parameter binding, but `set_config()` does:

**Actionable fix:**

```python
await session.execute(
    text("SELECT set_config('app.current_tenant', :tenant, true)"),
    {"tenant": str(tenant_id)},
)
```

The third argument `true` makes it transaction-local (equivalent to `SET LOCAL`). This eliminates string interpolation entirely.

### RF-9: Flag Argument in `cluster_unclustered_identities(commit=True)` (Remove Flag Argument)

**Fowler smell:** Remove Flag Argument (p. 314).

The `commit` boolean in `cluster_unclustered_identities()` (and propagated to the `ClusteringOrchestrator`) fundamentally changes the function's behavior: with `commit=True`, RLS context is lost after mid-function commits, post-commit work silently fails, and the caller must know to re-establish context. With `commit=False`, the function is safe.

This is Seam 4 from the RLS audit. The flag argument is the root cause: two radically different execution modes hidden behind a boolean.

**Actionable fix (Split Phase, Fowler p. 154):** Create two explicit entry points:

- `cluster_unclustered_identities_transactional()` for use by the worker (caller owns the transaction; no mid-function commit)
- `cluster_unclustered_identities_autocommit()` for use by the HTTP sync endpoint (commits after each phase; explicitly re-establishes context)

This makes the transaction contract explicit in the function name instead of hidden in a flag.

### RF-10: Missing Observability at Key Decision Points

**What Refactoring UI calls "Don't overlook empty states" (p. 234):** the pipeline has good logging for the happy path (chunk_stats, batch_complete) but poor logging for the "nothing happened" paths.

| Decision point                          | Current logging                       | Gap                                                        |
| --------------------------------------- | ------------------------------------- | ---------------------------------------------------------- |
| MV refresh produces 0 rows              | None                                  | Should log row count; 0 is a health alarm                  |
| Progress callback UPDATE affects 0 rows | None                                  | Should assert or log rowcount                              |
| Purge deletes 0 rows across all models  | None                                  | Should log per-model delete counts; all-zero is suspicious |
| Suggestion backfill finds 0 candidates  | None                                  | Should log; distinguishes "no work" from "RLS filtered"    |
| `_coerce_tenant()` returns `None`       | Error log, but caller returns default | Should be an early abort with clear error                  |

**Actionable fix:** Add structured log lines at each decision point that distinguish "legitimately empty" from "unexpectedly empty." For MV refresh specifically, log `(before_count, after_count)` so a refresh that goes from N to 0 is immediately visible.

### Summary: Refactoring Priority by Debugging Impact

| #     | Finding                                 | Fowler Catalog                           | Debugging Impact                                                | Effort                                  |
| ----- | --------------------------------------- | ---------------------------------------- | --------------------------------------------------------------- | --------------------------------------- |
| RF-1  | Silent failures as default              | Primitive Obsession, Introduce Assertion | **Critical**; directly caused all 4 RLS bugs to ship undetected | Low (add assertions + logging)          |
| RF-2  | Transaction lifecycle not in types      | Temporary Field, Extract Class           | **High**; prevents future SET LOCAL bugs                        | Medium (new TenantSession wrapper)      |
| RF-9  | Flag argument hides two modes           | Remove Flag Argument, Split Phase        | **High**; Seam 4 exists because of this flag                    | Medium (split into two functions)       |
| RF-10 | Missing empty-state observability       | (Refactoring UI: empty states)           | **High**; 0-row results indistinguishable from bugs             | Low (add log lines)                     |
| RF-8  | SQL string interpolation                | Primitive Obsession                      | **Medium**; defense-in-depth for injection                      | Low (use set_config())                  |
| RF-7  | Duplicated try/except in tenant_context | Duplicated Code, Extract Function        | **Medium**; 4 copies of recovery logic                          | Low (extract helper)                    |
| RF-3  | 16-parameter constructor                | Long Parameter List, Data Clumps         | **Medium**; hard to wire correctly                              | Medium (introduce parameter objects)    |
| RF-4  | 1,374-line repository                   | Large Class, Extract Class               | **Medium**; MV refresh buried in unrelated code                 | Medium-High (split into 4 repositories) |
| RF-5  | Duplicated evaluation logic             | Duplicated Code, Extract Function        | **Low-Medium**; bug fixes must be applied twice                 | Low (extract shared function)           |
| RF-6  | Hardcoded magic values                  | (constant extraction)                    | **Low**; no single config surface for tuning                    | Low (consolidate into settings)         |

## Confidence

High confidence:

- this batch was not stuck on the backend
- projection acknowledgement was already persisted
- the UI could remain stale because polling stops too early
- the centroid MV is empty because RLS blocks all rows during concurrent refresh (verified with and without `app.bypass_rls`)
- the repeated worker refresh loop is this broken refresh running every 60 seconds, each time producing 0 rows
- the fix is to set `app.bypass_rls = 'true'` on the AUTOCOMMIT connection before REFRESH
- (ADDITION) the progress checkpoint callback silently loses updates due to the same RLS pattern (code audit; not DB-verified but same mechanism)
- (ADDITION) scheduled disposal is non-functional for the same reason (code audit)
- (ADDITION) HTTP sync clustering loses context after commit, causing post-clustering suggestion work to silently fail (code audit; worker path is not affected because it passes `commit=False`)

## References

- `apps/prototype-description-service/scripts/db_shell.sh`
- `apps/prototype-description-service/logs/scan_worker.log`
- `apps/prototype-description-service/recognition/worker/scan_worker.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
- `apps/prototype-description-service/recognition/worker/handlers/utils.py` (`ensure_job_context`)
- `apps/prototype-description-service/db/tenant_context.py` (`set_tenant_context`, `enable_rls_bypass`)
- `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` (MV definition, RLS policies)
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`
- `docs/literature/extracted/Designing Data-Intensive Applications - The Big Ideas Behind -- Martin Kleppmann -- 6 [early release], 2017 -- O'Reilly Media, Incorporated -- 9781449373320 -- bf7c3fecfe5dcffceb170b2aa6d34c31 -- Anna’s Archive.txt`
- `docs/literature/extracted/Latency- Reduce delay in software systems -- Pekka Enberg -- 1, 2025 nov 25 -- Manning Publications Co_ LLC -- 9781633438088 -- 1e5b0046b5f8e592148d71d26be0de76 -- Anna’s Archive.txt`- `docs/literature/extracted/refactoring/Refactoring-Improving-the-Design-of-Existing-Code-MartinFowlerKentBeck.txt` (Fowler refactoring catalog: Extract Function p. 106, Extract Class p. 182, Introduce Parameter Object p. 140, Remove Flag Argument p. 314, Split Phase p. 154, Introduce Assertion p. 302)
- `docs/literature/extracted/refactoring/Refactoring-UI.txt` (Refactoring UI: "Limit your choices" p. 28, "Don't overlook empty states" p. 234)
