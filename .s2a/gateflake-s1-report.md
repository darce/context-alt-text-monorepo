# gateflake-s1 — file-backed SQLite fixture

**Lane:** `gateflake-runner`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Scope:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py` only
**Verdict:** PASS. Fixture defect is gone. Discrimination guard is permanent.

Canon IDs: **TEST-08**, **TEST-07**, **CON-17**, **DBG-01**, **TEST-09**, **TEST-15**.

## Verdict

`_sessionmaker` now uses file-backed `sqlite+aiosqlite` (`AsyncAdaptedQueuePool`). Cancelling an in-flight aiosqlite await no longer destroys the schema. Production is Postgres; this restores that semantic in-process (TEST-09: not a unit test, not a container).

No production code (`scene/application/`) was touched.

## Temp-file lifetime

**Mechanism:** `tempfile.TemporaryDirectory(prefix="acx-describe-async-")` holding `test.db`. Cleanup is bound to the engine two ways:

1. `event.listen(engine.sync_engine, "engine_disposed", _cleanup)` — tests already `await engine.dispose()`; this is the happy-path delete.
2. `weakref.finalize(engine, _cleanup)` — if a test fails before `dispose`, GC still deletes the dir. `TemporaryDirectory.cleanup()` is idempotent.

**Why not a pytest fixture:** the contract is keep the 2-tuple `engine, sf = await _sessionmaker()`. A fixture would rewrite every call site.

**Why not wrap `engine.dispose`:** `AsyncEngine.dispose` is read-only.

**Leak check:** after the green guard run, `ls /tmp/acx-describe-async-*` → no leftover dirs.

## Diff

```
async def _sessionmaker():
    # File-backed: StaticPool :memory: is destroyed when a cancelled
    # aiosqlite query invalidates the sole connection.
    tmpdir = tempfile.TemporaryDirectory(prefix="acx-describe-async-")
    path = os.path.join(tmpdir.name, "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")

    def _cleanup(_eng: object = None) -> None:
        tmpdir.cleanup()

    event.listen(engine.sync_engine, "engine_disposed", _cleanup)
    weakref.finalize(engine, _cleanup)
    ... create_all ...
    return engine, async_sessionmaker(engine, expire_on_commit=False)
```

Arity unchanged. New permanent test: `test_sessionmaker_survives_cancelled_in_flight_query`.

`test_worker_timeout_marks_failed_exactly_once`: `job_timeout_seconds` **0.5 → 0.05** (d866e144 timing dodge reverted).

## Step 1 (DBG-01) — failing transcript on old `:memory:` StaticPool

Guard written first. Cancel is deterministic: aiosqlite `sleep_ms` UDF sets an `asyncio.Event` then sleeps 800ms; the test waits for the event, then cancels mid-await. No worker timing.

3/3 RED before the fixture change:

```
FAILED test_sessionmaker_survives_cancelled_in_flight_query
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
[SQL: SELECT image_description_run_items.id, ... FROM image_description_run_items
 WHERE image_description_run_items.tenant_id = ? AND image_description_run_items.run_id = ? ...]
```

Verbose first run (2.55s):

```
scene/tests/test_describe_async_worker.py::test_sessionmaker_survives_cancelled_in_flight_query FAILED
E   sqlite3.OperationalError: no such table: image_description_run_items
...
scene/tests/test_describe_async_worker.py:150: in body
    item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
...
E   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
============================== 1 failed in 2.55s ===============================
```

Confirm 2 and 3: same `no such table: image_description_run_items` (1.70s, 1.71s). Not intermittent.

Prototype also showed the pool split: `:memory:` → `StaticPool`, subsequent session dies; file URL → `AsyncAdaptedQueuePool`, subsequent session reads 1 row.

## Step 2 — fix + d866e144 revert

File-backed `_sessionmaker` as above. Timeout test restored to `0.05s`. That test stayed green across all verification below — the class is dead. Mid-query cancel no longer drops the schema, so the old 0.5s dodge is unnecessary.

Did **not** raise sleeps, widen other timeouts, or reorder awaits.

## Step 3 — verification

### Guard GREEN after fix

```
.                                                                        [100%]
1 passed in 1.82s
```

### Full file (exact count)

```
cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_describe_async_worker.py -q -p no:randomly
...........                                                              [100%]
11 passed in 12.74s
```

11 tests: 10 existing + the new guard.

### 10 sequential runs (TEST-08)

| run | result |
|-----|--------|
| 1 | 11 passed in 12.26s |
| 2 | 11 passed in 12.26s |
| 3 | 11 passed in 12.21s |
| 4 | 11 passed in 12.19s |
| 5 | 11 passed in 12.22s |
| 6 | 11 passed in 12.31s |
| 7 | 11 passed in 12.20s |
| 8 | 11 passed in 12.21s |
| 9 | 11 passed in 12.21s |
| 10 | 11 passed in 12.32s |

All 10 identical: **11 passed**.

### 3 random-order runs (TEST-07)

Sandbox extras do not install `pytest-randomly` (`importlib` → False). Dropping `-p no:randomly` is a no-op here. Evidence used `uv run --extra dev --with pytest-randomly` (verification-only; not a project dep):

| seed | result |
|------|--------|
| 1 | 11 passed in 12.17s |
| 7 | 11 passed in 12.13s |
| 99 | 11 passed in 12.10s |

Also 3 default-order runs without the disable flag: 11 passed each.

### TEST-15 — uncommitted revert `:memory:` → RED, restore → GREEN

**RED** (`_sessionmaker` temporarily `sqlite+aiosqlite:///:memory:`):

```
FAILED test_sessionmaker_survives_cancelled_in_flight_query
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
1 failed in 1.74s
```

**GREEN** (file-backed restored):

```
.                                                                        [100%]
1 passed in 1.79s
```

Guard discriminates the fixture, not worker timing.

## d866e144 outcome

Reverted `job_timeout_seconds` 0.5 → 0.05 in `test_worker_timeout_marks_failed_exactly_once`. Green on the first full file run and on all 10 sequential + 3 shuffled runs. Safe because the pool no longer dies when cancel lands mid-query.
