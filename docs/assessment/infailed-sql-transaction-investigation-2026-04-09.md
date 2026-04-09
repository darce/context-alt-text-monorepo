# Investigation: InFailedSQLTransactionError in /recognition/analyze

**Date:** 2026-04-09
**Severity:** High (blocks all analyze requests when triggered)
**Status:** Root cause narrowed; fix recommendations provided

## Symptom

All `POST /recognition/analyze` requests fail with HTTP 501 and the PostgreSQL error:

```
InFailedSQLTransactionError: current transaction is aborted,
commands ignored until end of transaction block
```

The error occurs at `ensure_tenant_exists()` when executing `SELECT FROM tenants WHERE id = $1::UUID`. Multiple consecutive requests fail identically (cascading failure pattern).

Critically, the session dependency's health probe (`SELECT 1`) and tenant context setup (`RESET` + `SET LOCAL`) both succeed immediately before the failing query; the timing logs confirm `probe_ms=3.50` and `tenant_context_ms=0.94` with `available=True`.

## Call Chain

```
analyze_media()                          # routers/analyze.py:260
  session = Depends(get_optional_session) # deps/session.py:86
    _get_session()                        # db/session.py:38  [inner generator]
      session = async_session_factory()
      yield session                       # <-- _get_session suspends here
    SELECT 1                              # probe succeeds
    set_tenant_context(session, ...)      # RESET + SET LOCAL succeeds
    yield session                         # <-- get_optional_session suspends here
  _prepare_tenant_context()               # routers/analyze.py:170
    ensure_tenant_exists(session, ...)    # tenant_context.py:34
      SELECT FROM tenants WHERE id=$1     # <-- FAILS: InFailedSQLTransactionError
```

## Architecture Bugs Found

### Bug 1: Double Session Lifecycle Management (High Impact)

`get_optional_session` wraps `db.session.get_session()` via `async for`, creating **two independent commit/rollback layers** over the same session:

| Layer | Commits | Rollbacks | Closes |
|---|---|---|---|
| `get_optional_session` (outer) | Yes (after yield to endpoint) | Yes (on endpoint error) | No |
| `_get_session()` (inner) | Yes (when `async for` advances past yield) | Yes (on any exception) | Yes (finally) |

**Execution sequence on success:**
1. Endpoint returns; `get_optional_session` commits (**first commit**)
2. `clear_tenant_context` runs RESETs, starting a new autobegin transaction
3. `async for` advances `_get_session()`; it commits again (**second commit** of the autobegin transaction)
4. `_get_session()` finally block closes the session

The second commit is unnecessary and creates a micro-transaction (BEGIN + COMMIT) on every request. More importantly, if either commit fails due to a transient error, the exception handling paths diverge: `get_optional_session` catches and rolls back, but `_get_session()`'s except clause may also fire, creating ambiguous cleanup ordering.

**File:** [deps/session.py](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py#L86-L130) wrapping [db/session.py](../../apps/prototype-description-service/db/session.py#L38-L54)

### Bug 2: Duplicate set_tenant_context Calls (Medium Impact)

Tenant context (`app.current_tenant`) is set **twice** per request:

1. In `get_optional_session` (the dependency): [deps/session.py line 103](../../apps/prototype-description-service/recognition/interface_adapters/http/deps/session.py#L103)
2. In `_prepare_tenant_context` (the endpoint): [routers/analyze.py line 187](../../apps/prototype-description-service/recognition/interface_adapters/http/routers/analyze.py#L187)

Each call executes `RESET app.bypass_rls` + `SET LOCAL app.current_tenant`, doubling the SQL round-trips. The second call also runs `ensure_tenant_exists` BEFORE `set_tenant_context`, but `set_tenant_context` was already called in the dependency; the endpoint re-does it redundantly.

### Bug 3: Exception Suppression in clear_tenant_context (Low Impact)

```python
# db/tenant_context.py:81-84
async def clear_tenant_context(session: AsyncSession) -> None:
    with contextlib.suppress(Exception):
        await session.execute(text("RESET app.current_tenant"))
        await session.execute(text("RESET app.bypass_rls"))
```

All exceptions during cleanup are silently swallowed. If the session is in a bad state, this masks diagnostic information. Combined with the double lifecycle, this makes it harder to trace how connections return to the pool.

### Bug 4: clear_tenant_context Races with Session Close (Low Impact)

In `get_optional_session`'s finally block, `clear_tenant_context` runs inside the `async for` body. After it completes, the `async for` advances `_get_session()`, which commits and then closes the session. Ordering is currently correct, but fragile; any refactor that changes the `async for` iteration could cause `clear_tenant_context` to run on a closed session.

### Bug 5: Checkout Listener Uses Raw DBAPI Cursor (Low Impact)

```python
# db/tenant_context.py:140-144
@event.listens_for(engine.sync_engine, "checkout")
def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy):
    cursor = dbapi_conn.cursor()
    cursor.execute("RESET app.current_tenant")
    cursor.execute("RESET app.bypass_rls")
    cursor.close()
```

These raw DBAPI operations bypass SQLAlchemy's transaction tracking. They run at the asyncpg adapter level via greenlet-adapted synchronous calls. While they should execute in autocommit mode, any failure here (e.g., if the underlying connection is corrupted) is not caught, and the exception propagates unhandled through the pool checkout mechanism.

## Root Cause Hypotheses

### H1: Preceding Request Poisoned Connection Pool (Most Likely)

A request prior to the ones in the log encountered a SQL error whose cleanup path left a pooled connection with an aborted transaction. Despite `pool_pre_ping=True`, the connection was reused:

- `pool_pre_ping` runs `SELECT 1` via the DBAPI adapter. If the pre-ping ran via the **simple query protocol** and succeeded, but the connection's **extended protocol state** (prepared statement cache) was corrupted, the ORM query's `PREPARE` step would fail.
- asyncpg caches prepared statements per connection. If the connection was previously used, a stale or invalid cached statement could trigger internal asyncpg operations (e.g., `DEALLOCATE`) during the `PREPARE` phase that abort the transaction.

**Evidence:** Multiple consecutive requests fail identically, suggesting all pool connections are affected; this matches a scenario where a cascading error poisoned the entire pool (pool_size=20 with burst traffic could exhaust all connections).

### H2: set_tenant_context Error Recovery Leaves Stale State (Possible)

The `set_tenant_context` function catches `InFailedSQLTransactionError` and recovers by rolling back and retrying. If this recovery path fires in `get_optional_session`:

1. The rollback ends the original transaction (started by the `SELECT 1` probe)
2. New RESET + SET LOCAL run in a new autobegin transaction
3. Session is yielded to the endpoint
4. Endpoint's `ensure_tenant_exists` runs in the new transaction

If the retry itself fails partially (e.g., SET LOCAL succeeds but some internal asyncpg state is inconsistent), the subsequent ORM query could encounter the aborted transaction. The `tenant_context_ms=0.94` is tight but plausible for a rollback + 2 retries on localhost.

### H3: asyncpg Prepared Statement Cache Interaction (Possible)

asyncpg uses the extended query protocol for parameterized queries (`$1::UUID`). The `PREPARE` step for `ensure_tenant_exists`'s SELECT query differs from the simple-protocol commands (SELECT 1, RESET, SET LOCAL) used by the probe and tenant context setup. If the asyncpg connection's prepared statement cache contains an invalid entry for this query (from a previous aborted transaction on the same connection), the `PREPARE` could trigger a cache invalidation that itself fails inside the aborted transaction window.

### H4: Double Commit Causes Intermittent Connection State Corruption (Less Likely)

The double commit pattern (Bug 1) creates a micro-transaction (BEGIN + COMMIT) at the end of every request. If this micro-transaction encounters a transient error (network blip, PostgreSQL busy), the exception handling in `_get_session()` rolls back and re-raises, but the connection may be returned to the pool in an ambiguous state. The next request on that connection would then see the aborted transaction.

## Recommended Fixes

### Fix 1: Eliminate Double Session Lifecycle (Critical)

Refactor `get_optional_session` to create sessions directly instead of wrapping `_get_session()`:

```python
async def get_optional_session(...) -> AsyncIterator[AsyncSession | None]:
    session = async_session_factory()
    try:
        # probe
        await session.execute(text("SELECT 1"))
        if tenant_id:
            await set_tenant_context(session, uuid.UUID(str(tenant_id)))
    except Exception:
        await session.close()
        yield None
        return
    try:
        yield session
        await session.commit()
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise
    finally:
        if tenant_id:
            await clear_tenant_context(session)
        await session.close()
```

This eliminates the double commit, the fragile `async for` interaction, and the ambiguous cleanup ordering.

### Fix 2: Remove Duplicate set_tenant_context (Medium)

Choose ONE location for tenant context setup. Since `get_optional_session` already sets it, remove the redundant call from `_prepare_tenant_context`:

```python
# In _prepare_tenant_context, change:
if session is not None and hasattr(session, "execute") and is_postgres(session):
    await ensure_tenant_exists(session, tenant_uuid)
    # Remove: await set_tenant_context(session, tenant_uuid)
```

Or, remove it from `get_optional_session` and keep it only in the endpoint (the endpoint has more context about what tenant operations are needed).

### Fix 3: Add Diagnostic Logging to clear_tenant_context

Replace `contextlib.suppress(Exception)` with explicit error logging:

```python
async def clear_tenant_context(session: AsyncSession) -> None:
    if is_sqlite(session):
        return
    try:
        await session.execute(text("RESET app.current_tenant"))
        await session.execute(text("RESET app.bypass_rls"))
    except Exception:
        logger.debug("clear_tenant_context failed (expected during cleanup)", exc_info=True)
```

### Fix 4: Guard Checkout Listener

Wrap the checkout listener in a try/except to prevent unhandled exceptions from propagating through the pool mechanism:

```python
def _reset_context_on_checkout(dbapi_conn, connection_record, connection_proxy):
    try:
        cursor = dbapi_conn.cursor()
        cursor.execute("RESET app.current_tenant")
        cursor.execute("RESET app.bypass_rls")
        cursor.close()
    except Exception:
        logger.warning("checkout listener: failed to reset tenant context", exc_info=True)
```

## Next Investigation Steps

If the fix recommendations above don't resolve the issue:

1. **Enable SQLAlchemy echo logging** (`echo=True` on engine) to see the exact sequence of SQL commands sent to PostgreSQL, including implicit BEGIN/COMMIT and any asyncpg-internal commands.
2. **Check PostgreSQL server logs** for transaction abort causes. Filter for the tenant UUID `c0ce73dc-1c66-56a4-ae32-6eb966810988` and look for ERROR entries preceding the `InFailedSQLTransactionError`.
3. **Add connection identity logging** to `get_optional_session` to verify the same connection is used for the probe and the failing query:
   ```python
   logger.info("connection id: %s", id(session.get_bind()))
   ```
4. **Disable asyncpg's statement cache** (`prepared_statement_cache_size=0` in the engine URL) to rule out H3.
5. **Test with a fresh pool** by restarting the service and immediately sending ONE request. If it fails, the issue is not pool pollution from a prior request.
