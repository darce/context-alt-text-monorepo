# Projection Stall and Materialized View Refresh Loop Investigation

Date: 2026-03-24

## Scope

This report investigates the latest batch visible in the UI as:

- Job `bb1cad30-88be-4d0e-ab3b-be220b792979`
- Status text: `Syncing projected results...`
- Phase: `Projecting`
- Progress: `937/937 images`

The user-observed suspicion was that the system was "stuck in material view refreshing" based on `apps/prototype-description-service/logs/scan_worker.log`.

## Executive Summary

The evidence shows two related but distinct facts:

1. The clustering work for the batch did finish.
2. After clustering finished, the single `scan_worker` control loop entered a near-continuous `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids` cycle.

The worker-side root cause is a scheduling/design issue:

- `scan_worker.run_forever()` performs MV refresh on the same serialized control path that claims new work.
- `_refresh_mv_if_needed()` records the refresh timestamp using the loop's `now` value from before the refresh starts, not after it finishes.
- When refresh runtime grows to roughly the configured interval (`60s`), the next loop wakes up with `elapsed ~= 60s` and immediately refreshes again.
- That creates a self-sustaining maintenance loop where the worker spends almost all of its wall-clock time refreshing the MV.

However, the UI's `Projecting` label does not mean the worker is still clustering. In the backend, that label is shown when a completed clustering job is in `awaiting_projection`, which specifically means WordPress has not yet acknowledged projection. So the strongest conclusion is:

- The worker is definitely trapped in an MV-refresh-heavy loop.
- The UI is definitely still awaiting projection acknowledgement.
- The logs available here do not prove that the MV loop is the only cause of the missing acknowledgement, but it is a serious latency and control-plane starvation bug that can make the system look stuck and can delay other backend work.

## Evidence

### 1. Clustering completed before the stall

The final clustering logs for follow-up job `c2e831f4-c24e-4b1a-b70e-c0fee716bc0d` show normal completion:

- `18:47:36`: final chunk processed: `processed=937/937`
- `18:47:37`: `singleton_hac_complete`
- `18:47:37`: `batch_complete accepted=391 suggested=109 rejected=28 new_clusters=537`

Source:

- `apps/prototype-description-service/logs/scan_worker.log`

This means the worker was no longer doing clustering work when the repeated MV refresh started.

### 2. The worker then entered a repeating MV refresh cycle

Immediately after clustering completion, the log shows:

- `18:48:09 [worker] Refreshing centroids MV (elapsed=60.7s)`
- `18:49:10 [worker] Refreshing centroids MV (elapsed=60.9s)`
- `18:50:10 [worker] Refreshing centroids MV (elapsed=60.2s)`
- continuing every ~60-61 seconds through at least `19:04:20`

There are no matching "refresh complete" log lines, so the simplest safe inference is:

- each refresh call takes about one minute wall-clock time, and
- the next loop iteration decides it is already time to refresh again.

Source:

- `apps/prototype-description-service/logs/scan_worker.log`

### 3. MV refresh is on the worker's critical path

`run_forever()` executes refresh before it checks for pending clustering jobs or scan items:

```python
now = datetime.now(tz=UTC)
await self._refresh_mv_if_needed(session, now)

if await self._process_pending_clustering_jobs(session=session, now=now):
    ...
else:
    ...
```

Source:

- `apps/prototype-description-service/recognition/worker/scan_worker.py`

This means refresh latency directly delays the worker's ability to do anything else.

### 4. The scheduling timestamp is anchored before the refresh, not after it

Inside `_refresh_mv_if_needed()`:

```python
elapsed = (now - self._last_mv_refresh_time).total_seconds()
...
await cluster_repo.refresh_centroids_view_concurrent()
self._last_mv_refresh_time = now
```

Source:

- `apps/prototype-description-service/recognition/worker/scan_worker.py`

This is the critical scheduling flaw. If refresh starts at `T0`, takes about `60s`, and `_last_mv_refresh_time` is set to `T0` instead of `T1`, then the next loop at about `T1 + 1s` sees `elapsed ~= 61s` and refreshes again immediately.

### 5. The actual refresh operation is a full PostgreSQL MV refresh

The repository executes:

```sql
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_identity_cluster_centroids
```

using an autocommit connection.

Source:

- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`

This is intentionally a heavyweight global maintenance operation. `CONCURRENTLY` avoids blocking readers the same way as a non-concurrent refresh, but it still consumes real database resources and can be slow on large datasets.

### 6. "Projecting" means "awaiting projection acknowledgement"

The analyze/status router maps a completed clustering job to `awaiting_projection` when `projection_acknowledged_at` is still null:

```python
response.progress.phase = "awaiting_projection" if projection.acknowledged_at is None else "complete"
```

Source:

- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`

The admin UI then translates `awaiting_projection` into `Syncing projected results...`.

Sources:

- `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts`

So the frontend is correctly reporting "backend has finished clustering, but WordPress has not acknowledged the projection yet."

## Root Cause

The confirmed root cause is a control-loop scheduling bug combined with a heavyweight maintenance task on the hot path.

More precisely:

1. `scan_worker` is a single serialized control loop.
2. That loop performs a full MV refresh before it checks for new work.
3. The refresh duration has grown to about the same size as the configured interval.
4. The worker records "last refresh time" using the timestamp from before the refresh began.
5. As a result, every subsequent loop immediately becomes eligible for another refresh.

That creates a closed loop:

1. start refresh
2. spend about 60s refreshing
3. wake up and observe that about 60s have elapsed since the recorded timestamp
4. refresh again

This is not a crash. It is a maintenance-feedback loop.

## Why This Matches the Literature

Two themes from the supplied references fit this failure very closely.

### 1. Queueing and head-of-line blocking

Kleppmann explains that client-visible response time includes queueing, not just service time, and that a small number of slow operations can cause head-of-line blocking for subsequent work. See:

- `docs/literature/extracted/Designing Data-Intensive Applications - The Big Ideas Behind -- Martin Kleppmann -- 6 [early release], 2017 -- O'Reilly Media, Incorporated -- 9781449373320 -- bf7c3fecfe5dcffceb170b2aa6d34c31 -- Anna’s Archive.txt` around lines `1248-1260`
- same file around lines `1332-1355`

That is exactly what this worker does: it places a slow MV maintenance job at the front of the only control loop, so all later work waits behind it.

### 2. Background maintenance competing for finite resources

Kleppmann also notes that background compaction/maintenance can interfere with normal reads and writes because disks and databases have finite resources, and that the impact is often most visible at high percentiles rather than averages. See:

- the same DDIA extract around lines `4037-4063`

The repeated MV refresh here is conceptually the same class of problem: a background maintenance task is consuming shared database capacity and stretching system responsiveness.

### 3. Latency compounds across components

Enberg defines latency as the delay between cause and observed effect and emphasizes that end-to-end latency compounds across dependent components. See:

- `docs/literature/extracted/Latency- Reduce delay in software systems -- Pekka Enberg -- 1, 2025 nov 25 -- Manning Publications Co_ LLC -- 9781633438088 -- 1e5b0046b5f8e592148d71d26be0de76 -- Anna’s Archive.txt` around lines `548-569`

In this incident, the UI is waiting on a chain: clustering completion -> projection sync -> acknowledgement. Even if the missing acknowledgement is elsewhere, adding a minute-long maintenance task into the backend loop increases the time and uncertainty of the whole flow.

### 4. Incremental maintenance beats expensive recomputation on the request path

Enberg's discussion of incremental computation and materialized views argues for updating only what changed so reads stay fast and there is "no perceived latency" at query time. See:

- the same Latency extract around lines `4781-4827`

The current implementation does the opposite at the worker level: it repeatedly runs a global refresh instead of narrowing maintenance to the changed clusters or isolating the refresh from latency-sensitive control flow.

## Impact

### Confirmed impact

- The worker spends nearly all of its post-clustering wall-clock time inside or immediately re-entering MV refresh.
- That serially delays any other work owned by `scan_worker`.
- The logs provide poor observability because refresh start is logged, but refresh completion, duration, and row/version effects are not.

### Likely impact

- Higher tail latency for any control-plane work sharing the same backend loop or database resources.
- Longer recovery times for pending scan/clustering follow-up jobs when the MV becomes expensive.

### Not yet proven from the available evidence

- That MV refresh is the sole reason WordPress never acknowledged the projection for this specific job.

I could not confirm that last point because this shell does not currently expose `POSTGRES_DSN`, so I could not inspect the live database state or correlate with WordPress/runtime logs.

## Proposed Fix

### Immediate fix

1. Schedule refreshes from completion time, not start time.

Change:

```python
self._last_mv_refresh_time = now
```

to something equivalent to:

```python
finished_at = datetime.now(tz=UTC)
self._last_mv_refresh_time = finished_at
```

This prevents the self-sustaining "refresh takes interval, therefore refresh again immediately" loop.

2. Add explicit refresh end logging.

Log:

- refresh start time
- refresh completion time
- duration
- whether it actually ran or was skipped
- whether there were any cluster mutations since the last refresh

Without this, operators only see repeated starts and have to infer duration from timestamps.

3. Gate refresh on a dirty flag or mutation watermark.

Do not run a full MV refresh every `60s` unconditionally. Only refresh when clustering, curation, split, or merge-suggestion generation actually changed relevant centroid inputs since the prior refresh.

### Stronger structural fix

4. Move MV refresh off the worker's hot control path.

Run refresh in one of these ways:

- a separate low-priority background task/process
- a dedicated scheduler with its own DB connection pool and timeout policy
- an explicit coalesced maintenance job queue

This follows the same design principle DDIA uses for isolating low-priority batch work from higher-priority online work.

5. Add timeout and backoff.

If one refresh exceeds a threshold, do not immediately retry on the next cycle. Add:

- timeout
- exponential backoff
- jitter
- suppression after N consecutive slow refreshes

### Long-term fix

6. Replace repeated full MV refresh with incremental centroid maintenance.

The codebase already recomputes centroids for specific target clusters in some write paths. The long-term direction should be:

- keep centroid state incrementally updated per changed cluster
- reserve full MV refresh for repair/reconciliation
- run reconciliation rarely and off the latency-sensitive path

This aligns with Enberg's incremental-computation guidance and avoids paying global recomputation cost after every batch.

### Product/UI fix

7. Make the projection wait state more explicit.

Today the UI phrase `Syncing projected results...` can be misread as "the Python worker is still doing work." In reality, the backend state is "clustering complete, waiting for WordPress projection acknowledgement."

The UI should distinguish:

- `Projecting locally`
- `Waiting for WordPress sync`
- `Acknowledging projection`

That would have made this incident easier to interpret.

## Recommended Validation Plan

1. Add instrumentation around `refresh_centroids_view_concurrent()` with start/end timing.
2. Reproduce on a representative dataset and confirm refresh duration.
3. Change the scheduler to stamp completion time, then verify that a 60s refresh does not immediately trigger another 60s refresh.
4. Add a dirty-flag guard and confirm idle workers do not refresh continuously when no writes occurred.
5. Correlate the same run with WordPress sync logs or API access logs to determine why `projection_acknowledged_at` remained null.

## Confidence

High confidence:

- clustering completed successfully
- the worker entered a repeated MV refresh loop
- the loop is caused by serial placement of refresh on the control path plus completion-vs-start scheduling

Medium confidence:

- this loop materially contributed to the perceived stall

Lower confidence:

- this loop alone explains the missing projection acknowledgement

## References

- `apps/prototype-description-service/logs/scan_worker.log`
- `apps/prototype-description-service/recognition/worker/scan_worker.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py`
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py`
- `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachineEffects.ts`
- `docs/literature/extracted/Designing Data-Intensive Applications - The Big Ideas Behind -- Martin Kleppmann -- 6 [early release], 2017 -- O'Reilly Media, Incorporated -- 9781449373320 -- bf7c3fecfe5dcffceb170b2aa6d34c31 -- Anna’s Archive.txt`
- `docs/literature/extracted/Latency- Reduce delay in software systems -- Pekka Enberg -- 1, 2025 nov 25 -- Manning Publications Co_ LLC -- 9781633438088 -- 1e5b0046b5f8e592148d71d26be0de76 -- Anna’s Archive.txt`
