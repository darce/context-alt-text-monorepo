# Retry/Attempt-Level Observability

## Problem

Once E15-2b lands, every persisted job row carries a `correlation_id` and every worker log line inherits it. Retries reuse the original `correlation_id` by design — there is no per-attempt sub-identifier. When a handler is flaky (transient DB contention, upstream 5xx, claim-lease expiry), an operator grepping logs by correlation sees N attempts interleaved with no way to tell attempt 1 from attempt 3 beyond timestamps. Root-cause analysis of retry storms is guesswork.

## Impact

- Flaky-handler triage requires manual timestamp reconstruction to separate attempts
- No way to query "jobs that needed 3+ attempts to succeed" from the DB or log stream
- Metrics dashboards (scoped in [correlation-dashboards.md](./correlation-dashboards.md)) cannot produce a retry-count distribution
- Post-mortem narratives must hand-wave over "the job was retried a few times" instead of citing exact attempt counts

## Prerequisites

- **E15-2b must land first.** This task extends the correlation contract; it does not replace it. Starting before E15-2b persists `correlation_id` on job rows produces incompatible schema.

## Solutions (ordered by recommendation)

### 1. `attempt` integer column + log field (recommended)

Add a nullable `attempt INT` column to every persisted job/queue surface touched by E15-2b. The enqueue path initializes it to `1`; the claim path increments it when a stale lease is reclaimed. Worker handlers read it off the row and push it into the logging contextvar alongside `correlation_id`, so every log line carries both.

```python
# in recognition/worker/handlers/scan.py
with correlation_context(job.correlation_id, attempt=job.attempt):
    await handler(job)
```

**Pros**: Queryable in SQL (`SELECT correlation_id, MAX(attempt) ... WHERE attempt > 1`), minimal schema footprint, composes cleanly with `correlation_id` in log records.
**Cons**: Every in-scope table needs the column (same set E15-2b enumerated). Claim path becomes responsible for the atomic increment.

### 2. Composed log-only attempt identifier

Do not persist on rows. Worker handlers compute `attempt_id = f"{correlation_id}#{attempt}"` from an in-process counter keyed by `correlation_id`, emitted on every log line. No schema change.

**Pros**: Zero schema footprint. Easy to implement.
**Cons**: Counter is in-process — restarting the worker mid-retry resets it. Cannot SQL-query for "jobs retried N times". Defeats the DDIA end-to-end framing that motivated E15-2b (correlation crosses process boundaries as persisted payload, not ephemeral state).

### 3. Composed persisted identifier (`attempt_id` column)

Single `attempt_id VARCHAR` column storing `{correlation_id}#{attempt}`. Redundant with E15-2b's `correlation_id` column; violates sr-007 (single canonical source) by splitting the correlation field into two places.

**Pros**: Single column.
**Cons**: Duplicates correlation data. Parsing `attempt_id` to recover attempt number is fragile. Worst of both worlds.

## Not-Doing

- **Dead-letter queues** — separate concern with its own schema and retry-policy implications
- **Retry policy changes** — no change to max-attempts, backoff, or jitter; this task only observes what retry already does
- **OTel span hierarchy** — per-attempt span creation is a future distributed-tracing task if OTel ever lands
- **Historical backfill** — rows existing before this task has no `attempt` value; leave NULL, do not backfill

## Decision

Pending. Recommend solution 1 (`attempt` column + log field) once E15-2b has merged to `main` and the enumeration of in-scope tables is stable.

## Open Questions

1. Does the claim path already atomically increment an `attempts`-like field for lease reclamation? If so, this task is mostly a logging wiring change, not a schema change.
2. Should `attempt=1` be logged, or should the log field only appear when `attempt > 1`? Always-logging is simpler; conditional-logging cuts noise on the happy path.
3. Are there workers outside the scan/clustering/retention set that should be in scope (e.g. ad-hoc scripts in `apps/prototype-description-service/scripts/` that claim jobs)?
