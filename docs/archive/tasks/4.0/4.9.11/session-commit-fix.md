# Fix: Session Transaction Conflict in Scan Worker

**Date**: 2025-12-27  
**Issue**: Scan worker crashes with `UPDATE expected 1 row, 0 matched` during curation follow-ups  
**Related**: 4.9.10.a latency fixes, WP timeout on large clustering jobs

---

## Problem Summary

The scan worker crashes repeatedly with:

```
UPDATE statement on table 'identity_clustering_jobs' expected to update 1 row(s); 0 were matched.
This Session's transaction has been rolled back due to a previous exception during flush.
```

**Root Cause (current)**: Transaction/tenant context is still getting reset during curation follow-ups. When `SET LOCAL` RLS context is lost, the `identity_clustering_jobs` update matches 0 rows and SQLAlchemy raises a stale update error.

**Observed flow**:
1. `_process_pending_clustering_jobs` locks a job row, sets `status="running"` via `session.flush()`.
2. `_handle_curation_job` calls `run_curation_job` → `cluster_unclustered_identities`.
3. Tenant/RLS context is cleared (commit or context reset).
4. `_handle_curation_job` tries to update job row → `0 rows matched` error.

---

## Solution (In Progress)

### Fix 1: Guard commits + reassert tenant context

`cluster_unclustered_identities()` already supports a `commit: bool = True` flag, and curation jobs pass `commit=False` so the scan worker controls the transaction. This was necessary but not sufficient, so we now also reassert tenant/RLS context before updating the curation job row.

**Files touched**:

| File | Change |
|------|--------|
| `recognition/application/orchestration/incremental_clustering.py` | Commit guard (`commit` flag) controls internal commit. |
| `recognition/application/orchestration/cluster_service.py` | Pass `commit` through to incremental clustering. |
| `recognition/application/orchestration/curation_job.py` | Call clustering with `commit=False` during curation follow-ups. |
| `recognition/worker/scan_worker.py` | Reassert tenant/RLS context before updating job rows. |

**Commit guard** (`incremental_clustering.py`):

```python
async def cluster_unclustered_identities(..., commit: bool = True) -> ClusteringResult:
    # ... processing ...
    if commit:
        await session.commit()
    return result
```

**Curation job call** (`curation_job.py`):

```python
result = await cluster_service.cluster_unclustered_identities(tenant_id, commit=False)
```

**Context reassertion** (`scan_worker.py`):

```python
await set_tenant_context(session, job.tenant_id)
await enable_rls_bypass(session)
```

### Fix 2: Increased Timeout for Clustering (Status Unknown)

A 120s proxy timeout was proposed as a stopgap. This change is not verified on this branch and does not address the scan worker crash.

### Fix 3: Async Mode with Polling (Deferred)

The long-term fix is to use `mode=async` for clustering and implement frontend polling.

---

## Verification

Not rerun on this branch.

---

## Files Modified

```
apps/prototype-description-service/recognition/application/orchestration/incremental_clustering.py
apps/prototype-description-service/recognition/application/orchestration/cluster_service.py
apps/prototype-description-service/recognition/application/orchestration/curation_job.py
apps/prototype-description-service/recognition/worker/scan_worker.py
apps/prototype-description-service/recognition/tests/fakes.py
```

---

## Completion Checklist

- [x] Add commit guard in incremental clustering and thread it through cluster service + curation job.
- [x] Reassert tenant/RLS context before updating curation job rows in scan worker.
- [x] Update test fakes to accept `commit` parameter for clustering calls.
- [ ] Validate scan worker no longer crashes after curation jobs.
- [ ] Confirm WP clustering/merge UX latency improvements (if async follow-up is added).
