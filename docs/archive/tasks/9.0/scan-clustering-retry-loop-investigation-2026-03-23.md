# Scan Clustering Retry Loop Investigation

Date: 2026-03-23

Scope:

- Investigate why a 500-image analyze batch appears frozen in the UI while clustering is still running.
- Investigate why clustering performance regressed from seconds to hours.
- Investigate repeated SQL integrity errors in the description-service worker.
- Produce findings and actionable improvement options without changing code yet.

## Executive Summary

The 500-image scan itself is not what is stuck. The scan job `2505e432-c169-493e-b864-f130fc1e6a6f` completed successfully at 19:15:24 with 500/500 media processed and 937 identities detected. The long-running work is the auto-created follow-up clustering job `ed3e2da0-0c2c-4747-814a-9f11ec3c8481`.

The main failure pattern is a retry loop:

- the clustering worker processes the job up to `750/937`,
- reaches HAC refinement on the remaining 14 noise identities,
- hits `unique_identity_membership`,
- crashes the entire worker process,
- restarts,
- immediately reclaims the same clustering job as `pending`,
- and reprocesses all 937 identities from scratch.

This happened at least 77 times in the current `scan_worker.log`, which explains both the apparent UI freeze and the dramatic runtime regression. The log has grown to 243,035 lines largely because the same work is being replayed and logged over and over.

The most likely immediate root cause is overlapping fallback assignment paths inside one clustering transaction. Specifically, identities that were already routed into a fallback new-cluster path are still included in HAC refinement, causing the same identity to be inserted into `identity_members` twice before the transaction commits.

## High-Confidence Findings

### 1. The scan completed; clustering is what is looping

Database inspection:

- `identity_scan_jobs.id = 2505e432-c169-493e-b864-f130fc1e6a6f`
- status = `completed`
- processed_media = `500`
- total_media = `500`
- identities_detected = `937`
- completed_at = `2026-03-23 19:15:24`

Follow-up clustering row:

- `identity_clustering_jobs.id = ed3e2da0-0c2c-4747-814a-9f11ec3c8481`
- status = `pending`
- processed_identities = `0`
- total_identities = `0`
- started_at = `NULL`
- completed_at = `NULL`

That DB state already explains a large part of the UX problem: the backend worker is doing clustering work, but the durable clustering job row never gets out of its initial placeholder state.

### 2. The worker is replaying the same clustering job from the beginning

Evidence from `apps/prototype-description-service/logs/scan_worker.log`:

- first clustering attempt begins at line `1515`
- the job reaches `processed=750/937` at line `4451`
- after the crash, the same job restarts at line `4651`
- this pattern repeats throughout the log
- another late cycle reaches `processed=750/937` at line `236566`
- the next restart begins immediately after at line `236766`

Counts from the current log:

- `batch_start job_id=ed3e2da0-0c2c-4747-814a-9f11ec3c8481`: 77 times
- `processed=750/937`: 77 times
- `duplicate key value violates unique constraint "unique_identity_membership"`: 77 times

This is the single biggest reason clustering now takes hours instead of seconds.

### 3. The integrity error happens during or immediately after HAC refinement on the final 14 noise identities

Representative crash sequence from `scan_worker.log`:

- line `236566`: `chunk_processing ... processed=750/937 chunk_size=50`
- line `236759`: `Running HAC refinement on 14 noise identities`
- line `236760`: worker crash with `duplicate key value violates unique constraint "unique_identity_membership"`

The worker then reconnects and starts the same clustering job again:

- line `236766`: `batch_start job_id=ed3e2da0...`
- line `236768`: `batch_processing ... count=937`
- line `236769`: `chunk_processing ... processed=0/937 chunk_size=5`

### 4. The failing identities were already part of the chunk’s fallback flow before HAC tried to cluster them

The crashing insert contains these two identity IDs:

- `164a03dc-158c-4599-9a26-32c631ddd5bf` with `media_id=6336`
- `c1d31d73-0c9c-4d4d-9564-aa14894ce798` with `media_id=6346`

Just before the crash, the same two identities were logged as `SUGGESTED`:

- line `236651`: identity `164a03dc...` suggested to cluster `963cfd76...`
- line `236680`: identity `c1d31d73...` suggested to cluster `963cfd76...`

Immediately after those suggestions, HAC runs over `still_unclustered` and tries to create a new cluster containing those same two identities, leading to the failing insert parameters at line `236762`.

This strongly suggests duplicate assignment inside one transaction, not a conflict with old committed membership rows. Supporting evidence:

- `identity_members` currently has `0` rows for the tenant after the crash loop
- so the unique violation is likely between two inserts from the same failed run rather than against surviving state from a previous run

### 5. The code path allows the same identities to enter multiple fallback cluster-creation stages

Relevant code:

- `apps/prototype-description-service/recognition/application/orchestration/clustering/orchestrator.py`
- `apps/prototype-description-service/recognition/application/orchestration/clustering/discovery_pipeline.py`
- `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py`
- `apps/prototype-description-service/recognition/infrastructure/repositories/member_repository.py`

Important behavior:

- `still_unclustered` includes `no_candidates + rejected_identities + suggested_identities`
- graph fallback can create new clusters from `still_unclustered`
- then `run_hac_refinement(still_unclustered=still_unclustered, ...)` is called on the same list
- `persist_new_cluster()` uses `bulk_add_members()` with a plain insert and no deduplication
- the DB constraint `unique_identity_membership` enforces one membership row per identity per tenant

The highest-confidence hypothesis is:

1. a pair of identities is considered "suggested but still unclustered"
2. one fallback path already persists a fallback cluster for them
3. HAC refines the same identities again because the list was never reduced
4. `bulk_add_members()` attempts a second membership insert for the same identity IDs
5. the session becomes invalid during flush
6. the entire clustering transaction rolls back

### 6. The worker crash path amplifies the problem by losing all durable progress

Relevant worker code:

- `apps/prototype-description-service/recognition/worker/scan_worker.py`
- `apps/prototype-description-service/recognition/worker/handlers/clustering.py`

Observed behavior:

- the worker sets the clustering job row to `running`
- progress callbacks flush in the same session/transaction
- a flush-time integrity error invalidates that session
- the outer worker loop crashes
- the process restarts
- because the transaction rolled back, the clustering job row is still `pending 0/0`
- the same job is immediately eligible for reclamation again

In practice, this turns one correctness bug into a severe latency bug.

### 7. The UI freeze is real, but it is downstream of missing durable clustering state

The admin is not just "slow"; it is under-informed.

Relevant frontend files:

- `apps/prototype-wp-alt-context/js/admin/hooks/useJobStateMachine.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/jobStateMachineUtils.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useRecognitionHooks.ts`
- `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts`
- `apps/prototype-wp-alt-context/js/admin/pages/workbench/Panels.tsx`

Two issues combine here:

1. The backend follow-up clustering job never persists a truthful `running/progress` state because its transaction keeps rolling back. The UI therefore has very little reliable progress metadata to show.

2. The live workbench state machine is oriented around locally persisted active job IDs. Auto-created follow-up clustering jobs are not obviously promoted into that local active-job list, so the UI’s phase handoff from scan to clustering is fragile even when the backend chaining works.

The current user-visible symptom:

- button text remains `Scanning media…`
- status text can remain stale or generic
- the user gets no meaningful ETA, retry count, or "clustering currently running" signal

### 8. Log volume itself is now part of the runtime tax

The active worker log is 243,035 lines and growing.

The repeated work loop causes:

- repeated `batch_start`
- repeated per-identity `ACCEPTED`, `SUGGESTED`, `REJECTED`
- repeated per-cluster `new_cluster`
- repeated HAC logs
- repeated worker crash traces

This is not the root cause, but it is adding overhead and making diagnosis harder.

### 9. Worker restarts also force extra MV refresh work

On every worker restart, `_last_mv_refresh_time` is reset in memory. The next loop immediately runs:

- `[worker] Refreshing centroids MV (elapsed=639099...)`

That means every failed attempt pays the MV refresh cost again before re-entering clustering. This is secondary compared with replaying 937 identities, but it still worsens tail latency.

## Root Cause Hypothesis

### Primary root cause

Duplicate identity assignment inside one clustering run caused by overlapping fallback stages:

- the same identity can be "suggested" and still left in `still_unclustered`
- graph fallback can create a new fallback cluster for it
- HAC then runs against the unchanged `still_unclustered` list
- the same identity is inserted again into `identity_members`

Confidence: high

### Secondary root cause

The clustering job uses one broad transaction scope, so a late-stage integrity error rolls back:

- job state transition to `running`
- chunk-level progress updates
- all created clusters and memberships

That makes the job look untouched in durable storage and causes indefinite replay.

Confidence: high

### UX root cause

The admin relies on durable job state plus locally tracked job IDs. Because the follow-up clustering job never durably advances and may not be adopted as the current stream target, the user sees a stale scan-oriented state instead of truthful clustering progress.

Confidence: medium-high

## Why This Became So Slow

The clustering algorithm is probably not intrinsically 100x slower. The system is slow because failed work is being repeated.

Using the current run as an example:

- one clustering attempt reaches 750/937 and then fails
- all work rolls back
- the worker restarts and repeats the first 750 identities
- this happened 77 times in the current log

This is classic retry amplification. DDIA’s discussion of idempotence is directly relevant here: retries are only safe when the operation has the same effect as running once. Right now, clustering writes are not effectively idempotent across overlapping fallback paths. DDIA’s transaction discussion is relevant too: when one late operation fails, the whole transaction aborts and the application safely retries, but only if retry does not re-trigger the same duplication condition.

The latency literature is also a good fit:

- Little’s Law is a reminder that growing concurrency and queue depth increase latency
- latency is a distribution, not a single value, so repeated failure loops dominate the tail
- every component of latency compounds, which is exactly what happens when replayed chunk work, MV refresh, DB flush failures, and logging all stack up
- backpressure is missing here; the system keeps retrying a permanently failing job instead of reducing load or halting

## Actionable Improvement Options

These are intentionally framed as next-step proposals, not code changes made in this task.

### Correctness fixes

1. Prevent duplicate assignment across fallback stages

- After graph fallback persists a new cluster, remove those identities from the HAC candidate set.
- Alternatively, make `run_hac_refinement()` operate only on identities that remain truly unassigned after earlier fallback writes.
- Add an invariant check before HAC persistence: skip any identity already assigned in the current run/session.

2. Make membership writes idempotent at the persistence boundary

- `bulk_add_members()` is currently a plain insert.
- Consider conflict-safe insert behavior similar to `add_member_if_not_exists()`.
- At minimum, add a defensive dedupe pass on identity IDs before bulk insertion.
- Better: treat duplicate membership attempts as a structured signal that the planner produced overlapping assignments, and fail earlier with targeted diagnostics.

3. Narrow transaction scope

- Use chunk-level commits or savepoints instead of one broad transaction for the entire clustering job.
- Persist `job.status = running` and chunk progress outside the same failure-prone unit as member insertion.
- If a late chunk fails, preserve earlier successful chunks and fail/resume from the checkpoint instead of replaying the entire job.

4. Roll back and fail the job cleanly on integrity errors

- Once a flush raises, explicitly `rollback()` before trying to mark the job failed.
- If the session is invalid, reopen a fresh session to persist `failed`, `error_message`, and the last durable checkpoint.
- Avoid full worker-process crash for deterministic data errors.

### Performance fixes

5. Add durable chunk checkpoints

- Persist `processed_identities`, `total_identities`, current chunk index, and retry count after each successful chunk commit.
- Resume from the next unfinished chunk instead of replaying from 0/937.

6. Bound retries for deterministic data errors

- Integrity violations like `unique_identity_membership` are unlikely to be transient.
- Mark such jobs `failed` after one attempt or a very small retry budget.
- Reserve exponential backoff retries for connection failures, deadlocks, or transient infrastructure faults.

7. Reduce per-identity logging during large jobs

- Keep chunk summaries and sampled identity decisions.
- Gate verbose per-identity logging behind a debug flag or tenant-specific tracing mode.
- Preserve enough evidence for diagnosis without writing hundreds of thousands of lines.

8. Avoid MV refresh on every crash-restart cycle

- Persist or debounce MV refresh timing across restarts.
- Or skip refresh when immediately retrying the same failed clustering job.

### UX and observability fixes

9. Surface pipeline truth, not just the original scan

- The workbench should explicitly distinguish:
  - scan phase
  - clustering phase
  - retrying/failing phase
- If scan is done and follow-up clustering exists, the UI should say so even when the follow-up row is unhealthy.

10. Expose retry count and last successful checkpoint

- Suggested fields:
  - `retry_count`
  - `last_successful_processed_identities`
  - `current_stage`
  - `current_chunk_size`
  - `last_error_at`
  - `last_error_code`

11. Show clustering progress in identities, not images

- The existing UI already mixes scan and cluster concepts.
- Once the pipeline hands off, the visible counter should say `Clustering 750/937 identities…`, not imply image scanning is still happening.

12. Measure latency as a distribution

- Track p50/p95/p99 for:
  - scan item processing
  - chunk clustering time
  - DB flush/commit time
  - MV refresh time
  - job retry interval
- The current average runtime is misleading because the pathological tail dominates real user experience.

## Suggested Investigation Order

1. Confirm the duplicate-assignment path with a focused regression test

- Reproduce a chunk where identities are both `suggested` and then selected by HAC.
- Assert only one membership write is attempted per identity.

2. Instrument the planner boundary

- Before each `persist_new_cluster()`, log the identity IDs being inserted and whether they are already assigned in-session or earlier in the chunk.

3. Make failure durable before optimizing speed

- First ensure a deterministic integrity error marks the job failed once.
- Then add checkpointed resume.
- Then reduce logging and MV refresh overhead.

4. Fix the UI handoff once the backend can report truthful state

- Otherwise the UI will still be guessing around rolled-back rows.

## Confidence Notes

Very high confidence:

- scan finished successfully
- clustering job is replaying from scratch
- replay loop is the main reason runtime exploded
- integrity error occurs at/after HAC on the final 14 noise identities
- durable clustering state is not being preserved

High confidence:

- duplicate assignment is happening within one transaction, not against preexisting committed `identity_members`
- overlapping fallback stages are the immediate source of the duplicate insert

Medium-high confidence:

- frontend phase handoff contributes to the frozen feel
- immediate MV refresh after every restart adds measurable but secondary overhead

## Addendum: N+1 Query Analysis and Baseline Clustering Latency (added 2026-03-23)

Even after the retry loop is fixed, single-run clustering latency has a structural N+1 problem. The numbers below describe one clean run without crashes.

### Per-assignment DB round-trips

Each `persist_assignment()` (triggered per ACCEPT decision) executes:

| Step                     | Method                                  | Queries |
| ------------------------ | --------------------------------------- | ------- |
| Fetch cluster            | `get_by_id(cluster_id)`                 | 1       |
| Insert member            | `add_member()`                          | 1       |
| Check reps               | `get_all_representatives()`             | 1       |
| Recompute centroid       | `get_all_representatives()` (duplicate) | 1       |
| Update cluster           | `update(cluster)`                       | 1       |
| Read curriculum_t        | `get_curriculum_t()`                    | 1       |
| Write curriculum_t       | `set_curriculum_t()`                    | 1       |
| (conditional) Remove rep | `remove_representative()`               | 0-1     |
| (conditional) Add rep    | `create_and_add_representative()`       | 0-1     |

Minimum: **7 queries per identity assignment**. With representative work: 9-10.

### Per-chunk overhead

`prepare_cluster_caches()` is called at the top of every chunk iteration. It runs `get_by_tenant(tenant_id, limit=1000)` and iterates all clusters to extract representatives and centroids. For 500 identities the adaptive chunker produces ~20 chunks, so this runs ~20 times against a growing cluster set; the same data is re-fetched from the DB each time.

### Projected query count for 937 identities (one clean run)

| Component                                          | Count       |
| -------------------------------------------------- | ----------- |
| `prepare_cluster_caches()` per chunk               | ~20         |
| Progress flush per chunk                           | ~20         |
| ACCEPT assignments (~70%: ~656 identities x 8 avg) | ~5,250      |
| SUGGEST assignments (~20%: ~187 identities x ~2)   | ~375        |
| `persist_new_cluster()` bulk inserts               | ~50         |
| Curriculum / centroid maintenance                  | ~700        |
| **Estimated total**                                | **~6,400+** |

At 5-10ms per async DB round-trip on localhost, one clean clustering run should take 30-60s for 937 identities. Not hours; but also not "a few seconds" as the user remembers. The previous fast experience was likely with a much smaller identity count or before the representative/centroid maintenance paths were added.

### Relevant patterns from DDIA and Latency literature

**DDIA (Kleppmann), Ch. 2-3: Data Models and Storage Engines**
The N+1 pattern here is a textbook example of the "fan-out reads" problem. Each identity assignment triggers separately-keyed lookups rather than batch operations. DDIA's discussion of materialized views is relevant: the representative and centroid data that `prepare_cluster_caches()` recomputes each chunk should be treated as a derived dataset that can be incrementally maintained rather than requeried.

**DDIA, Ch. 7: Transactions**
The single broad transaction spanning all 937 identities means one late integrity error rolls back all work. DDIA advocates for smaller transaction scopes with explicit savepoints when the failure domain is narrow and the cost of replay is high. The current architecture is the worst case: broad transaction + deterministic late failure = infinite replay.

**DDIA, Ch. 11: Stream Processing / Idempotence**
The clustering write path is not idempotent. `add_member()` and `bulk_add_members()` both use raw inserts. The safe `add_member_if_not_exists()` with ON CONFLICT DO NOTHING already exists but is unused in the hot path. Making persistence idempotent is a prerequisite for safe retry (DDIA's "exactly-once semantics via idempotent operations").

**Latency (Enberg), Ch. 1-3: Measuring and Reducing Latency**
The retry loop is a textbook latency amplification pattern. Little's Law (L = lambda \* W) explains why: with each retry adding another full 937-identity traversal to the queue, the effective arrival rate grows while service time stays constant, pushing wait time toward infinity. Enberg's guidance on backpressure is directly applicable: the system should stop retrying a permanently failing job rather than requeuing it with exponential backoff.

**Latency (Enberg), Ch. 5-6: I/O and Database Latency**
The 7-10 DB round-trips per assignment illustrate Enberg's "chatty protocol" anti-pattern. Each round-trip adds network + kernel scheduling + DB parse/plan/execute overhead. Batching writes (e.g., collecting all member inserts for a chunk, then issuing one `INSERT ... VALUES (...), (...), ...`) would amortize per-query overhead. The duplicate `get_all_representatives()` call (once in `_should_add_representative`, again in `recompute_centroid`) is a pure waste.

### Improvement options (addendum)

These supplement the correctness and UX fixes already listed above.

**A. Batch membership writes per chunk**
Collect all ACCEPT decisions for a chunk, then issue a single `INSERT ... ON CONFLICT DO NOTHING` with all membership rows. This converts ~N\*7 queries into ~3 queries per chunk (one bulk insert, one bulk cluster update, one bulk curriculum update).

**B. Cache cluster data in memory across chunks**
Load `prepare_cluster_caches()` once at job start. After each chunk, incrementally update the in-memory cache with newly created clusters and updated centroids/representatives. Eliminates ~20 redundant `get_by_tenant` queries.

**C. Deduplicate `get_all_representatives()` inside `persist_assignment`**
Pass the representative list from `_should_add_representative()` into `recompute_centroid()` instead of re-fetching. Saves one DB query per ACCEPT.

**D. Chunk-level savepoints or commits**
Wrap each chunk in a savepoint. If one chunk fails, roll back to the previous savepoint and mark the job partially complete. Resume from the last successful chunk on retry.

**E. Atomic curriculum_t update**
Replace the read-modify-write (`get_curriculum_t` + `set_curriculum_t`) with a single `UPDATE ... SET curriculum_t = 0.99 * :similarity + 0.01 * COALESCE(curriculum_t, 0)` statement.

## Recommended Next Deliverables

1. A backend fix PR focused only on:

- removing duplicate fallback assignment (suggested identities excluded from HAC candidate set)
- making clustering failure durable (fresh session to persist `failed` status after integrity error)
- preventing full-job replay after deterministic integrity errors (mark failed, not pending)
- switching `add_member()` / `bulk_add_members()` to ON CONFLICT DO NOTHING

2. A smaller UX PR focused only on:

- explicit clustering phase state in the workbench
- retry/failure messaging
- identity-based progress labels (`Clustering 750/937 identities`)

3. A follow-up performance PR after the correctness fix lands:

- batch membership writes per chunk
- in-memory cluster cache across chunks
- deduplicate `get_all_representatives()` calls
- chunk-level savepoints
- atomic curriculum_t update

4. A follow-up performance report after the correctness fix lands, because current timing is dominated by failure replay and is not a clean baseline for algorithm tuning.
