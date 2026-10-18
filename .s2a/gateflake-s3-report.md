# s3 — GATEFLAKE-R2-01 real commit barrier

**Verdict:** PASS

**Lane:** `gateflake-runner`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Approach:** Drop `poolclass=StaticPool`; file URL + default `AsyncAdaptedQueuePool`. Register `sleep_ms` on `engine.sync_engine` `connect`. Keep `job_timeout_seconds=0.5`. Rewrite the cancel-test poll comment as a genuine commit barrier.

Canon: **TEST-08**, **TEST-16**, **TEST-15**, **REF-25**, **CON-17**.

---

## Progress

- Report stub created.
- Code committed (sandbox SHA, unresolvable at destination per VLM6-S2A-F3-02;
  landed as destination `a7def04e48723c70b100047ed8f41c7755a8c7a8`) — drop
  StaticPool, connect-listener `sleep_ms`, rewrite comments. R1-03
  `TimeoutError` message kept; with the listener it should be unreachable.

## Step 1 — the barrier is real

Probe used the **shipped** `_sessionmaker` (not a hand-built engine). Session A `mark_item(RUNNING)` flush, no commit. Session B a second `sf()` `get_single_run_item`.

```
----- shipped _sessionmaker -----
pool=AsyncAdaptedQueuePool
url=sqlite+aiosqlite:////tmp/acx-describe-async-pie0utv_/test.db
A session_id=281140343955360
A raw_id=281140326369904 raw_type=_ConnectionFairy
A driver_id=281140336806656 driver_type=Connection
A sqlite3_id=281140336857856 sqlite3_type=Connection
B session_id=281140348642384
B raw_id=281140326696624 raw_type=_ConnectionFairy
B driver_id=281140326654672 driver_type=Connection
B sqlite3_id=281140326468960 sqlite3_type=Connection
same_raw=False
same_driver=False
same_sqlite3=False
B_sees_uncommitted=False status='queued'
```

`same_sqlite3=False` and `B_sees_uncommitted=False`. B sees the last committed `queued` row, not A's uncommitted `RUNNING`. Decisive step passed.

## Step 3 — TEST-15 discrimination

Temporarily reverted `_sessionmaker` to `sqlite+aiosqlite:///:memory:` (uncommitted). Restore confirmed by clean `git status` after GREEN.

**RED** (`:memory:`)

```
FAILED scene/tests/test_describe_async_worker.py::test_sessionmaker_survives_cancelled_in_flight_query - sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
1 failed in 2.40s
```

**GREEN** (file URL + QueuePool restored)

```
.                                                                        [100%]
1 passed in 1.86s
```

## Step 4 — under load (6 CPU burners, TEST-08 / CON-17)

Load: 6× `python3 -c 'while True: x = 1234567 * 7654321'` (PIDs 977077–977082, `nproc=4`). No retries.

### `test_worker_cancellation_marks_failed_then_re_raises` — 25/25 PASS

```
===== CANCEL RUN 1 =====
.                                                                        [100%]
1 passed in 10.40s
RESULT 1 PASS
ELAPSED 1 14.73
===== CANCEL RUN 2 =====
.                                                                        [100%]
1 passed in 12.98s
RESULT 2 PASS
ELAPSED 2 19.51
===== CANCEL RUN 3 =====
.                                                                        [100%]
1 passed in 10.40s
RESULT 3 PASS
ELAPSED 3 16.21
===== CANCEL RUN 4 =====
.                                                                        [100%]
1 passed in 12.92s
RESULT 4 PASS
ELAPSED 4 19.48
===== CANCEL RUN 5 =====
.                                                                        [100%]
1 passed in 12.49s
RESULT 5 PASS
ELAPSED 5 17.67
===== CANCEL RUN 6 =====
.                                                                        [100%]
1 passed in 10.31s
RESULT 6 PASS
ELAPSED 6 14.72
===== CANCEL RUN 7 =====
.                                                                        [100%]
1 passed in 10.61s
RESULT 7 PASS
ELAPSED 7 15.13
===== CANCEL RUN 8 =====
.                                                                        [100%]
1 passed in 10.49s
RESULT 8 PASS
ELAPSED 8 14.93
===== CANCEL RUN 9 =====
.                                                                        [100%]
1 passed in 13.22s
RESULT 9 PASS
ELAPSED 9 18.44
===== CANCEL RUN 10 =====
.                                                                        [100%]
1 passed in 12.51s
RESULT 10 PASS
ELAPSED 10 17.33
===== CANCEL RUN 11 =====
.                                                                        [100%]
1 passed in 10.40s
RESULT 11 PASS
ELAPSED 11 14.8
===== CANCEL RUN 12 =====
.                                                                        [100%]
1 passed in 10.50s
RESULT 12 PASS
ELAPSED 12 14.82
===== CANCEL RUN 13 =====
.                                                                        [100%]
1 passed in 10.77s
RESULT 13 PASS
ELAPSED 13 15.62
===== CANCEL RUN 14 =====
.                                                                        [100%]
1 passed in 12.93s
RESULT 14 PASS
ELAPSED 14 18.0
===== CANCEL RUN 15 =====
.                                                                        [100%]
1 passed in 10.54s
RESULT 15 PASS
ELAPSED 15 15.0
===== CANCEL RUN 16 =====
.                                                                        [100%]
1 passed in 13.00s
RESULT 16 PASS
ELAPSED 16 18.07
===== CANCEL RUN 17 =====
.                                                                        [100%]
1 passed in 10.10s
RESULT 17 PASS
ELAPSED 17 15.19
===== CANCEL RUN 18 =====
.                                                                        [100%]
1 passed in 10.43s
RESULT 18 PASS
ELAPSED 18 16.39
===== CANCEL RUN 19 =====
.                                                                        [100%]
1 passed in 10.60s
RESULT 19 PASS
ELAPSED 19 15.09
===== CANCEL RUN 20 =====
.                                                                        [100%]
1 passed in 10.51s
RESULT 20 PASS
ELAPSED 20 14.92
===== CANCEL RUN 21 =====
.                                                                        [100%]
1 passed in 9.99s
RESULT 21 PASS
ELAPSED 21 14.21
===== CANCEL RUN 22 =====
.                                                                        [100%]
1 passed in 10.37s
RESULT 22 PASS
ELAPSED 22 15.42
===== CANCEL RUN 23 =====
.                                                                        [100%]
1 passed in 10.40s
RESULT 23 PASS
ELAPSED 23 14.79
===== CANCEL RUN 24 =====
.                                                                        [100%]
1 passed in 10.42s
RESULT 24 PASS
ELAPSED 24 15.69
===== CANCEL RUN 25 =====
.                                                                        [100%]
1 passed in 10.55s
RESULT 25 PASS
ELAPSED 25 14.98
```

Failures: none.

### Step 2 — `_load_item` `database is locked` during the poll

Instrument: poll `except` prints `GATEFLAKE-S3-LOCK` then re-raises (no retry).

Occurrences over the 25 cancel runs: **0**. No `GATEFLAKE-S3-LOCK` line, no `database is locked` in any cancel transcript.

### `test_worker_timeout_marks_failed_exactly_once` — 25/25 PASS

```
===== TIMEOUT RUN 1 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 1 PASS
ELAPSED 1 11.89
===== TIMEOUT RUN 2 =====
.                                                                        [100%]
1 passed in 8.06s
RESULT 2 PASS
ELAPSED 2 12.62
===== TIMEOUT RUN 3 =====
.                                                                        [100%]
1 passed in 7.53s
RESULT 3 PASS
ELAPSED 3 12.79
===== TIMEOUT RUN 4 =====
.                                                                        [100%]
1 passed in 4.89s
RESULT 4 PASS
ELAPSED 4 9.1
===== TIMEOUT RUN 5 =====
.                                                                        [100%]
1 passed in 7.49s
RESULT 5 PASS
ELAPSED 5 12.01
===== TIMEOUT RUN 6 =====
.                                                                        [100%]
1 passed in 7.52s
RESULT 6 PASS
ELAPSED 6 13.98
===== TIMEOUT RUN 7 =====
.                                                                        [100%]
1 passed in 7.61s
RESULT 7 PASS
ELAPSED 7 12.1
===== TIMEOUT RUN 8 =====
.                                                                        [100%]
1 passed in 7.39s
RESULT 8 PASS
ELAPSED 8 12.72
===== TIMEOUT RUN 9 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 9 PASS
ELAPSED 9 11.88
===== TIMEOUT RUN 10 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 10 PASS
ELAPSED 10 11.78
===== TIMEOUT RUN 11 =====
.                                                                        [100%]
1 passed in 7.47s
RESULT 11 PASS
ELAPSED 11 11.78
===== TIMEOUT RUN 12 =====
.                                                                        [100%]
1 passed in 7.90s
RESULT 12 PASS
ELAPSED 12 12.58
===== TIMEOUT RUN 13 =====
.                                                                        [100%]
1 passed in 7.30s
RESULT 13 PASS
ELAPSED 13 11.62
===== TIMEOUT RUN 14 =====
.                                                                        [100%]
1 passed in 7.29s
RESULT 14 PASS
ELAPSED 14 11.69
===== TIMEOUT RUN 15 =====
.                                                                        [100%]
1 passed in 7.59s
RESULT 15 PASS
ELAPSED 15 13.47
===== TIMEOUT RUN 16 =====
.                                                                        [100%]
1 passed in 9.40s
RESULT 16 PASS
ELAPSED 16 13.63
===== TIMEOUT RUN 17 =====
.                                                                        [100%]
1 passed in 7.60s
RESULT 17 PASS
ELAPSED 17 11.89
===== TIMEOUT RUN 18 =====
.                                                                        [100%]
1 passed in 7.37s
RESULT 18 PASS
ELAPSED 18 13.07
===== TIMEOUT RUN 19 =====
.                                                                        [100%]
1 passed in 7.46s
RESULT 19 PASS
ELAPSED 19 11.81
===== TIMEOUT RUN 20 =====
.                                                                        [100%]
1 passed in 9.89s
RESULT 20 PASS
ELAPSED 20 14.96
===== TIMEOUT RUN 21 =====
.                                                                        [100%]
1 passed in 7.40s
RESULT 21 PASS
ELAPSED 21 12.9
===== TIMEOUT RUN 22 =====
.                                                                        [100%]
1 passed in 7.49s
RESULT 22 PASS
ELAPSED 22 12.02
===== TIMEOUT RUN 23 =====
.                                                                        [100%]
1 passed in 10.07s
RESULT 23 PASS
ELAPSED 23 15.2
===== TIMEOUT RUN 24 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 24 PASS
ELAPSED 24 11.88
===== TIMEOUT RUN 25 =====
.                                                                        [100%]
1 passed in 5.51s
RESULT 25 PASS
ELAPSED 25 9.91
```

Failures: none.

```
===== SUMMARY =====
cancel 25/25 pass 0 fail lock_hits=0
timeout 25/25 pass 0 fail
burners killed
```

## Step 5 — full file 10× idle

`cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_describe_async_worker.py -q -p no:randomly`

```
===== IDLE FILE RUN 1 =====
...........                                                              [100%]
11 passed in 12.32s
RESULT 1 PASS
===== IDLE FILE RUN 2 =====
...........                                                              [100%]
11 passed in 12.32s
RESULT 2 PASS
===== IDLE FILE RUN 3 =====
...........                                                              [100%]
11 passed in 12.29s
RESULT 3 PASS
===== IDLE FILE RUN 4 =====
...........                                                              [100%]
11 passed in 12.29s
RESULT 4 PASS
===== IDLE FILE RUN 5 =====
...........                                                              [100%]
11 passed in 12.27s
RESULT 5 PASS
===== IDLE FILE RUN 6 =====
...........                                                              [100%]
11 passed in 12.20s
RESULT 6 PASS
===== IDLE FILE RUN 7 =====
...........                                                              [100%]
11 passed in 12.31s
RESULT 7 PASS
===== IDLE FILE RUN 8 =====
...........                                                              [100%]
11 passed in 12.52s
RESULT 8 PASS
===== IDLE FILE RUN 9 =====
...........                                                              [100%]
11 passed in 12.31s
RESULT 9 PASS
===== IDLE FILE RUN 10 =====
...........                                                              [100%]
11 passed in 12.27s
RESULT 10 PASS
idle 10x 10/10 pass 0 fail
```

## Step 6 — temp dir leak check

After batteries and after the 10× idle:

```
count=0
no leaked temp dirs
```

`find /tmp -maxdepth 1 -name 'acx-describe-async-*'` empty. Burners gone (`pgrep` no match).

No steps dropped.

## Final diffs (destination `a7def04e48723c70b100047ed8f41c7755a8c7a8`)

`_sessionmaker`:

```
-async def _sessionmaker():
-    # File-backed + StaticPool: ...
-    engine = create_async_engine(
-        f"sqlite+aiosqlite:///{path}",
-        poolclass=StaticPool,
-    )
+async def _sessionmaker(*, sleep_ms=None):
+    # File-backed SQLite, default AsyncAdaptedQueuePool. The file keeps
+    # the schema when a cancelled aiosqlite query invalidates a connection
+    # (s1). QueuePool gives real commit isolation: sessions do not share a
+    # sqlite3 connection, so a second session cannot dirty-read or roll
+    # back another session's uncommitted flush (GATEFLAKE-R2-01). sleep_ms
+    # is registered on every checkout via a connect listener (GATEFLAKE-R1-03).
+    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
+
+    def _sleep_ms(ms: object) -> int:
+        if sleep_ms is not None:
+            return sleep_ms(ms)
+        time.sleep(float(ms) / 1000.0)
+        return 1
+
+    @event.listens_for(engine.sync_engine, "connect")
+    def _register_sleep_ms(dbapi_connection, _connection_record) -> None:
+        dbapi_connection.create_function("sleep_ms", 1, _sleep_ms)
```

Timeout comment (REF-25; StaticPool claims removed; r2b distribution cited):

```
             # FALLBACK (REF-25 / GATEFLAKE-R1-01): 0.05 fires inside
-            # phase-1 mark_item(RUNNING). The cancelled aiosqlite
-            # connection still holds the SQLite write lock; StaticPool
-            # replacement then fails _mark_terminal with database is
-            # locked (23/25 and 8/10 under 6 CPU burners; busy_timeout
-            # self-deadlocks because the holder is the dying checkout).
-            # 0.5 lets phase-1 commit before wait_for cancels, so
-            # cleanup is not fighting a live writer. Production is
-            # Postgres. Do not silently retune this.
+            # phase-1 mark_item(RUNNING). A cancelled aiosqlite
+            # connection can still hold the SQLite write lock; a
+            # replacement checkout then fails _mark_terminal with
+            # database is locked (measured under 6 CPU burners;
+            # busy_timeout self-deadlocks because the holder is the
+            # dying checkout). r2b timed phase-1 commit at min 0.027s
+            # / median 0.078s / max 0.096s (n=15 under 6 burners) —
+            # 0.404s margin to 0.5. 0.5 lets phase-1 commit before
+            # wait_for cancels. Production is Postgres. Do not
+            # silently retune this.
             job_timeout_seconds=0.5,
```

Cancel-test poll comment (now a real commit barrier):

```
-        # FALLBACK (REF-25 / GATEFLAKE-R1-02): sleep(0.05) lands inside
-        # phase-1's RUNNING write under load. Same lock race as the
-        # timeout test — dying aiosqlite holds the file lock, cleanup
-        # cannot persist FAILED. Wait for the committed RUNNING row
-        # so cancel is after that write, not a magic longer sleep.
+        # Commit barrier (GATEFLAKE-R2-01): _sessionmaker is file-backed
+        # QueuePool, so this _load_item session is a different sqlite3
+        # connection and cannot dirty-read or roll back the worker's
+        # uncommitted flush. Seeing RUNNING means phase-1 committed.
+        # Cancel after that write, not mid-write (GATEFLAKE-R1-01 lock
+        # race). Measured hedge: poll may block or raise database is
+        # locked if the worker still holds the write lock.
```

R1-03 `TimeoutError` message kept verbatim. Listener is on every checkout; that message should now be unreachable.

Production `describe_async_worker.py` not touched.
