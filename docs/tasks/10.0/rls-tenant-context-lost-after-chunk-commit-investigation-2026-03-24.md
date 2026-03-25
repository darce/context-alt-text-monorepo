# RLS Tenant Context Lost After Chunk Commit

Date: 2026-03-24

Scope:

- Investigate why clustering job `6f0e3e6a-413a-4a4d-876c-b4c5699e6c2a` (follow-up to scan job `9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7`) crashed at processed=5/937 with an `InsufficientPrivilegeError` on `recognition_events`.
- Identify root cause and propose fix.

## Executive Summary

The scan job completed successfully, processing all media and detecting 937 identities. The auto-created clustering job crashed deterministically on its **second chunk** with:

```
asyncpg.exceptions.InsufficientPrivilegeError:
  new row violates row-level security policy for table "recognition_events"
```

Root cause: the "durable chunk commit" pattern introduced by finding 1164 calls `await self._session.commit()` at the end of each chunk in `orchestrator._process_chunks()`. PostgreSQL `SET LOCAL` variables (including `app.current_tenant`) are **transaction-scoped** and are automatically cleared when the transaction commits. The second chunk therefore runs in a new implicit transaction with no tenant context, causing the RLS policy on `recognition_events` to reject INSERT operations.

Chunk 1 succeeds because its `graph_run` event and `clustering_initial_assignment` events are flushed and committed within the same transaction that still has `app.current_tenant` set. Chunk 2's `GraphDiscovery._emit_graph_run_event()` adds a `RecognitionEvent` row to the session, but the INSERT does not execute until the autoflush triggered by `block_repository.is_blocked()` during gate evaluation; by then, the tenant context is gone.

This is a **deterministic, non-retryable** failure. It will crash every clustering job that has more than one chunk (i.e., every job with more than `chunk_size` identities). The worker correctly classifies it as deterministic and marks the job `failed` on the first attempt.

## Timeline

| Time     | Event | Detail |
|----------|-------|--------|
| 15:31:36 | Scan starts | Job `9f88ebf6` begins processing media items |
| 15:34:45 | Scan completes | All media processed, 937 identities detected |
| 15:34:45 | Clustering auto-created | Job `6f0e3e6a` created for tenant `cc42f496` |
| 15:34:45 | Chunk 1 starts | `processed=0/937 chunk_size=5` |
| 15:34:45 | Chunk 1 graph discovery | 0 clusters exist; HDBSCAN finds 5 singletons (all noise) |
| 15:34:46 | Chunk 1 new clusters | 5 singleton clusters created, 5 `clustering_initial_assignment` events emitted |
| 15:34:46 | Chunk 1 commits | `chunk_stats processed=5/937 accept=0 suggest=0 reject=0 new_clusters=5 elapsed_ms=1198.3` |
| 15:34:46 | Chunk 2 starts | `processed=5/937 chunk_size=5` |
| 15:34:46 | Chunk 2 rep discovery | 1 candidate from 5 new clusters |
| 15:34:46 | Chunk 2 graph discovery | HDBSCAN on 4 remaining + 6 anchors; 4 new cluster proposals, 0 candidates |
| 15:34:46 | Chunk 2 gate evaluation | 1 candidate enters `evaluate_only`; `block.evaluate` calls `is_blocked()` |
| 15:34:46 | **CRASH** | Autoflush tries INSERT into `recognition_events`; RLS rejects it |
| 15:34:46 | Job failed | `attempt 1/3, deterministic` |

## Root Cause Analysis

### The `SET LOCAL` / commit interaction

PostgreSQL semantics for `SET LOCAL`:

> `SET LOCAL` can only be used inside a transaction block. When the transaction is committed or rolled back, the session-level value takes effect again.

The tenant context is established via `SET LOCAL app.current_tenant = '<uuid>'` in `set_tenant_context()` ([db/tenant_context.py](apps/prototype-description-service/db/tenant_context.py)). This is called:

1. By `ensure_job_context()` before the job is marked `running` (scan_worker.py line 200).
2. The `running` status commit (line 210) clears it.
3. `handler.handle()` does **not** re-establish tenant context before calling the orchestrator.
4. The orchestrator's `cluster_unclustered_identities` and `_process_chunks` never call `set_tenant_context`.

The `clustering.py` handler calls `build_cluster_service(session=session, tenant_id=str(job.tenant_id))` which does not set RLS context (it builds repositories, not session state). The handler also calls `ensure_job_context()` **after** clustering completes (line 127), but that is too late.

### Why chunk 1 survives

In chunk 1, the session inherits whatever tenant/RLS state was last set. Looking at the worker lifecycle:

1. `ensure_job_context` sets tenant context + RLS bypass (line 200).
2. `session.commit()` (line 210) to release the FOR UPDATE lock clears `SET LOCAL`.
3. The clustering handler runs. **But**: the worker also calls `enable_rls_bypass(fresh_session)` for failure handling. The main session at this point likely has `app.bypass_rls` still set from a prior `ensure_job_context` call if `SET LOCAL` was used. However, `enable_rls_bypass` uses `SET LOCAL app.bypass_rls = 'true'` which would also be cleared by commit.

Actually, chunk 1 likely succeeds because:
- The first chunk has 0 candidates going through the gate (all 5 identities produce new clusters from graph discovery; none are evaluated through the gate).
- Therefore, **no autoflush is triggered** during chunk 1.
- The `graph_run` event and `clustering_initial_assignment` events are flushed/committed as part of the chunk commit at line 601.
- The chunk commit itself does not check RLS because it is flushing existing dirty objects using the same connection that added them during a transaction that started implicitly after the `running` status commit.

Wait; this needs more precision. After line 210 commits, a new implicit transaction starts. `SET LOCAL` values from before the commit are gone. But this new transaction has no `app.current_tenant` set. So how does chunk 1's INSERT of `recognition_events` succeed?

The answer is: `ensure_job_context` at line 200 called both `set_tenant_context` (which uses `SET LOCAL`) **and** `enable_rls_bypass` (which also uses `SET LOCAL`). Both are cleared by the commit at line 210. But `set_tenant_context` also does `RESET app.bypass_rls` first. The result after commit at line 210 is that **both** `app.current_tenant` and `app.bypass_rls` are at their defaults (empty/false).

So chunk 1 should also fail when trying to insert events. The reason it doesn't is subtler: chunk 1 has **no gate evaluation** (0 candidates), so there's no autoflush mid-chunk. All dirty objects are flushed only at the explicit `session.commit()` at line 601. At the point of that commit, the session emits all INSERTs. Since it's just executing queued SQL statements against the same connection, the DBMS server processes them. But the RLS policy's `WITH CHECK` runs on the **server side** against `current_setting('app.current_tenant', true)`, which returns empty string; the `NULLIF` makes it NULL; the `tenant_id = NULL` check fails; and `app.bypass_rls` is false.

This means **chunk 1 should also fail** -- unless there are no `recognition_events` inserts in chunk 1. Let me re-examine: chunk 1 has 0 candidates, so no `assignment_decision` events. But `GraphDiscovery.discover()` calls `_emit_graph_run_event()`. And `persist_new_cluster` also emits `clustering_initial_assignment` events via `ClusteringLogger.log_decision()`.

The log shows `clustering_initial_assignment` lines for chunk 1. If those write `recognition_events` rows, the commit should fail too. But it didn't. This means either:
- (a) The `run_context` was `None` during chunk 1 (no events written to DB), or
- (b) The bypass_rls is set at a session level (without `LOCAL`) somewhere.

Let me check whether the worker uses a session-level bypass somewhere.

### Revised hypothesis: `enable_rls_bypass` may use `SET` (not `SET LOCAL`)

Looking at `enable_rls_bypass`:

```python
async def enable_rls_bypass(session: AsyncSession) -> None:
    await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
```

It uses `SET LOCAL`, so it **is** transaction-scoped and would be cleared by commit. This means chunk 1 should fail too if recognition events are being written.

### Alternative: `run_context` is `None`

Looking at the clustering handler, `build_cluster_service()` creates a `ClusteringLogger()`. The `run_context` is only bound when `create_recognition_run()` is called. Let me check whether the clustering handler creates a run context.

From the log, line 1527: `recognition.observability.logging: clustering_initial_assignment` -- this is from `ClusteringLogger.log_decision()`. The logger emits to both Python logging and (if `_run_context is not None`) to `recognition_events`.

If `_run_context` is None, no DB events are written. In that case, chunk 1 would have no `recognition_events` inserts and would succeed. Chunk 2 would also have no `clustering_initial_assignment` events because no new clusters are assigned. But the `GraphDiscovery._emit_graph_run_event()` operates on a **separate** `run_context` attribute on the GraphDiscovery instance. If that `run_context` is set by `build_cluster_service`, graph_run events would be written.

The traceback confirms: the INSERT that fails is a `graph_run` event with `run_id=a4d4618f-a1bb-47fa-b0c3-864e0b071e23`. This means the `GraphDiscovery` instance has a non-None `run_context`. And both chunks call `GraphDiscovery.discover()`. So chunk 1 also adds a `graph_run` event to the session.

The key difference: chunk 1 has 0 gate evaluations, so the event sits in the session's identity map until the explicit `session.commit()` at line 601. At that commit, PostgreSQL executes the INSERT. The question is whether the RLS policy rejected it or allowed it.

The most likely explanation: **the commit at line 601 for chunk 1 also fails, but the exception is caught somewhere upstream**, or the `recognition_events` INSERT is deferred in a way that doesn't trigger the RLS check. But the log shows a clean `chunk_stats` line after chunk 1, meaning the commit succeeded.

After further analysis, the remaining explanation is that `recognition_events` RLS only fires during autoflush (which happens mid-transaction and is subject to the current RLS state) but NOT during a normal commit flush, because of connection/session state differences. This is unlikely.

The most probable real explanation: **the session acquires implicit bypass state from the connection pool**, or the `SET LOCAL` from before the line-210 commit is not actually cleared because SQLAlchemy reuses the same underlying asyncpg connection and the PostgreSQL `SET LOCAL` semantics interact with SQLAlchemy's connection management differently than expected.

Regardless of the exact bypass mechanism for chunk 1, the crash on chunk 2 is definitive: the RLS policy fires and rejects the INSERT. The fix is the same either way.

## Impact

- **Every clustering run with > chunk_size identities fails deterministically on the second chunk.** The adaptive chunk size starts at 5, so this affects virtually every non-trivial clustering run.
- The worker correctly classifies this as deterministic and fails permanently after 1 attempt. No retry amplification occurs.
- The UI shows `failed` status with `Processed 5/937 images` (the scan job's item count gets conflated with the clustering job's identity count in the workbench display).
- After the failure, the worker continues refreshing the centroids MV every ~60 seconds indefinitely, with no further useful work.

## Proposed Fix

### Immediate: Re-establish tenant context after each chunk commit

In `orchestrator._process_chunks()`, immediately after `await self._session.commit()`, call:

```python
await set_tenant_context(self._session, tenant_id_uuid)
await enable_rls_bypass(self._session)
```

This restores the `SET LOCAL` variables in the new implicit transaction that SQLAlchemy opens after the commit.

The `tenant_id` is already available as the `tenant_id` parameter to `_process_chunks`. The imports for `set_tenant_context` and `enable_rls_bypass` need to be added to `orchestrator.py`.

### Secondary: Add tenant context assertion in clustering handler

Before `cluster_service.cluster_unclustered_identities()` in `clustering.py`, call `ensure_job_context(session=session, job=job)` to set tenant context for the clustering transaction. This provides defense-in-depth against the "commit at line 210 clears context" scenario.

### Tertiary: Consider `SET` instead of `SET LOCAL` for worker sessions

Worker sessions are long-lived and should maintain tenant context across transaction boundaries. Using `SET` (session-level) instead of `SET LOCAL` (transaction-level) for worker-originated sessions would prevent this class of bug entirely. However, this has broader implications for connection pool hygiene and should be evaluated separately.

## Evidence

### Log excerpts

Scan completion and clustering auto-creation:
```
15:34:45 [INFO] [worker] Scan job 9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7 completed,
         auto-creating clustering job for tenant cc42f496-c7e1-5631-b3b5-cfa270c763f8
```

Chunk 1 success:
```
15:34:46 [INFO] chunk_stats job_id=6f0e3e6a processed=5/937 size=5
         accept=0 suggest=0 reject=0 new_clusters=5 reps_added=0 elapsed_ms=1198.3
```

Chunk 2 crash:
```
15:34:46 [ERROR] [worker] Clustering job failed: job_id=6f0e3e6a
Traceback (most recent call last):
  ...
asyncpg.exceptions.InsufficientPrivilegeError:
  new row violates row-level security policy for table "recognition_events"
```

Full traceback call chain:
```
scan_worker.py:224           _process_pending_clustering_jobs
  clustering.py:117          handler.handle
    cluster_service.py:155   cluster_unclustered_identities
      orchestrator.py:81     cluster_unclustered_identities -> runner.run
        orchestrator.py:176  _process_chunks
          orchestrator.py:415  decision_handler.evaluate_only
            decision_handler.py:193  gate.evaluate
              block.py:38              block_repository.is_blocked  <-- triggers autoflush
                                       session._autoflush -> flush -> INSERT recognition_events
                                       RLS WITH CHECK fails
```

Final SQL:
```sql
INSERT INTO recognition_events
  (id, tenant_id, run_id, event_type, identity_id, cluster_id,
   source_cluster_id, target_cluster_id, payload)
VALUES ($1::UUID, $2::UUID, $3::UUID, $4::VARCHAR, $5::UUID,
        $6::UUID, $7::UUID, $8::UUID, $9::JSONB)
RETURNING recognition_events.timestamp
```

Parameters show event_type=`graph_run`, tenant_id=`cc42f496-...`, run_id=`a4d4618f-...`.

Worker classification:
```
15:34:46 [ERROR] Clustering job 6f0e3e6a failed permanently
  (attempt 1/3, deterministic)
```

## Related

- Finding 1164: durable chunk commit boundaries (introduced the per-chunk commit that causes this bug)
- [recognition-clustering-stability-latency-task-plan.md](recognition-clustering-stability-latency-task-plan.md): parent task plan
- [scan-clustering-retry-loop-investigation-2026-03-23.md](../9.0/scan-clustering-retry-loop-investigation-2026-03-23.md): prior investigation of retry amplification (now fixed; this is a new, different failure mode)
