# Session Lifecycle Resilience Specification

> **Metadata**
>
> - **Date**: 2026-04-09
> - **Author**: Claude Opus 4.6
> - **Status**: Draft
> - **Assessment**: [docs/assessment/infailed-sql-transaction-investigation-2026-04-09.md](../assessment/infailed-sql-transaction-investigation-2026-04-09.md)
> - **Package version target**: n/a (monorepo `apps/prototype-description-service`)
>
> **Purpose:** This spec defines testable changes to eliminate the double session lifecycle bug,
> configure PostgreSQL safety timeouts, add diagnostic logging, and remove redundant tenant context
> calls. These changes resolve the `InFailedSQLTransactionError` cascading failure documented in the assessment.

**Constraints:** Greenfield policy applies — no backward compatibility needed, no production users,
clean rewrites preferred over shims. The session dependency contract (`AsyncIterator[AsyncSession | None]`)
must remain stable because FastAPI endpoint signatures depend on it. The `db.session.get_session()` generator
must remain available for non-HTTP callers (background workers, CLI tools) — it is not being removed, only
decoupled from the HTTP dependency layer.

---

## Spec Items

### SLR-001: Flatten session dependency lifecycle to single-owner pattern

**Trace:** F1 (Double Session Lifecycle), F4 (Race with Session Close)
**Priority:** P0

All three HTTP session dependencies (`get_session`, `get_optional_session`, `get_observability_session`) currently wrap `db.session.get_session()` via `async for`, creating two independent commit/rollback/close layers over the same `AsyncSession`. This must be replaced with a single-owner pattern where each dependency creates the session directly, owns the full lifecycle, and never delegates transaction management to another generator.

**Before** (`recognition/interface_adapters/http/deps/session.py::get_optional_session`):
```python
async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    started_at = _time.perf_counter()
    session_iter = cast(AsyncGenerator[AsyncSession, None], _get_session())
    try:
        async for session in session_iter:
            # ... probe, set_tenant_context, yield, commit, rollback ...
            # BUG: session_iter also commits/rollbacks/closes in its own generator
    finally:
        await session_iter.aclose()
```

**After:**
```python
async def get_optional_session(
    tenant_id: str | None = Depends(get_tenant_id_optional),
) -> AsyncIterator[AsyncSession | None]:
    started_at = _time.perf_counter()
    session = async_session_factory()
    probe_ms: float | None = None
    tenant_context_ms: float | None = None
    session_available = False
    try:
        try:
            probe_started_at = _time.perf_counter()
            await session.execute(text("SELECT 1"))
            probe_ms = (_time.perf_counter() - probe_started_at) * 1000
            if tenant_id:
                tenant_context_started_at = _time.perf_counter()
                await set_tenant_context(session, uuid.UUID(str(tenant_id)))
                tenant_context_ms = (_time.perf_counter() - tenant_context_started_at) * 1000
        except Exception:
            await session.close()
            _log_session_dependency_timing(
                "get_optional_session", started_at=started_at,
                available=False, tenant_id=tenant_id,
                probe_ms=probe_ms, tenant_context_ms=tenant_context_ms,
            )
            yield None
            return
        session_available = True
        try:
            yield session
            await session.commit()
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("get_optional_session: exception during yield/commit: %s", exc)
            await session.rollback()
            raise
    finally:
        _log_session_dependency_timing(
            "get_optional_session", started_at=started_at,
            available=session_available, tenant_id=tenant_id,
            probe_ms=probe_ms, tenant_context_ms=tenant_context_ms,
        )
        await session.close()
```

Key changes:
- `async_session_factory()` replaces `cast(AsyncGenerator, _get_session())` — session created directly, no wrapping
- Single commit/rollback path — no inner generator with its own commit/rollback
- `session.close()` in the outermost `finally` — guarantees cleanup on all paths, no fragile `aclose()` sequencing
- `clear_tenant_context` is removed from the request path (see SLR-005 rationale below)
- Import `async_session_factory` from `db.session` instead of `_get_session`

The same refactor applies to `get_session` and `get_observability_session` with the same pattern. Each dependency owns exactly one lifecycle: create → probe → [set tenant context] → yield → commit/rollback → close.

**Done when:**
- `deps/session.py` does not import `get_session` from `db.session`
- `deps/session.py` imports `async_session_factory` from `db.session`
- No `async for session in session_iter:` pattern exists in `deps/session.py`
- No `session_iter.aclose()` call exists in `deps/session.py`
- `db.session.get_session()` remains unchanged (used by non-HTTP callers)
- `POST /recognition/analyze` succeeds with a valid tenant_id when the database is available
- `POST /recognition/analyze` returns a non-5xx error (or `None` session) when the database is unavailable
- No "double COMMIT" appears in SQLAlchemy echo logging for a single request (`echo=True` test)

---

### SLR-002: Remove duplicate set_tenant_context from analyze endpoint

**Trace:** F2 (Duplicate set_tenant_context)
**Priority:** P1

`_prepare_tenant_context` in `routers/analyze.py:187` calls `set_tenant_context(session, tenant_uuid)` after the session dependency has already set tenant context. Remove the duplicate call. Keep `ensure_tenant_exists` because it has business-logic semantics (auto-provisioning).

**Before** (`recognition/interface_adapters/http/routers/analyze.py::_prepare_tenant_context`):
```python
if session is not None and hasattr(session, "execute") and is_postgres(session):
    await ensure_tenant_exists(session, tenant_uuid)
    await set_tenant_context(session, tenant_uuid)  # DUPLICATE — already set by dependency
```

**After:**
```python
if session is not None and hasattr(session, "execute") and is_postgres(session):
    await ensure_tenant_exists(session, tenant_uuid)
    # set_tenant_context is handled by the session dependency layer
```

**Done when:**
- `routers/analyze.py` does not call `set_tenant_context` (grep verification)
- `routers/analyze.py` does not import `set_tenant_context` (import cleanup)
- `ensure_tenant_exists` is still called in `_prepare_tenant_context`
- Existing analyze tests pass without modification (tenant context is set by the dependency)

---

### SLR-003: Replace exception suppression with diagnostic logging in clear_tenant_context

**Trace:** F3 (Exception Suppression)
**Priority:** P1

Replace `contextlib.suppress(Exception)` with explicit `try/except` that logs session state metadata.

**Before** (`db/tenant_context.py::clear_tenant_context`):
```python
async def clear_tenant_context(session: AsyncSession) -> None:
    if is_sqlite(session):
        return
    with contextlib.suppress(Exception):
        await session.execute(text("RESET app.current_tenant"))
        await session.execute(text("RESET app.bypass_rls"))
```

**After:**
```python
async def clear_tenant_context(session: AsyncSession) -> None:
    if is_sqlite(session):
        return
    try:
        await session.execute(text("RESET app.current_tenant"))
        await session.execute(text("RESET app.bypass_rls"))
    except Exception:
        logger.warning(
            "clear_tenant_context failed (session in_transaction=%s)",
            session.in_transaction(),
            exc_info=True,
        )
```

**Done when:**
- `contextlib.suppress` is not used in `clear_tenant_context` (grep verification)
- A `WARNING`-level log is emitted when clear_tenant_context fails on a session in a failed transaction state
- The function does not raise — cleanup failures are logged but do not propagate

---

### SLR-004: Guard checkout listener with try/except

**Trace:** F5 (Checkout Listener)
**Priority:** P2

Wrap the checkout listener's raw DBAPI operations in `try/except` with logging.

**Before** (`db/tenant_context.py::_register_checkout_listener`):
```python
def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("RESET app.current_tenant")
    cursor.execute("RESET app.bypass_rls")
    cursor.close()
```

**After:**
```python
def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy) -> None:
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("RESET app.current_tenant")
        cursor.execute("RESET app.bypass_rls")
        cursor.close()
    except Exception:
        logger.warning("checkout listener: failed to reset tenant context", exc_info=True)
```

**Done when:**
- The checkout listener does not propagate exceptions to the pool checkout mechanism
- A `WARNING`-level log is emitted on failure

---

### SLR-005: Remove clear_tenant_context from request path

**Trace:** F1 (Double Lifecycle — autobegin from RESET commands), F4 (Race with Session Close)
**Priority:** P1

After SLR-001 flattens the lifecycle, `clear_tenant_context` in the request path creates a spurious autobegin transaction: the RESET commands start a new transaction after commit, and then `session.close()` must roll it back. The checkout listener (`db/tenant_context.py:136-141`) already resets `app.current_tenant` and `app.bypass_rls` at connection checkout time, guaranteeing cleanup for the next consumer regardless of how the current request ends.

Remove `clear_tenant_context` calls from all three session dependencies. The checkout listener provides the same guarantee without the autobegin side effect.

**Before** (`deps/session.py::get_optional_session`, line 129-130):
```python
if tenant_id:
    await clear_tenant_context(session)
```

**After:**
```python
# Tenant context cleanup is handled by the pool checkout listener
# (db/tenant_context.py::_reset_context_on_checkout).
# Calling clear_tenant_context here would start a spurious autobegin
# transaction that session.close() must roll back.
```

**Done when:**
- `deps/session.py` does not call `clear_tenant_context` (grep verification)
- `deps/session.py` does not import `clear_tenant_context`
- The checkout listener (`_reset_context_on_checkout`) remains registered and functional
- `clear_tenant_context` remains in the module for use by `get_tenant_aware_session` and any future non-HTTP callers

---

### SLR-006: Configure PostgreSQL transaction safety timeouts

**Trace:** F7 (No Query-Level Timeouts). See also [PG18 roadmap — Phase 0](../roadmaps/roadmap-pg18-upgrade.md#phase-0-pg17-safety-parameter-configuration).
**Priority:** P1

Add `SET LOCAL` timeout configuration to the session setup path. These are server-side defenses available in the current PG17 deployment.

**Before:**

No timeout configuration exists anywhere in the session lifecycle.

**After** (in the session dependency, after probe succeeds, before yield):
```python
# Set server-side safety timeouts for this transaction
await session.execute(text("SET LOCAL statement_timeout = '10s'"))
await session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '30s'"))
```

`transaction_timeout` (PG17+) should be configured at the PostgreSQL server level (`postgresql.conf`) rather than per-session, because it bounds total transaction duration including application processing time between SQL commands.

**Done when:**
- `SET LOCAL statement_timeout` is executed in the session dependency after the probe succeeds
- `SET LOCAL idle_in_transaction_session_timeout` is executed in the session dependency after the probe succeeds
- Values are configurable via environment variables with sensible defaults (`DB_STATEMENT_TIMEOUT=10s`, `DB_IDLE_IN_TXN_TIMEOUT=30s`)
- SQLite sessions skip timeout configuration (guarded by `is_postgres()` or equivalent)

---

### SLR-007: Add connection-identity logging

**Trace:** R-MISS-2 (Connection identity diagnostic)
**Priority:** P1

Add connection identity to the session dependency timing log to confirm whether the probe and the failing query use the same underlying connection.

**Before** (`deps/session.py::_log_session_dependency_timing`):
```python
logger.info(
    "session_dependency_timing dependency=%s available=%s tenant_id=%s total_ms=%.2f probe_ms=%s tenant_context_ms=%s",
    ...
)
```

**After:**
```python
logger.info(
    "session_dependency_timing dependency=%s available=%s tenant_id=%s total_ms=%.2f probe_ms=%s tenant_context_ms=%s conn_id=%s",
    dependency_name, available, tenant_id or "",
    (_time.perf_counter() - started_at) * 1000,
    f"{probe_ms:.2f}" if probe_ms is not None else "n/a",
    f"{tenant_context_ms:.2f}" if tenant_context_ms is not None else "n/a",
    conn_id or "n/a",
)
```

Where `conn_id` is derived from the session's bound connection when available.

**Done when:**
- Session dependency timing logs include a `conn_id` field
- The `conn_id` is stable for the duration of a single request (same value for probe and yield)

---

### SLR-008: Diagnostic — asyncpg statement cache toggle

**Trace:** R-MISS-1 (asyncpg statement cache)
**Priority:** P2

Add an environment variable to disable asyncpg's prepared statement cache for diagnostic purposes. This confirms or eliminates hypothesis H3 (stale statement cache entries cause extended-protocol failures after simple-protocol probe succeeds).

**Before** (`db/settings.py`):
```python
postgres_dsn: str  # e.g. "postgresql+asyncpg://..."
```

**After:**
```python
# When DB_DISABLE_STMT_CACHE=1, append ?prepared_statement_cache_size=0 to DSN
```

**Done when:**
- Setting `DB_DISABLE_STMT_CACHE=1` results in `prepared_statement_cache_size=0` being passed to asyncpg
- The default behavior (cache enabled) is unchanged
- A log message at startup indicates whether the statement cache is disabled

---

## Implementation Tiers

### Tier 1 — Ready to implement

Task plan: `docs/tasks/15.0/slr-1-session-lifecycle-resilience-task-plan.md`

```
SLR-001  Flatten session lifecycle         P0 — primary fix, ~80 LOC refactor
SLR-002  Remove duplicate set_tenant_ctx   P1 — 1 call site removal
SLR-003  Diagnostic logging in cleanup     P1 — 3 lines replaced
SLR-004  Guard checkout listener           P2 — try/except wrapper
SLR-005  Remove request-path cleanup       P1 — depends on SLR-001
SLR-006  Configure PG timeouts             P1 — SET LOCAL additions
SLR-007  Connection-identity logging       P1 — 1 log field addition
SLR-008  Statement cache toggle            P2 — DSN parameter
```

SLR-001 must land first. SLR-005 depends on SLR-001 (removing request-path cleanup only makes sense after the double lifecycle is eliminated). All others are independent and can be parallelized.

### Tier 3 — ADR-Backed Direction, Ready for Implementation Planning

Design artifact: `docs/agentic/adrs/ADR-006-session-circuit-breaker-and-pool-bulkheading.md`

ADR-006 is now the approved source of truth for the Tier 3 resilience split. It chooses:
- a repo-local, in-process circuit breaker in the HTTP dependency boundary
- breaker state owned on FastAPI `app.state`
- a dedicated observability `AsyncEngine` and pool as the bulkhead
- explicit environment-backed thresholds and observability pool sizing

Implementation-ready follow-on task plans:

```
SLR-3   Session dependency circuit breaker   docs/tasks/15.0/slr-3-session-dependency-circuit-breaker-task-plan.md
SLR-4   Observability pool bulkhead          docs/tasks/15.0/slr-4-observability-pool-bulkhead-task-plan.md
```

Recommended sequencing:
- `SLR-3` lands the breaker state machine, FastAPI ownership, dependency integration, and breaker-aware health semantics.
- `SLR-4` lands the dedicated observability engine/pool, split pool stats, and observability wiring. It may follow `SLR-3` or be reviewed in parallel, but should not contradict the breaker-open health contract introduced there.

---

## Spec-Review Gate

No implementation tasks may be created from this spec until:

1. The spec has been reviewed with findings recorded in MCP
2. All review findings are resolved (fixed, deferred with rationale, or wontfix)
3. Validation snippets have been verified against the current package (not guessed)

For Tier 3 / architectural items, the review gate applied to ADR-006 before the follow-on task plans were created. Those implementation plans now exist and should inherit the ADR-backed direction rather than re-open the architectural choice.

---

## Validation

### Tier 1 validation

```bash
# --- SLR-001: Verify no double lifecycle pattern ---
# After implementation, these greps must return zero matches:
grep -n "session_iter" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: no matches

grep -n "async for session in" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: no matches

grep -n "aclose" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: no matches

grep -n "from db.session import get_session" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: no matches

grep -n "async_session_factory" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: matches (confirms direct factory usage)

# --- SLR-002: Verify no duplicate set_tenant_context ---
grep -n "set_tenant_context" apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py
# Expected: no matches (only ensure_tenant_exists should remain)

# --- SLR-003: Verify no exception suppression in cleanup ---
grep -n "contextlib.suppress" apps/prototype-description-service/db/tenant_context.py
# Expected: no matches

# --- SLR-005: Verify no request-path cleanup ---
grep -n "clear_tenant_context" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: no matches

# --- SLR-006: Verify timeout configuration ---
grep -n "statement_timeout" apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py
# Expected: matches (SET LOCAL statement_timeout)

# --- Full test suite ---
cd apps/prototype-description-service && python -m pytest recognition/tests/ -x -q
```

### Tier 1 proof requirement

```bash
# Existing package tests that must stay green while the lifecycle is flattened:
cd apps/prototype-description-service && python -m pytest \
  recognition/tests/api/test_dependencies.py \
  recognition/tests/api/test_api_analyze.py \
  recognition/tests/api/test_api_health.py -q
```

Tier 1 implementation must add automated regression coverage for the single-owner
session lifecycle and configuration changes. Manual `echo=True` log inspection is
not sufficient close evidence for this spec. The follow-on task plan owns the
concrete proof bundle for:

- one dependency-owned commit/rollback path per request
- removal of duplicate tenant-context setup in `routers/analyze.py`
- timeout and statement-cache settings flowing through `db/settings.py` and `db/session.py`
