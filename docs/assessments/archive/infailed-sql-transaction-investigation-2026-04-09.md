# Assessment: InFailedSQLTransactionError in prototype-description-service

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: Claude Opus 4.6
> - **Scope**: `apps/prototype-description-service` — session lifecycle, tenant context, connection pool
> - **Status**: Draft
>
> **Purpose:** This assessment investigates a cascading failure in `POST /recognition/analyze` caused by
> PostgreSQL's `InFailedSQLTransactionError`. It traces the root cause through the session dependency chain,
> identifies five code-level bugs and three missing resilience patterns, and recommends directions for a spec.

---

# Session Lifecycle and Connection Resilience Assessment

> All `POST /recognition/analyze` requests fail with HTTP 501 and `InFailedSQLTransactionError: current
> transaction is aborted, commands ignored until end of transaction block` at `ensure_tenant_exists()`.
> The session dependency's health probe (`SELECT 1`) and tenant context setup (`RESET` + `SET LOCAL`)
> both succeed immediately before the failing query, confirming the problem is in the session lifecycle
> and connection pool management layers, not in PostgreSQL itself. Multiple consecutive requests fail
> identically, indicating pool-wide connection poisoning — a cascading failure pattern.

**Related docs:**

- [E15-7 local sync task plan](../tasks/15.0/E15-7-local-sync-completion-and-audit-closure-task-plan.md) — implicitly depends on `/recognition/analyze` reliability (now merged to main)
- SQLAlchemy 2.x [Session API — autobegin](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.params.autobegin)
- SQLAlchemy 2.x [AsyncSession extensions](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- Hattingh, *Using Asyncio in Python* — async context managers, resource ownership (Ch. 3)
- Nygard, *Release It!* — Cascading Failures (§4.3), Blocked Threads (§4.5), Circuit Breaker (§5.2), Bulkheads (§5.3), Timeouts (§5.1), Fail Fast (§5.5)

## Executive Summary

The `InFailedSQLTransactionError` cascading failure has a primary architectural cause and several contributing factors. The primary cause is a **double session lifecycle**: `deps/session.py` wraps `db/session.py`'s async generator via `async for`, creating two independent commit/rollback layers over the same `AsyncSession`. When the outer layer commits, SQLAlchemy's autobegin starts a new transaction on the next database operation; the inner generator then commits *that* spurious transaction, creating a micro-transaction on every request. If either commit fails transiently, the exception handling paths diverge and the connection may return to the pool in a corrupted state.

Four contributing factors amplify the primary cause: duplicate `set_tenant_context` calls double the SQL round-trips and error surface; blanket `contextlib.suppress(Exception)` in `clear_tenant_context` masks the diagnostic signal needed to distinguish failure modes; the checkout listener uses raw DBAPI cursors that bypass SQLAlchemy's transaction tracking; and no PostgreSQL timeout parameters (`statement_timeout`, `idle_in_transaction_session_timeout`, `transaction_timeout`) are configured to bound the damage when a connection enters a failed state.

Beyond the code bugs, the system lacks four resilience patterns identified in Nygard's stability framework: circuit breaker (stop hammering a poisoned pool), query-level timeouts (bound individual operations), connection pool bulkheading (isolate observability from business queries), and fail-fast behavior (reject requests immediately when the pool is degraded).

**What should happen next:** A spec defining testable changes for the session lifecycle flattening (P0), timeout configuration (P1), and diagnostic logging (P1). Circuit breaker and pool bulkheading are valid directions but carry design uncertainty; they should be Tier 3 / ADR-gated in the spec.

## Findings

### F1. Double Session Lifecycle Management

Three FastAPI session dependencies (`get_session`, `get_optional_session`, `get_observability_session`) wrap the inner `db.session.get_session()` async generator via `async for`, then call `commit()` / `rollback()` on the session themselves. The inner generator *also* calls `commit()` / `rollback()` / `close()` when the `async for` iteration advances past the `yield`. This creates two independent lifecycle managers for the same `AsyncSession`.

Current examples:

- `deps/session.py:51-80` — outer `get_session` casts inner generator, iterates with `async for`, calls `commit()` at line 63, `rollback()` at line 67, `clear_tenant_context` at line 78, then `aclose()` at line 80
- `deps/session.py:88-132` — outer `get_optional_session` same pattern: `commit()` at line 111, `rollback()` at line 118, `clear_tenant_context` at line 130, `aclose()` at line 132
- `db/session.py:37-51` — inner `get_session()`: `yield session` at line 45, `commit()` at line 46, `rollback()` at line 48, `close()` at line 51

**Execution sequence on success (get_optional_session):**

1. Endpoint returns; `get_optional_session` calls `session.commit()` (line 111) — SQLAlchemy flushes, emits COMMIT, releases the Connection back to the pool, expires objects
2. `clear_tenant_context` (line 130) runs `RESET app.current_tenant` + `RESET app.bypass_rls` — these start a **new autobegin transaction** because the prior transaction was committed
3. `session_iter.aclose()` (line 132) advances the inner `get_session()` generator past its `yield` — inner generator calls `session.commit()` (db/session.py:46) — this commits the autobegin transaction started by the RESET commands (**second commit**)
4. Inner generator's `finally` block calls `session.close()` (db/session.py:51)

The second commit is unnecessary and creates a spurious micro-transaction (BEGIN + COMMIT) containing only the RESET commands. On transient failure of either commit, the exception handling paths diverge: the outer layer catches and rolls back, but the inner generator's `except` clause may also fire on the same session, creating ambiguous cleanup ordering.

**Impact:** This is the primary mechanism by which connections return to the pool in a corrupted state. Nygard's cascading failure pattern applies directly: "Cascading failures often result from resource pools that get drained because of a failure in a lower layer" (§4.3). The double lifecycle is the crack that propagates.

The SQLAlchemy async docs explicitly state: "A single [AsyncSession] instance is NOT safe for concurrent task usage." While this isn't concurrent *task* access, two async generators managing the same session's transaction state is the same class of problem — ambiguous ownership.

### F2. Duplicate set_tenant_context Calls

Tenant context (`app.current_tenant`) is set **twice** per `/recognition/analyze` request:

- `deps/session.py:101` — in `get_optional_session` during dependency resolution
- `routers/analyze.py:187` — in `_prepare_tenant_context` during endpoint execution

Current examples:

- `deps/session.py:99-102` — `await set_tenant_context(session, uuid.UUID(str(tenant_id)))` inside `get_optional_session`
- `routers/analyze.py:185-187` — `await ensure_tenant_exists(session, tenant_uuid)` then `await set_tenant_context(session, tenant_uuid)` inside `_prepare_tenant_context`

Each `set_tenant_context` call executes `RESET app.bypass_rls` + `SET LOCAL app.current_tenant`, doubling the SQL round-trips. The endpoint's call also runs `ensure_tenant_exists` *before* `set_tenant_context`, but `set_tenant_context` was already called in the dependency — the endpoint re-does it redundantly.

**Impact:** Each duplicate call adds 2 SQL round-trips (~1ms) and doubles the surface area for the `InFailedSQLTransactionError` recovery path (db/tenant_context.py:55-62) to fire. The recovery path itself (rollback + retry) changes the transaction state, which interacts with F1's double lifecycle.

### F3. Exception Suppression in clear_tenant_context

`clear_tenant_context` swallows all exceptions with `contextlib.suppress(Exception)`, including exceptions that would indicate the session is in a corrupted state.

Current examples:

- `db/tenant_context.py:85-87` — `with contextlib.suppress(Exception): await session.execute(text("RESET app.current_tenant")); await session.execute(text("RESET app.bypass_rls"))`

**Impact:** This masks the diagnostic signal needed to distinguish between root cause hypotheses. When a session is in a failed transaction state at cleanup time, the RESET commands fail with `InFailedSQLTransactionError` — but this is silently swallowed. The investigation had to reason from indirect evidence (timing logs, cascading failure patterns) because the cleanup path destroys the evidence. Per Nygard: "Without information, it is impossible to make deliberate improvements" (§17, Transparency).

### F4. clear_tenant_context Races with Session Close

In all three session dependencies, `clear_tenant_context` runs inside the `try` block of the `async for` body (deps/session.py:78, 130). After it completes, the outer `finally` block calls `session_iter.aclose()`, which advances the inner generator to its `finally` block, which calls `session.close()`. The ordering is currently correct but depends on the `async for` iteration protocol — any refactor that changes this sequencing could cause `clear_tenant_context` to run on a closed session.

Current examples:

- `deps/session.py:77-80` — `clear_tenant_context(session)` at line 78, then `session_iter.aclose()` at line 80 in the outer `finally`
- `deps/session.py:129-132` — same pattern for `get_optional_session`

**Impact:** Low immediate risk, but the fragile ordering is a maintenance hazard. Hattingh notes that async generators and async context managers should have one clear owner managing the resource lifecycle (Ch. 3, "Async Context Managers: async with"). The current design splits ownership across two generators.

### F5. Checkout Listener Uses Raw DBAPI Cursor

The pool checkout listener resets tenant context using raw DBAPI operations that bypass SQLAlchemy's transaction tracking.

Current examples:

- `db/tenant_context.py:136-141` — `cursor = dbapi_conn.cursor(); cursor.execute("RESET app.current_tenant"); cursor.execute("RESET app.bypass_rls"); cursor.close()`

These run via the greenlet-adapted synchronous event system (confirmed by SQLAlchemy async docs: "Events remain synchronous even in async code. Register via sync_* attributes"). If the underlying connection is corrupted, the exception propagates unhandled through the pool checkout mechanism.

**Impact:** Low in isolation. The raw DBAPI operations should run in autocommit mode and succeed or fail quickly. However, combined with F1's double lifecycle, a connection returned to the pool with ambiguous transaction state could cause this listener to fail on checkout, creating a secondary failure path.

### F6. No Circuit Breaker on Session Dependency

When multiple consecutive requests encounter `InFailedSQLTransactionError`, the system continues attempting new requests against the poisoned pool. Each attempt checks out a connection, runs the probe (`SELECT 1`), sets tenant context, then fails at the ORM query — consuming pool connections and time without useful work.

Current examples:

- No circuit breaker implementation exists anywhere in `apps/prototype-description-service/`

**Impact:** Nygard identifies this as the primary defense against cascading failures: "The most effective patterns to combat cascading failures are Circuit Breaker and Timeouts" (§4.3). Without a circuit breaker, the pool-poisoning cascade runs until all connections are exhausted or the service is restarted.

### F7. No Query-Level Timeouts Configured

No `statement_timeout`, `idle_in_transaction_session_timeout`, or `transaction_timeout` is set at the session, connection, or PostgreSQL configuration level.

Current examples:

- `db/settings.py:100-103` — `pool_size=20, max_overflow=10, pool_timeout=30, pool_recycle=3600` — pool-level timeouts exist but no query-level or transaction-level timeouts
- No `statement_timeout` appears anywhere in the codebase (verified by grep)

**Impact:** A connection in a failed transaction state can sit idle indefinitely. `pool_timeout=30` bounds the wait for a connection checkout, but once checked out, there is no bound on how long a query or transaction can run. `transaction_timeout` (available since PG17, already deployed) and `idle_in_transaction_session_timeout` (available since PG9.6) are immediately available but unconfigured — these would automatically terminate sessions in a failed/idle transaction state.

### F8. No Connection Pool Bulkheading

All three session dependencies (`get_session`, `get_optional_session`, `get_observability_session`) share the same connection pool. When the pool is poisoned, observability endpoints fail alongside business endpoints.

Current examples:

- `db/session.py:21-29` — single `engine` shared by all session factories
- `deps/session.py:135-175` — `get_observability_session` uses the same `_get_session()` from the shared engine

**Impact:** Nygard's Bulkhead pattern (§5.3) recommends partitioning resources so that a failure in one partition cannot exhaust another. The observability session should remain available for diagnostics even when business connections are poisoned.

## Recommendations

### 1. Flatten session lifecycle to single-owner pattern

**Traces:** F1, F3, F4
**Priority:** P0

Refactor all three session dependencies (`get_session`, `get_optional_session`, `get_observability_session`) to create sessions directly from `async_session_factory()` instead of wrapping `_get_session()` via `async for`. Each dependency should own the full lifecycle: create, probe, set tenant context, yield, commit/rollback, clear tenant context, close. The inner `db.session.get_session()` generator remains available for non-HTTP callers but is no longer used by the HTTP dependency layer.

Use `async with async_session_factory() as session:` pattern per the SQLAlchemy async docs' explicit warning about connection leaks when `AsyncSession` falls out of scope without `aclose()`.

### 2. Remove duplicate tenant context setup

**Traces:** F2
**Priority:** P1

Choose one location for tenant context setup and remove the other. The dependency layer (`deps/session.py`) is the natural owner because it already manages the session lifecycle. Remove the `set_tenant_context` call from `_prepare_tenant_context` in `routers/analyze.py:187`. Keep `ensure_tenant_exists` in the endpoint because it has business-logic semantics (auto-provisioning).

### 3. Replace exception suppression with diagnostic logging

**Traces:** F3
**Priority:** P1

Replace `contextlib.suppress(Exception)` in `clear_tenant_context` with a `try/except` that logs the exception at `WARNING` level with session state metadata (`in_transaction()`, connection identity). This preserves the "don't raise during cleanup" behavior while providing the diagnostic signal needed to distinguish failure modes.

### 4. Guard checkout listener

**Traces:** F5
**Priority:** P2

Wrap the checkout listener's raw DBAPI operations in `try/except` with logging. This prevents unhandled exceptions from propagating through the pool checkout mechanism and provides diagnostic signal for connection-level corruption.

### 5. Configure PostgreSQL timeout parameters

**Traces:** F7
**Priority:** P1

Configure `statement_timeout`, `idle_in_transaction_session_timeout`, and `transaction_timeout` at the session level via `SET LOCAL` in the session dependency. These are server-side defenses available in the current PG17 deployment — they do not require PG18. Recommended values for prototype:

- `statement_timeout = '10s'` — bound individual query execution
- `idle_in_transaction_session_timeout = '30s'` — terminate idle-in-transaction sessions
- `transaction_timeout = '60s'` — bound total transaction duration (PG17+)

### 6. Add circuit breaker on session dependency (ADR-gated)

**Traces:** F6
**Priority:** P1 (design), P2 (implementation)

Add a circuit breaker that opens after N consecutive session failures (e.g., 3) and returns HTTP 503 immediately for a cooldown period. Requires a design decision on: library choice (tenacity, pybreaker, or hand-rolled), threshold/cooldown parameters, and integration with FastAPI dependency injection. Recommend as Tier 3 / ADR-gated in the spec.

### 7. Dedicated observability pool (ADR-gated)

**Traces:** F8
**Priority:** P2 (design), P3 (implementation)

Create a separate `AsyncEngine` with its own small connection pool (pool_size=2) for `get_observability_session`. This ensures health checks and diagnostics remain available during pool-wide business connection failures. Requires a design decision on: pool sizing, engine lifecycle management, and whether the observability pool should share the same PostgreSQL role. Recommend as Tier 3 / ADR-gated in the spec.

## Code-Verified Critique

### What the assessment gets right

- **F1 (Double Lifecycle)** is strongly supported by code: the `async for` + `aclose()` pattern in deps/session.py:51-80 and deps/session.py:88-132 is verified, and the inner generator's commit/rollback/close at db/session.py:44-51 is verified. The execution sequence analysis is correct — autobegin creates the spurious micro-transaction.
- **F2 (Duplicate set_tenant_context)** is verified: deps/session.py:101 and routers/analyze.py:187 both call `set_tenant_context` on the same session for the same tenant.
- **F3 (Exception Suppression)** is verified at db/tenant_context.py:85.
- **F7 (No Timeouts)** is verified: no `statement_timeout` appears anywhere in the codebase.

### Where the assessment overstates the problem

- **F4 (Race with Session Close)** is rated "Low Impact" and that is correct — the current code ordering is actually safe because the `finally` block runs after the `try` body completes, and `aclose()` is the last operation. The race would only materialize if someone refactors the `finally` block ordering. This is a maintenance hazard, not a current bug. The original investigation overstated this by calling it a "race" — it's a fragile coupling, not a race condition.
- **F5 (Checkout Listener)** — the original investigation rated this "Low Impact" and that is correct. The raw DBAPI operations run at connection checkout time, before any SQLAlchemy session is involved. They are unlikely to encounter a failed transaction because the connection was just checked out from the pool. The realistic failure mode is a corrupted connection that should have been discarded by `pool_pre_ping` — which is enabled.
- **F8 (No Bulkheading)** — this is a valid pattern recommendation but may be over-engineering for a prototype with `pool_size=20`. The pool is unlikely to be fully exhausted by a single failure cascade. Worth considering for production but not P0/P1 for the prototype.

### Recommendations the assessment is missing

- **R-MISS-1: Disable or tune asyncpg statement cache.** The investigation's H3 (asyncpg prepared statement cache interaction) is a plausible contributing cause. asyncpg caches prepared statements per connection and uses the extended query protocol for parameterized queries, while `pool_pre_ping` uses the simple query protocol. A stale cache entry on a recycled connection could cause the ORM query to fail even though the probe succeeded. Setting `prepared_statement_cache_size=0` in the engine URL would eliminate this vector. This should be a diagnostic step first and potentially a permanent configuration if confirmed.
- **R-MISS-2: Checkpoint — add connection-identity logging.** Adding `id(session.get_bind())` to the session dependency timing log would confirm whether the probe and the failing query use the same underlying connection. This is a zero-cost diagnostic that should be added regardless of which root cause hypothesis is confirmed.
- **R-MISS-3: PG17 `transaction_timeout` is already available.** `transaction_timeout` (introduced in PG17, which is the current deployment) would automatically terminate any transaction that exceeds the configured duration, preventing connections from sitting in a failed state indefinitely. This is the highest-leverage immediately-available mitigation. See also [PG18 upgrade roadmap — Phase 0](../roadmaps/roadmap-pg18-upgrade.md#phase-0-pg17-safety-parameter-configuration).

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
|----------|--------|--------|--------|-------|
| **P0** | Flatten session lifecycle to single-owner | Eliminates primary cascading failure mechanism | Medium — refactor 3 dependencies, update tests | F1, F3, F4 |
| **P1** | Configure PostgreSQL timeout parameters | Server-side bound on failed transaction duration | Small — SET LOCAL in session setup | F7 |
| **P1** | Replace exception suppression with diagnostic logging | Enables root cause diagnosis | Small — replace 3 lines in `clear_tenant_context` | F3 |
| **P1** | Remove duplicate set_tenant_context | Halves SQL round-trips, reduces error surface | Small — remove 1 call site | F2 |
| **P1** | Add connection-identity logging | Zero-cost diagnostic for connection reuse | Small — add 1 log field | R-MISS-2 |
| **P2** | Guard checkout listener | Prevents unhandled exception propagation | Small — wrap in try/except | F5 |
| **P2** | Disable asyncpg statement cache (diagnostic) | Confirms or eliminates H3 hypothesis | Small — engine URL parameter | R-MISS-1 |
| **P2** | Circuit breaker on session dependency | Stops cascading failure amplification | Medium — requires design decision | F6 |
| **P3** | Dedicated observability pool | Fault isolation for diagnostics | Medium — requires design decision | F8 |

## Deferred or Rejected Directions

- **Dedicated observability pool (P3):** Valid pattern but may be over-engineering for the prototype. Defer until pool exhaustion is observed in practice.

## Suggested Spec Direction

The spec should define testable changes for findings F1–F5 and F7 (the code-level bugs and timeout configuration). These are Tier 1: high-certainty, code-verified, independent, no design uncertainty.

F6 (circuit breaker) and F8 (pool bulkheading) should be Tier 3 / ADR-gated because they require design decisions about library choice, threshold parameters, and pool partitioning strategy.

The spec should live at `docs/specs/session-lifecycle-resilience-spec.md` (monorepo level, since it spans `apps/prototype-description-service/db/` and `apps/prototype-description-service/recognition/interface_adapters/http/deps/`).

## Next Step

- [x] Write a spec (path: `docs/specs/session-lifecycle-resilience-spec.md`) — Tier 1 items ready to implement, Tier 3 items ADR-gated for circuit breaker and pool bulkheading

## References

- `apps/prototype-description-service/db/session.py` — inner session generator
- `apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py` — outer session dependencies
- `apps/prototype-description-service/db/tenant_context.py` — tenant context helpers, checkout listener
- `apps/prototype-description-service/db/settings.py` — pool configuration
- `apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py` — analyze endpoint with duplicate `set_tenant_context`
- `docs/literature/extracted/refactoring/Release-it--design-and-deploy–production-ready-software--Michael-T-Nygard.txt` — stability antipatterns and patterns
- `docs/literature/extracted/refactoring/Using-Asyncio-in-Python-Understanding-Python-Hattingh.txt` — async context manager ownership
