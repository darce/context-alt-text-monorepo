# Recognition Clustering Crash Investigation

Date: 2026-03-24

Scope:

- Investigate the latest worker crash associated with the user-visible failure:
  - `Job 9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7: failed`
  - `Phase: failed`
  - `Processed 5/937 images`
- Use `apps/prototype-description-service/logs/scan_worker.log` as the primary evidence source.
- Identify the immediate failure, likely root cause, and concrete remediation options.

## Executive Summary

The displayed failed job ID, `9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7`, is the completed scan/analyze job, not the job that actually crashed. The log shows that scan job finished successfully at `2026-03-24 15:34:45`, then auto-created a follow-up clustering job `6f0e3e6a-413a-4a4d-876c-b4c5699e6c2a`.

That clustering job completed chunk 1 successfully (`processed=5/937`), committed the chunk, then failed at the start of chunk 2 with:

- `asyncpg.exceptions.InsufficientPrivilegeError`
- `new row violates row-level security policy for table "recognition_events"`

The failure was not caused by duplicate memberships, HAC replay, or clustering math. It was caused by observability event persistence. More specifically, the worker enables RLS bypass using `SET LOCAL app.bypass_rls = 'true'`, but chunk commits clear `SET LOCAL` state. After the first chunk commit, GraphDiscovery emitted a pending `graph_run` event into the session. A later query in gate evaluation triggered an autoflush, which attempted to insert that event without the RLS bypass still in effect, and Postgres rejected it.

The most likely root cause is therefore:

1. worker starts clustering with transaction-local RLS bypass enabled
2. chunk 1 commits successfully
3. that commit clears the transaction-local bypass flag
4. chunk 2 emits a `recognition_events` row through the shared session
5. a later query triggers autoflush
6. the event insert hits RLS without bypass and aborts the clustering job

Confidence: high

## Incident Timeline

All timestamps below come from `apps/prototype-description-service/logs/scan_worker.log`.

### 1. The scan job completed normally

- `2026-03-24 15:34:45`
- Log line: `Scan job 9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7 completed, auto-creating clustering job`

This means the user-visible failed job ID is the pipeline entrypoint, not the actual crashing worker job.

### 2. The follow-up clustering job began immediately

- clustering job ID: `6f0e3e6a-413a-4a4d-876c-b4c5699e6c2a`
- tenant ID: `cc42f496-c7e1-5631-b3b5-cfa270c763f8`
- total identities: `937`

The job started at:

- `2026-03-24 15:34:45`
- `batch_start`
- then `chunk_processing ... processed=0/937 chunk_size=5`

### 3. Chunk 1 completed successfully

The first chunk produced 5 singleton new-cluster assignments and then logged:

- `chunk_stats job_id=6f0e3e6a... processed=5/937 size=5 accept=0 suggest=0 reject=0 new_clusters=5 ...`

This matters because it proves:

- the job made durable progress before failing
- the `5/937` progress value in the UI corresponds to the first clustering chunk, not scan image progress

### 4. Chunk 2 failed before persistence of its decisions

The next chunk started immediately:

- `chunk_processing job_id=6f0e3e6a... processed=5/937 chunk_size=5`

Graph discovery then ran and emitted:

- `Completed: algorithm=hdbscan clusters=3 noise=2 candidates=0 new_clusters=4`

Right after `Total candidates to evaluate through gate: 1`, the worker crashed.

### 5. The actual database error was an RLS violation on `recognition_events`

The log shows:

- `asyncpg.exceptions.InsufficientPrivilegeError: new row violates row-level security policy for table "recognition_events"`

The failing SQL was:

```sql
INSERT INTO recognition_events (...)
VALUES (...)
RETURNING recognition_events.timestamp
```

The event payload indicates the row was a `graph_run` observability event.

## What Failed Technically

### Immediate failure point

The stack trace shows the clustering job failed while evaluating a candidate in chunk 2:

- `decision_handler.evaluate_only()`
- `gate.evaluate()`
- `block_repository.is_blocked()`

That query triggered SQLAlchemy autoflush. The autoflush attempted to persist a previously-added `RecognitionEvent` ORM row and failed under RLS.

### Source of the pending event row

`GraphDiscovery.discover()` emits a `graph_run` event through the bound `RecognitionRunContext`:

- `recognition/application/discovery/graph/discovery.py`
- `_emit_graph_run_event(...)`
- `self._run_context.add_event(event_type="graph_run", payload=payload)`

`RecognitionRunContext.add_event()` only adds the ORM row to the shared session; it does not flush immediately:

- `recognition/observability/recognition_runs.py`
- `self.session.add(event)`

That means the event can sit pending in the session until some unrelated later query triggers autoflush.

### Why RLS bypass was lost

The worker enables bypass at the top of the loop using:

```python
await session.execute(text("SET LOCAL app.bypass_rls = 'true'"))
```

from `db/tenant_context.py`.

`SET LOCAL` is transaction-scoped. The clustering worker now commits after each chunk. So after chunk 1:

- the commit succeeds
- the transaction ends
- the `SET LOCAL app.bypass_rls = 'true'` setting is cleared

The same session is then reused for chunk 2 without re-establishing bypass. That makes later writes to RLS-protected tables fail.

## Root Cause Hypothesis

### Primary root cause

Chunk-level commits were introduced, but the worker still relies on a transaction-local RLS bypass flag that is only set once before clustering starts.

Because the bypass is configured with `SET LOCAL`, every chunk commit clears it. Observability event writes that occur after the first commit therefore run without bypass and violate the `recognition_events` RLS policy.

Confidence: high

### Trigger sequence

1. worker enters clustering session and calls `enable_rls_bypass()`
2. chunk 1 commits
3. session continues into chunk 2
4. GraphDiscovery adds a `graph_run` event to the session
5. gate evaluation performs a query
6. SQLAlchemy autoflush tries to insert the pending event
7. insert runs without bypass and hits RLS
8. clustering job is marked failed permanently on attempt 1

Confidence: high

## Why the UI Looked Confusing

The failure text the user saw was:

- `Job 9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7: failed`
- `Processed 5/937 images`

That is misleading in two ways:

1. `9f88ebf6-93b8-4ce2-8cc9-a7f1c66bd2c7` is the finished scan job, while the actual failing row is clustering job `6f0e3e6a-413a-4a4d-876c-b4c5699e6c2a`.
2. `5/937` is clustering identity progress from chunk 1, not image scan progress. The scan itself had already completed.

So the visible state is pipeline-correct in spirit, but still confusing in presentation because it associates the failure with the top-level analyze job ID and uses an image-oriented label for identity-oriented progress.

## Impact

- No evidence here of replay amplification or repeated retries; the job failed once and was classified as deterministic.
- The job still did not complete, so the user-visible pipeline failed after scan completion.
- Observability itself became the failure source, which means diagnostic instrumentation is now on the critical path of clustering success.

## Recommended Fixes

### 1. Re-establish RLS context after every chunk commit

Any session that uses chunk commits must reapply tenant/bypass context after each commit before continuing work.

Likely options:

- call `enable_rls_bypass(session)` again after each chunk commit
- or replace transaction-local `SET LOCAL` usage with a session-level strategy that is explicitly reset on connection return

### 2. Keep observability writes out of the critical clustering session

Safer alternatives:

- buffer `recognition_events` and persist them in a separate fresh session
- or emit them best-effort so observability failures cannot fail the clustering job

This is especially important because `RecognitionRunContext.add_event()` currently adds rows to the same ORM session used for clustering writes.

### 3. Prevent autoflush surprises around read queries

The trace itself points to one mitigation:

- use `session.no_autoflush` around gate/block lookups if there are known pending observability rows

This would not fix the missing bypass on its own, but it would make the failure timing more predictable.

### 4. Improve pipeline error presentation

The UI should distinguish:

- pipeline/analyze job ID
- active clustering follow-up job ID
- identity-based clustering progress

The current `Processed 5/937 images` wording obscures that scan had already finished and clustering failed afterward.

## Concrete Follow-Up Checks

1. Reproduce with observability enabled and chunk commits active.
2. Confirm whether reapplying `enable_rls_bypass(session)` immediately after each chunk commit eliminates the failure.
3. Add a regression test covering:
   - chunk 1 commit
   - chunk 2 graph-run event emission
   - later gate query/autoflush
   - successful continuation without `recognition_events` RLS failure
4. Decide whether observability event persistence should ever be allowed to fail the clustering pipeline.

## Key Evidence

- Scan completion and clustering handoff:
  - `scan_worker.log`, lines around `1511-1512`
- Chunk 1 success:
  - `scan_worker.log`, chunk stats at `processed=5/937`
- Actual exception:
  - `scan_worker.log`, lines around `1553-1700`
- Transaction-local bypass:
  - `db/tenant_context.py`, `enable_rls_bypass()`
- Chunk commit boundary:
  - `recognition/application/orchestration/clustering/orchestrator.py`
- Event emission:
  - `recognition/application/discovery/graph/discovery.py`
  - `recognition/observability/recognition_runs.py`

## Bottom Line

This crash was caused by an interaction between:

- chunk-level commits,
- transaction-local RLS bypass,
- shared-session observability event writes,
- and SQLAlchemy autoflush.

The clustering pipeline itself made valid progress through the first chunk. The second chunk failed because a `graph_run` observability insert lost its RLS bypass after the previous chunk commit.
