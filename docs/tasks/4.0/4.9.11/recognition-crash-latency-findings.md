# Recognition Crash + Merge Latency Findings (Post 2025-12-26 23:56)

Date: 2025-12-27
Scope: recognition + scan worker logs after 2025-12-26 23:56:03,700, and session commit analysis.

## Summary

- The recognition service is still hitting transaction-aborted errors and deadlocks during manual merge/rename flows, which surface as 500s and can trigger process restarts.
- The scan worker still crashes after curation jobs with the same `UPDATE expected 1 row(s); 0 were matched` error. The commit guard is present in the code, so the remaining failure likely comes from tenant/RLS context being reset mid-flow or the guard not being exercised in runtime.
- Merge requests remain synchronous and heavy (member moves, representative/centroid recompute, view refresh, source delete), causing slow UX and increasing lock contention; large merges (45-50 identities) are present in the logs.

## Log Review (after 2025-12-26 23:56:03,700)

### recognition.log

Key events and errors:

- 23:56:45: Unique constraint violation on `identity_clusters.label` during rename (`unique_tenant_identity_label`), logged in `get_optional_session` as a commit error. This aborts the transaction and returns 500.
- 23:57:14: Merge succeeds log entry, but immediately followed by `InFailedSQLTransactionError` on a SELECT in `clusters.py` -> `cluster_merge.py` -> `cluster_repository.delete`, which indicates the transaction was already aborted. This is logged as an unhandled exception and yields a 500.
- 23:58:22 and 23:58:58: very large merges (moved_count=50 and moved_count=45) executed in-line, likely driving long request times and lock contention.
- 23:59:46: Another `InFailedSQLTransactionError` during merge. Same failure mode as above.
- 00:05:22: Deadlock detected while moving members (`UPDATE identity_members SET cluster_id=...`). The exception is unhandled and returns 500.

These failures align with the reported UI stutter + repeated merge prompts: a failed merge leaves the transaction aborted, the request 500s, and the UI retries or replays the merge.

### scan_worker.log

There are no scan worker entries at 23:56 itself; the next curation job activity starts at 00:01:15. The pattern is consistent with the known crash:

- 00:01:15–00:01:17: curation job starts, incremental clustering runs, job completes.
- 00:01:17: scan worker crashes with `UPDATE statement on table 'identity_clustering_jobs' expected to update 1 row(s); 0 were matched`.

This is the same error shown repeatedly earlier in the evening (23:50–23:52), so the underlying session/transaction issue is still active.

## Session Commit Fix Status (from session-commit-fix.md)

`docs/tasks/4.0/4.9.11/session-commit-fix.md` claims:
- `cluster_unclustered_identities()` has a `commit: bool` parameter
- curation jobs call it with `commit=False`

Current code now includes the `commit` guard and the curation job call passes `commit=False`, but the scan worker crashes persist in the logs. That means either:
- The runtime branch doesn’t include these changes, or
- Another path is still resetting the tenant/RLS context (or committing) before the job row update.

This still aligns with the observed error: once `SET LOCAL` context is lost, the `identity_clustering_jobs` update is filtered by RLS and yields a 0-row update, which SQLAlchemy treats as stale.

## Root Cause Analysis (Session + Merge Latency)

1) Transaction or tenant context is still being reset during curation follow-ups.
- Even with `commit=False`, a commit or context reset anywhere in the flow clears `SET LOCAL` values.
- Once that happens, the scan worker’s final job update is filtered by RLS and returns 0 rows.

2) Merge endpoint does too much work synchronously.
- `cluster_merge.merge_cluster()` moves all members, recomputes representatives, recomputes centroids, refreshes centroids view, broadcasts events, and deletes the source cluster inside the request.
- Large merges (45–50 identities) amplify lock duration and slow response time, making the UI feel blocked and increasing the chance of timeouts and deadlocks.

3) Error handling allows aborted sessions to continue.
- `UniqueViolationError` (label collisions) and `DeadlockDetectedError` leave the session in an aborted state.
- Subsequent SELECTs inside the same request produce `InFailedSQLTransactionError`, which is logged as an unhandled exception.

4) Concurrency + retries are generating deadlocks.
- The log shows deadlock on `identity_members` updates during merge.
- UI retries or multiple merge events (due to slow responses) likely increase overlap and contention.

## Recommendations (Targeting Fast Merge + Crash Fix)

Immediate, high-impact:

1) Enforce tenant/RLS context before updating `identity_clustering_jobs`.
- Reapply `set_tenant_context()`/RLS bypass after curation work and before updating the job row.
- If needed, reload the job row after any commit and update the fresh instance.

2) Return early from merge and defer heavy recompute work.
- Make merge endpoint only reassign members + update target metadata, then enqueue a curation job to recompute reps/centroids and refresh the centroid view.
- This immediately improves latency and reduces lock time.

3) Harden merge and rename error handling.
- Catch `UniqueViolationError` and return a 409 response without continuing the transaction.
- Catch `DeadlockDetectedError`, rollback, retry with backoff, or return a 409/503 for the UI to retry safely.

4) Add idempotency/merge dedupe.
- If a source cluster is already merged or deleted, return a successful no-op response to prevent repeated merges of the same source.

Medium-term (structural):

5) Prefer async clustering and async merge follow-ups.
- The contract already supports `mode=async` for clustering; extend to merge follow-up jobs and surface job progress in the UI.

6) Explicit timeouts and lock ordering.
- Set `lock_timeout` for `move_members` updates; ensure a consistent locking order between source/target to reduce deadlocks.

## Files to Update (based on current code)

- `apps/prototype-description-service/recognition/application/orchestration/incremental_clustering.py`
- `apps/prototype-description-service/recognition/application/orchestration/cluster_service.py`
- `apps/prototype-description-service/recognition/application/orchestration/curation_job.py`
- `apps/prototype-description-service/recognition/application/orchestration/cluster_merge.py`
- `apps/prototype-description-service/recognition/worker/scan_worker.py`

## Implementation Started

- Reassert tenant/RLS context in `scan_worker.py` before updating curation/split job rows.

## Related Context

- API contract confirms synchronous clustering/merge paths in the WP proxy (`docs/architecture/contracts/clustering-api.md`) and recognition service (`docs/architecture/contracts/recognition-clustering.md`), which explains why long merges block the UI.
