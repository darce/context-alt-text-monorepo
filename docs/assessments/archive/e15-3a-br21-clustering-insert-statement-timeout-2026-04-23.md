# Assessment: BR-21 — `identity_clustering_jobs` INSERT canceled by `statement_timeout=10s`

> **Metadata**
>
> - **Date**: 2026-04-23
> - **Task**: [E15-3a](../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md) — finding `E15-3a-BR-21`
> - **Scope**: `apps/prototype-description-service` — async session lifecycle, `POST /recognition/clustering/jobs`, `SqlAlchemyJobRepository.save()`
> - **Status**: Draft; fix plan below informs the Slice 2 unblock.
> - **Related prior work**: [`infailed-sql-transaction-investigation-2026-04-09.md`](./infailed-sql-transaction-investigation-2026-04-09.md) — same class of incident (session lifecycle / pool poisoning), earlier surface.
>
> **Purpose.** Ingest the refactoring / stability / asyncio literature under `literature/extracted/refactoring/` and return a fix, with references, for the Slice 2 failure where `INSERT INTO identity_clustering_jobs` is canceled at exactly 10,014 ms per attempt against a near-empty table. The previous 2026-04-09 investigation closed on session-lifecycle flattening and introduced `statement_timeout=10s`. BR-21 matches the *failure class* the literature predicts: the timeout now fires correctly, but the call site still lacks a fail-fast / circuit-breaker / pre-flight boundary, so a single upstream lock-holder can cascade into three identical 10 s stalls and a user-visible "signal timed out" while the plugin UI falsely reports "Scan complete / No suggestions to review." The exact blocker still requires runtime confirmation via `pg_locks` / `pg_stat_activity`.

---

## 1. Observed symptoms

Captured during operator roundtrip on LocalWP → `api.altcontext.com`, OCI stdout logs (correlation IDs elided):

1. `POST /recognition/analyze` → `202 Accepted`, **~15 ms**, 10 media queued. Path and pool are healthy.
2. `POST /recognition/clustering/jobs` → `500`, **10,014 ms**, `asyncpg.exceptions.QueryCanceledError: canceling statement due to statement timeout`.
3. Retries (2×) repeat at **10,014 ms** each.
4. Plugin UI reports "Scan complete / No suggestions to review" because the `/analyze` 202 succeeded — the clustering-jobs failure is invisible to the browser.
5. Session-dependency telemetry remains fast right up to the failing write. For the same request window, auth's `get_optional_session` probe completes in **~1.5-4.7 ms**, tenant-context setup stays around **~0.5-1.8 ms**, and the clustering route's `get_session` only balloons at the point of the write path (`total_ms≈10,012-10,015`).
6. Each failed clustering retry uses a different `conn_id` (`0xe941e9c5c860`, `0xe941e9d665a0`, `0xe941e9970c50` in the sample), which argues against a single bad pooled connection being handed out repeatedly. It is more consistent with an external blocker that healthy connections all encounter once they reach the same SQL boundary.

The cancelled statement in the traceback is the `INSERT INTO identity_clustering_jobs` emitted by `await self._session.flush()` inside `SqlAlchemyJobRepository.save()` (`recognition/infrastructure/repositories/job_repository.py:61`). The table is near-empty. Postgres `statement_timeout` is configured at 10 s (`db/session.py` log banner at startup).

One log-line subtlety matters for interpretation: the request opens **two** DB dependencies. `require_auth()` depends on `get_optional_session`, while the route itself depends on `get_session()`. When the route later raises on the clustering INSERT, FastAPI unwinds both generators; `get_optional_session` therefore logs the downstream exception during teardown even though the failing INSERT was executed on the route/session path, not on the auth session.

## 2. Call-site and transaction boundary

The router handler acquires a row-level lock on the tenants row **before** the INSERT (`recognition/interface_adapters/http/routers/clusters.py:209`):

```python
await session.execute(
    select(Tenant.id).where(Tenant.id == request.tenant_id).with_for_update()
)
existing_job = await job_service.get_active_clustering_job_for_tenant(request.tenant_id)
if existing_job is not None:
    return _job_to_clustering_response(existing_job)
job = await job_service.create_job(JobType.CLUSTERING, tenant_id=request.tenant_id)  # → flush() INSERT
```

The session comes from the FastAPI dependency `get_session()` in `db/session.py:62`, which commits on success and rolls back on exception. The `SELECT ... FOR UPDATE` runs inside the session's implicit (autobegin) transaction; the subsequent `INSERT` is emitted in the **same** transaction by `session.flush()`.

Two consequences matter:

- The `SELECT ... FOR UPDATE` on `tenants` is the only place in this handler where the request explicitly queues on a lock held by another session. A zombie transaction holding any conflicting lock on that row (an abandoned migration, an `idle in transaction` session from a prior crashed request, an advisory lock) would cause subsequent work in the same transaction to stall up to `statement_timeout`. Because the traceback points at the `INSERT`, the accumulated wait may have occurred on the lock acquisition earlier in the transaction or on the `INSERT` itself; `pg_locks` / `pg_stat_activity` are required to disambiguate.
- The 10 s cliff, **repeatedly identical** across three attempts, is the stability-library signature of a blocked-dependency wait, not of slow I/O or data volume.

## 3. Literature crosswalk (direct support + bounded inference)

All line numbers below refer to the plain-text extractions under `literature/extracted/refactoring/`. The quotations support the failure class and the resilience direction; where this assessment infers the service's exact mechanism, that inference is labeled as such rather than treated as literature-proven fact.

### 3.1 Pool-level: a leaked / held DB transaction exhausts the pool and converts fast calls into slow failures

> "In the previous offending code, if closing the statement throws an exception, then the connection does not get closed, resulting in a resource leak. After forty of these calls, the resource pool is exhausted, and all future calls will block at `connectionPool.getConnection()`. […] The entire globe-spanning, multibillion dollar airline with its hundreds of aircraft and tens of thousands of employees was grounded by one programmer's rookie error: a single uncaught SQLException."
> — Nygard, *Release It!* §2, pp. ~1263-1270.

> "Because the pool was configured to block requesting threads when no resources were available, it eventually tied up all request-handling threads. […] The pool could have been configured to create more connections if it was exhausted. It could also have been configured to block callers for a limited time, instead of blocking forever when all connections were checked out. Either of these would have stopped the crack from propagating."
> — Nygard, *Release It!* §4.1 Cracks Propagate, pp. ~1482-1487.

> "Application failures nearly always relate to Blocked Threads in one way or another, including the ever-popular 'gradual slowdown' and 'hung server.' […] **Scrutinize resource pools** — Like Cascading Failures, the Blocked Threads antipattern usually happens around resource pools, particularly database connection pools. **A deadlock in the database can cause connections to be lost forever, and so can incorrect exception handling.**"
> — Nygard, *Release It!* §4.5 Blocked Threads, pp. ~3209-3446.

**Applicability.** This is the exact mechanism BR-21 is on track to reproduce at scale. One sick request is consuming one pool slot for 10 s × 3 retries = 30 s per attempt. Under concurrency the pool exhausts, and every unrelated endpoint (including `/health/detailed`) starts to queue on `pool.getConnection()`.

### 3.2 Timeout-level: the existing timeout is working; raising it is the wrong move

> "Well-placed timeouts provide fault isolation; a problem in some other system, subsystem, or device does not have to become your problem. […] It is essential that any resource pool that blocks threads must have a timeout to ensure threads are eventually unblocked whether resources become available or not."
> — Nygard, *Release It!* §5.1 Use Timeouts, pp. ~4345-4354.

> "Timeouts are often observed together with retries. […] If the operation failed because of any significant problem, it is likely to fail again if retried immediately. […] Within the walls of a data center, however, the failure is probably because of something wrong with the other end of a connection. Thus, fast retries are very likely to fail again."
> — Nygard, *Release It!* §5.1 Use Timeouts, pp. ~4399-4407.

**Applicability.** The `statement_timeout=10s` we added in the 2026-04-09 remediation **is** the fault-isolation boundary. The three identical 10 s retries are the Nygard-predicted failure pattern for an absent circuit-breaker / fail-fast above the timeout. Do not widen the timeout.

### 3.3 Circuit breaker + fail-fast: the missing layer

> "Timeouts have natural synergy with circuit breakers. A circuit breaker can tabulate timeouts, tripping to the 'off' state if too many occur. The Timeouts and Fail Fast patterns both address latency problems. […] **Apply to Integration Points, Blocked Threads, and Slow Responses — The Timeouts pattern prevents calls to Integration Points from becoming Blocked Threads. Thus, they avert Cascading Failures.**"
> — Nygard, *Release It!* §5.1 Remember This, pp. ~4433-4449.

> "If the system can determine in advance that it will fail at an operation, it's always better to fail fast. […] In any service-oriented architecture, the application can tell from the service requested roughly what database connections and external integration points will be needed. The service can very quickly check out the connections it will need and verify the state of the circuit breakers around the integration points. […] If any of the resources are not available, it can fail immediately, rather than getting partway through the work."
> — Nygard, *Release It!* §5.5 Fail Fast, pp. ~5013-5039.

**Applicability.** BR-21 currently returns `500` *after* 10 s of blocked work on a lock. That is the "slow failure response" Nygard calls the worst possible outcome. The fix is an admission-side check that aborts the request *before* entering the transaction when the DB is not in a writable state for this tenant.

### 3.4 Async Python: session ownership and cancellation discipline

> "Support for coroutines in context managers turns out to be exceptionally convenient. This makes sense, because many situations require network resources — say, connections — to be opened and closed within a well-defined scope."
> — Hattingh, *Using Asyncio in Python*, pp. ~2250-2275.

> "When a coroutine receives a cancellation signal, that is a clear directive to do only whatever cleanup is necessary. […] `CancelledError` is raised inside the task-wrapped coroutine when tasks are cancelled."
> — Hattingh, *Using Asyncio in Python*, pp. ~1740-1795.

> "`async def connect(self) -> Pool: self.pool = await asyncpg.create_pool(…)` / `async def disconnect(self): releases = [self.pool.release(conn) for conn in self.listeners]; await asyncio.gather(*releases); await self.pool.close()` / `async def server_command(self, cmd): conn = await asyncpg.connect(…); await conn.execute(cmd); await conn.close()`"
> — Hattingh, *Using Asyncio in Python*, pp. ~5122-5147.

**Applicability.** The code path still relies on dependency-owned session cleanup after the endpoint returns, so Hattingh is directly relevant on two points: resource ownership should live in a well-defined async scope, and cancellation paths should do only the cleanup required to leave the resource consistent. What the book does **not** prove by itself is this assessment's strongest causal claim: that this service actually returned a pooled connection before rollback completed and thereby created an `idle in transaction` blocker. Treat that as a plausible mechanism to investigate, not as literature-confirmed fact.

### 3.5 Database-level: lock contention can persist even when the table is empty

> "The approach of requiring read locks does not work well in practice, because one long-running write transaction can force many read-only transactions to wait until the long-running transaction has completed. This harms the response time of read-only transactions and is bad for operability: a slowdown in one part of an application can have a knock-on effect in a completely different part of the application, due to waiting for locks."
> — Kleppmann, *Designing Data-Intensive Applications* §Weak Isolation Levels, pp. ~9629-9634.

> "A long-running transaction may continue using a snapshot for a long time, continuing to read values that (from other transactions' point of view) have long been overwritten or deleted. By never updating values in place but instead creating a new version every time a value is changed, the database can provide a consistent snapshot while incurring only a small overhead."
> — Kleppmann, *DDIA* §Snapshot Isolation, pp. ~9806-9810.

**Applicability.** A near-empty `identity_clustering_jobs` table does not imply "no locks." Kleppmann's point is narrower than the draft originally implied: long-lived transactions can create knock-on waits that are operationally visible far away from the originating work. For BR-21, that supports the claim that table emptiness does not rule out an external lock-holder, but it does not identify which specific lock or backend is responsible.

### 3.6 Latency: the pool is the backpressure boundary; convoying is the user-visible symptom

> "Convoying is a phenomenon in concurrent systems that occurs when a thread holding a lock experiences a delay, causing other threads that require the same lock to queue up behind it. […] High lock contention, long critical sections, and bad thread scheduling exacerbate convoying."
> — Enberg, *Latency* §8.2.3 Convoying, pp. ~3323-3329.

> "Connection pooling is a technique that hides this latency by maintaining a set of pre-established connections that the application can reuse. […] Connection pooling hides connection establishment latency and can help limit resource usage by maintaining a fixed-size connection pool. […] The application must manage the number of concurrent queries it sends to avoid overwhelming the database. […] Uncontrolled async execution can overwhelm system resources and increase latency because clients can keep sending more requests than the server can handle. Backpressure is essential for managing concurrency to maintain a stable system with predictable performance."
> — Enberg, *Latency* §10.4.3 and §10.5, pp. ~4498-4504.

**Applicability.** Synthesis: the pool is the backpressure / bulkhead boundary; a held lock converts that boundary into a convoy that stalls the whole service. The fix must preserve the boundary (`statement_timeout` stays) and add an admission check that refuses to enter the convoy.

## 4. Root-cause hypothesis ranking

Ranked by posterior likelihood against the observed evidence (3 × 10,014 ms identical cancellations on a simple INSERT, empty table, fast 202 on the preceding call). The literature narrows the likely failure class to lock contention / blocked threads / missing fail-fast, but it does **not** by itself identify the blocking backend; the playbook in §6 is still required to confirm H1 vs H2.

| # | Hypothesis | Evidence for | Evidence against | Verdict |
|---|---|---|---|---|
| H1 | A prior request left an asyncpg connection `idle in transaction` holding the `tenants` row lock (from `SELECT ... FOR UPDATE` at `clusters.py:209`); new request's `SELECT ... FOR UPDATE` queues, wait surfaces against the next statement (the INSERT). | Matches the 10,014 ms cliff exactly; matches Nygard §4.5 "a deadlock in the database can cause connections to be lost forever"; the current logs show healthy sessions reaching the same failing boundary on different `conn_id`s, which fits one external blocking backend more than a reused bad checkout. | Requires an earlier aborted request to have reached line 209 and left the blocker behind; still needs `pg_stat_activity` / `pg_locks` confirmation. | **Most likely.** |
| H2 | A stale / abandoned `CREATE INDEX CONCURRENTLY` or `ALTER TABLE` is holding a `ShareUpdateExclusiveLock` / `AccessExclusiveLock` on `identity_clustering_jobs`. | Would produce exactly this timeout on INSERT; consistent with recent deploy churn. | No recent `alembic upgrade head` output in logs suggests this, but does not rule it out. | **Second-most-likely.** |
| H3 | Autovacuum acquired a conflicting lock on the table (e.g. vacuum full was triggered or an aggressive vacuum ran against a near-empty table). | Would produce the timeout. | Autovacuum on a near-empty table is low-probability at this duration and repeatability. | Low. |
| H4 | The asyncpg pool is saturated at the `pool_timeout` level, and the "10,014 ms" is actually the pool-checkout wait, not the INSERT. | Would be suggestive. | The log explicitly names the cancelled statement as the INSERT; the preceding `/analyze` returned 202 in 15 ms from the same pool; auth/session probes stay fast immediately before failure; and each retry gets a different connection ID before hitting the same 10 s wall. | Rejected. |
| H5 | RLS policy scan against a massive dependent table. | Would produce slow INSERT. | `identity_clustering_jobs` is near-empty and RLS policies on it are simple tenant filters. | Low. |

## 5. Recommended fix (layered, literature-aligned)

The fix is **three complementary layers** — not a single change. The 2026-04-09 assessment deliberately deferred the stability-pattern layer; BR-21 is the evidence that deferral is now costing us.

### Layer A — Operator unblock (immediate, same slice)

Unblock the Slice 2 roundtrip *before* any code lands. Run the diagnostic playbook in §6. If H1 or H2 is confirmed, terminate the zombie backend / stale migration. This is fault isolation at the operator boundary, not a code fix.

### Layer B — Admission-side fail-fast (Tier 1, same branch)

Rationale: *Nygard §5.5 Fail Fast.* Convert the slow 500 into a fast 503 when the DB is not in a writable state for clustering. The literature supports failing before or at the lock boundary; the exact probe mechanism below is a local design choice, not a claim derived directly from the books.

- One implementation candidate is a **time-budgeted pre-flight probe** before the `SELECT ... FOR UPDATE`: `SET LOCAL statement_timeout = '500ms'; SELECT 1 FROM pg_locks WHERE relation = 'identity_clustering_jobs'::regclass AND NOT granted LIMIT 1`. If a row is returned, short-circuit with `503 Service Unavailable, Retry-After: 5`, record a `jobs_admission_rejected` metric, and do not enter the transaction. This follows the spirit of Nygard's "verify resources before starting work" pattern, while remaining a service-specific design choice that should be validated against race conditions.
- Alternative lighter form: wrap the `SELECT ... FOR UPDATE` itself with a short local `statement_timeout` override (`SET LOCAL statement_timeout = '1s'`) so the lock wait fails in 1 s instead of 10 s. This keeps the call site simple and converts the 10 s cliff into a 1 s fast-fail. Trade-off: reduces diagnostic richness.

### Layer C — Pool-level bulkhead + circuit breaker (Tier 2, follow-on task)

Rationale: *Nygard §4.5 / §5.1 / §5.2 / §5.3.* The stability-library patterns the 2026-04-09 assessment deferred.

- **Circuit breaker** around the clustering-jobs write path: after N (e.g. 3) consecutive `QueryCanceledError`s within a 30 s window, open the breaker for 30 s. Every request in that window returns `503` in < 1 ms. This directly implements Nygard's §5.1 synergy: "a circuit breaker can tabulate timeouts, tripping to the 'off' state if too many occur."
- **Bulkhead** between analyze (fast, high-volume) and clustering-jobs (lock-prone) so the latter cannot exhaust the business pool and poison `/analyze`. In practice: a second `AsyncEngine` + `async_sessionmaker` dedicated to clustering writes, sized smaller (`pool_size=2, max_overflow=1`), so a stuck clustering INSERT cannot consume more than three pool slots total.
- **Asyncio session discipline.** Audit every `session.flush()` / `session.execute()` path for cancellation safety per Hattingh ch. 3: the session *must* be owned by an `async with` scope whose `__aexit__` guarantees ROLLBACK completes on the asyncpg connection before the connection returns to the pool. If `get_session()`'s current commit-on-return / close-in-finally pattern does not provide that guarantee under cancellation, move the commit into the endpoint body via `async with session.begin():` and have the dependency only yield + close.

### Layer D — Observability (Tier 1, same branch)

- Log the `X-Request-ID` correlation ID **and** the Postgres backend PID (`SELECT pg_backend_pid()`) on every session checkout. That is the two-column join needed to match a canceled client statement to a Postgres `pg_stat_activity` row during post-mortem.
- Emit a metric `clustering_jobs_admission_latency_seconds` histogram bucketed around the `statement_timeout` so the 10 s cliff is visible on the dashboard before it becomes a user complaint.

## 6. Operator diagnostic playbook (H1/H2 disambiguation)

Run from the OCI host in `/opt/acx-backend/prod`:

```bash
# 1. Find blocking backends on identity_clustering_jobs
docker compose -f docker-compose.env.yml exec postgres \
  psql -U acx_app -d acx_prod -c "
    SELECT pid, state, wait_event_type, wait_event, xact_start,
           now() - xact_start AS txn_age,
           now() - query_start AS query_age,
           left(query, 200) AS query
    FROM pg_stat_activity
    WHERE state != 'idle'
       OR state = 'idle in transaction'
    ORDER BY xact_start NULLS LAST;"

# 2. Current locks on identity_clustering_jobs and tenants
docker compose -f docker-compose.env.yml exec postgres \
  psql -U acx_app -d acx_prod -c "
    SELECT locktype, relation::regclass AS rel, mode, granted, pid, virtualtransaction
    FROM pg_locks
    WHERE relation IN (
      'identity_clustering_jobs'::regclass,
      'tenants'::regclass
    )
    ORDER BY granted, rel;"

# 3. In-progress concurrent index / DDL
docker compose -f docker-compose.env.yml exec postgres \
  psql -U acx_app -d acx_prod -c "
    SELECT pid, phase, left(query, 120)
    FROM pg_stat_progress_create_index
    UNION ALL
    SELECT pid, 'ddl-lock', left(query, 120)
    FROM pg_stat_activity
    WHERE query ILIKE 'alter table%' OR query ILIKE 'create index%';"
```

If (1) shows an `idle in transaction` row older than ~30 s, or (2) shows a non-granted lock on `tenants` or `identity_clustering_jobs`, H1/H2 is confirmed. Terminate the offending backend:

```bash
docker compose -f docker-compose.env.yml exec postgres \
  psql -U acx_app -d acx_prod -c "SELECT pg_terminate_backend(<pid>);"
```

If the root cause is a crashed application process, `sudo systemctl restart acx-prod` will recycle all pooled connections and clear any zombie transactions held by that process. Do this *after* capturing the diagnostic evidence, not before.

## 7. Verification & regression plan

- **Reproduction test** (unit, pytest): spin up a Postgres fixture, begin a transaction that does `SELECT ... FROM tenants WHERE id=$1 FOR UPDATE` on the test tenant and does not commit; from a second session, call `SqlAlchemyJobRepository.save()` on a CLUSTERING job and assert it raises within the 1 s bounded retry (Layer B), not 10 s. Guards the specific BR-21 regression.
- **Circuit-breaker test** (Layer C): mock the repository to raise `QueryCanceledError` three times; assert the next call returns `503` in < 10 ms without reaching the DB.
- **Fail-fast admission test** (Layer B): insert a dummy ungranted `pg_locks` row via advisory lock in a fixture; assert `POST /recognition/clustering/jobs` returns `503, Retry-After: 5` in < 600 ms.
- **Observability test** (Layer D): assert the log record for a clustering-jobs call contains both `correlation_id` and `pg_backend_pid`.
- **Re-run Slice 2** in LocalWP after Layer A unblocks the OCI environment and Layer B lands. Expect green roundtrip with a real job row in `identity_clustering_jobs`.

## 8. Non-goals

- Widening `statement_timeout` from 10 s. This was the fix for the *previous* incident class; widening it re-introduces the 2026-04-09 failure mode.
- Removing the `SELECT ... FOR UPDATE` on `tenants`. The idempotent-clustering-job guarantee depends on it; the fix is bounding the lock wait, not removing the lock.
- Switching from asyncpg. asyncpg is correct; the gap is in session ownership discipline and the missing stability layers above it.

## 9. References

- Nygard, *Release It! — Design and Deploy Production-Ready Software*, 2nd ed.
  - §2 (airline pool-exhaustion incident), pp. ~1263-1270
  - §4.1 Cracks Propagate, pp. ~1482-1487
  - §4.3 Cascading Failures, pp. ~2596-2637
  - §4.5 Blocked Threads, pp. ~3209-3446
  - §5.1 Use Timeouts, pp. ~4345-4449
  - §5.5 Fail Fast, pp. ~5013-5039
- Hattingh, *Using Asyncio in Python*
  - Async context managers (§Async Context Managers), pp. ~2250-2275
  - Cancellation semantics, pp. ~1740-1795
  - asyncpg pool lifecycle, pp. ~5122-5147
- Kleppmann, *Designing Data-Intensive Applications*
  - §Weak Isolation Levels — Read Committed, pp. ~9629-9634
  - §Snapshot Isolation, pp. ~9806-9810
- Enberg, *Latency — Reduce Delay in Software Systems*
  - §8.2.3 Convoying, pp. ~3323-3329
  - §10.4.3 Connection pools / §10.5 Backpressure, pp. ~4498-4504

Internal precedents:

- [`infailed-sql-transaction-investigation-2026-04-09.md`](./infailed-sql-transaction-investigation-2026-04-09.md) — prior session-lifecycle incident; landed `statement_timeout=10s`; deferred the stability patterns BR-21 now requires.
- [`infailed-sql-transaction-persistent-after-slr-2026-04-10.md`](./infailed-sql-transaction-persistent-after-slr-2026-04-10.md) — follow-on verification of the 2026-04-09 remediation.
