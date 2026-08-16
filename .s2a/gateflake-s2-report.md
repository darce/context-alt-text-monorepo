# FALLBACK — GATEFLAKE-R1-01..04. StaticPool does not close the lock window.

**Lane:** `gateflake-runner`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Approach:** FALLBACK. File-backed `StaticPool` kept (schema + UDF identity). `job_timeout_seconds` restored to **0.5**. Cancellation test waits for committed `RUNNING` before cancel. Not a silent retune — comments name the lock race and cite REF-25.
**Verdict:** primary StaticPool+0.05 **FAIL** (23/25 and 8/10). Fallback **PASS** (25/25 and 10/10) under the same 6× CPU burners.

Canon IDs that apply: **TEST-08**, **CON-17**, **TEST-15**, **TEST-16**, **REF-25**.

s1 overstatement: the s1 report called the class dead on 13 **idle** full-file runs. That was wrong. Idle green is not evidence about a load-dependent race (CON-17). Owned below and in the s1 corrections (R1-04).

---

## Measurement — does StaticPool's replacement get the file lock?

No. The dying cancelled aiosqlite connection still holds it.

`type(engine.sync_engine.pool).__name__ == "StaticPool"` on `sqlite+aiosqlite:///{tmpdir}/test.db`. Cancel mid-`mark_item(RUNNING)` invalidates that checkout. StaticPool then hands out a **replacement** connection to the same file. `_mark_terminal` hits `sqlite3.OperationalError: database is locked`. The `CancelledError` handler suppresses it. Item stays `queued`.

This is not "two live pooled connections" (the R1-01 sketch). It is connection replacement after invalidation. Same lock race, one live pool slot.

`connect_args={"timeout": 60}` set `PRAGMA busy_timeout=60000` and still failed: `_mark_terminal` waits on a lock whose holder is the dying checkout in the same cleanup. Self-deadlock. 60s hang then `queued`. Reverted. That is why the named timeout fallback is the remaining test-only fix. Production code (`describe_async_worker.py:317` `contextlib.suppress`) was out of scope.

TEST-16: after the fallback these two tests no longer cancel *inside* phase-1's write. They cancel after `RUNNING` is committed (timeout via 0.5s `wait_for` vs 2.0s CPU delay; cancel test via poll). The worker contract under test is "exactly one FAILED persist after a started job is cancelled", not "FAILED persist when cancel lands mid-SQLite write". Production is Postgres.

---

## What stayed from s1

File-backed `_sessionmaker`. Permanent guard. 2-tuple arity. No production edits. Event+finalize tmpdir lifetime.

TEST-15 (uncommitted `:memory:` revert, then restore), this session:

**RED**

```
FAILED test_sessionmaker_survives_cancelled_in_flight_query
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
1 failed in 2.44s
```

**GREEN** (file + StaticPool restored)

```
.                                                                        [100%]
1 passed in 1.85s
```

Full file after StaticPool (idle): `11 passed in 12.50s`.

---

## GATEFLAKE-R1-03

StaticPool makes `engine.connect()` and later `sf()` the same checkout. UDF `sleep_ms` is therefore on the connection the guard query uses — not LIFO luck. Verified: pool class `StaticPool`, guard GREEN.

Also wrapped `wait_for(started.wait())` so a split checkout fails with:

`sleep_ms UDF never started; UDF is registered on one aiosqlite connection and this session may have checked out a different one`

instead of a bare `TimeoutError`.

---

## GATEFLAKE-R1-04

Corrected `.s2a/gateflake-s1-report.md` in this commit:

1. "`AsyncEngine.dispose` is read-only" is false. It is a plain function. Event+finalize is a choice.
2. Struck "the class is dead" and "Safe because the pool no longer dies". Replaced with what the 13 idle runs actually show: schema survival, not lock-race death.

---

## Commits

- `4fd501526d1572daea55f076bb6772d1bfb18c62` — file URL + `poolclass=StaticPool`, keep 0.05, named UDF timeout
- `bcdb09a5a119e23c44bb0343be124f654aac421b` — fallback after the batteries below failed

---

## Load protocol

6 background processes: `python3 -c 'while True: x = 1234567 * 7654321'`.
4 CPUs. Sampled ~16–53% each (same recipe as the R1 reviewer).
Kill after the fallback batteries. No leftover `/tmp/acx-describe-async-*`.

---

## Primary batteries — StaticPool + `job_timeout_seconds=0.05` — FAIL

Command A: `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_describe_async_worker.py::test_worker_timeout_marks_failed_exactly_once -q -p no:randomly --tb=short`

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 6.37s
RESULT 1 PASS
===== RUN 2 =====
.                                                                        [100%]
1 passed in 5.60s
RESULT 2 PASS
===== RUN 3 =====
.                                                                        [100%]
1 passed in 5.79s
RESULT 3 PASS
===== RUN 4 =====
.                                                                        [100%]
1 passed in 4.98s
RESULT 4 PASS
===== RUN 5 =====
.                                                                        [100%]
1 passed in 3.63s
RESULT 5 PASS
===== RUN 6 =====
.                                                                        [100%]
1 passed in 5.81s
RESULT 6 PASS
===== RUN 7 =====
.                                                                        [100%]
1 passed in 5.50s
RESULT 7 PASS
===== RUN 8 =====
.                                                                        [100%]
1 passed in 6.65s
RESULT 8 PASS
===== RUN 9 =====
.                                                                        [100%]
1 passed in 8.20s
RESULT 9 PASS
===== RUN 10 =====
F                                                                        [100%]
FAILED ... sqlite3.OperationalError: database is locked
  at describe_async_worker.py _mark_terminal / set_item_failed autoflush
1 failed in 24.08s
RESULT 10 FAIL
===== RUN 11 =====
F                                                                        [100%]
FAILED ... assert 'queued' == FAILED
ERROR ... cancellation cleanup failed to persist terminal job state
sqlite3.OperationalError: database is locked
1 failed in 11.28s
RESULT 11 FAIL
===== RUN 12 =====
.                                                                        [100%]
1 passed in 9.07s
RESULT 12 PASS
===== RUN 13 =====
.                                                                        [100%]
1 passed in 3.41s
RESULT 13 PASS
===== RUN 14 =====
.                                                                        [100%]
1 passed in 5.71s
RESULT 14 PASS
===== RUN 15 =====
.                                                                        [100%]
1 passed in 6.17s
RESULT 15 PASS
===== RUN 16 =====
.                                                                        [100%]
1 passed in 5.58s
RESULT 16 PASS
===== RUN 17 =====
.                                                                        [100%]
1 passed in 5.40s
RESULT 17 PASS
===== RUN 18 =====
.                                                                        [100%]
1 passed in 5.60s
RESULT 18 PASS
===== RUN 19 =====
.                                                                        [100%]
1 passed in 8.76s
RESULT 19 PASS
===== RUN 20 =====
.                                                                        [100%]
1 passed in 10.82s
RESULT 20 PASS
===== RUN 21 =====
.                                                                        [100%]
1 passed in 9.19s
RESULT 21 PASS
===== RUN 22 =====
.                                                                        [100%]
1 passed in 4.10s
RESULT 22 PASS
===== RUN 23 =====
.                                                                        [100%]
1 passed in 5.41s
RESULT 23 PASS
===== RUN 24 =====
.                                                                        [100%]
1 passed in 3.07s
RESULT 24 PASS
===== RUN 25 =====
.                                                                        [100%]
1 passed in 7.17s
RESULT 25 PASS
```

**Tally A primary: 23 PASS / 2 FAIL.** Not 25/25. Fail.

Command B: same load, `test_worker_cancellation_marks_failed_then_re_raises` (`asyncio.sleep(0.05)` then cancel).

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 7.26s
RESULT 1 PASS
===== RUN 2 =====
.                                                                        [100%]
1 passed in 5.71s
RESULT 2 PASS
===== RUN 3 =====
F                                                                        [100%]
FAILED ... assert 'queued' == FAILED
ERROR ... cancellation cleanup failed to persist terminal job state
sqlite3.OperationalError: database is locked
1 failed in 11.91s
RESULT 3 FAIL
===== RUN 4 =====
.                                                                        [100%]
1 passed in 10.60s
RESULT 4 PASS
===== RUN 5 =====
F                                                                        [100%]
FAILED ... assert 'queued' == FAILED
ERROR ... cancellation cleanup failed to persist terminal job state
sqlite3.OperationalError: database is locked
1 failed in 11.58s
RESULT 5 FAIL
===== RUN 6 =====
.                                                                        [100%]
1 passed in 8.33s
RESULT 6 PASS
===== RUN 7 =====
.                                                                        [100%]
1 passed in 10.56s
RESULT 7 PASS
===== RUN 8 =====
.                                                                        [100%]
1 passed in 5.61s
RESULT 8 PASS
===== RUN 9 =====
.                                                                        [100%]
1 passed in 12.68s
RESULT 9 PASS
===== RUN 10 =====
.                                                                        [100%]
1 passed in 8.26s
RESULT 10 PASS
```

**Tally B primary: 8 PASS / 2 FAIL.** Not 10/10. Fail. R1-02 was right — same window.

No run was retried to replace a fail.

---

## Fallback batteries — 0.5s timeout + wait-for-RUNNING — PASS

Same 6 burners still up. Code at `bcdb09a5a119e23c44bb0343be124f654aac421b`.

Command A (timeout test, `job_timeout_seconds=0.5`):

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 7.69s
RESULT 1 PASS
===== RUN 2 =====
.                                                                        [100%]
1 passed in 7.19s
RESULT 2 PASS
===== RUN 3 =====
.                                                                        [100%]
1 passed in 7.60s
RESULT 3 PASS
===== RUN 4 =====
.                                                                        [100%]
1 passed in 7.78s
RESULT 4 PASS
===== RUN 5 =====
.                                                                        [100%]
1 passed in 9.78s
RESULT 5 PASS
===== RUN 6 =====
.                                                                        [100%]
1 passed in 7.30s
RESULT 6 PASS
===== RUN 7 =====
.                                                                        [100%]
1 passed in 10.10s
RESULT 7 PASS
===== RUN 8 =====
.                                                                        [100%]
1 passed in 7.38s
RESULT 8 PASS
===== RUN 9 =====
.                                                                        [100%]
1 passed in 7.33s
RESULT 9 PASS
===== RUN 10 =====
.                                                                        [100%]
1 passed in 7.30s
RESULT 10 PASS
===== RUN 11 =====
.                                                                        [100%]
1 passed in 7.31s
RESULT 11 PASS
===== RUN 12 =====
.                                                                        [100%]
1 passed in 9.82s
RESULT 12 PASS
===== RUN 13 =====
.                                                                        [100%]
1 passed in 9.33s
RESULT 13 PASS
===== RUN 14 =====
.                                                                        [100%]
1 passed in 10.01s
RESULT 14 PASS
===== RUN 15 =====
.                                                                        [100%]
1 passed in 7.40s
RESULT 15 PASS
===== RUN 16 =====
.                                                                        [100%]
1 passed in 7.38s
RESULT 16 PASS
===== RUN 17 =====
.                                                                        [100%]
1 passed in 7.50s
RESULT 17 PASS
===== RUN 18 =====
.                                                                        [100%]
1 passed in 8.44s
RESULT 18 PASS
===== RUN 19 =====
.                                                                        [100%]
1 passed in 7.30s
RESULT 19 PASS
===== RUN 20 =====
.                                                                        [100%]
1 passed in 7.99s
RESULT 20 PASS
===== RUN 21 =====
.                                                                        [100%]
1 passed in 7.52s
RESULT 21 PASS
===== RUN 22 =====
.                                                                        [100%]
1 passed in 8.53s
RESULT 22 PASS
===== RUN 23 =====
.                                                                        [100%]
1 passed in 7.34s
RESULT 23 PASS
===== RUN 24 =====
.                                                                        [100%]
1 passed in 7.91s
RESULT 24 PASS
===== RUN 25 =====
.                                                                        [100%]
1 passed in 7.71s
RESULT 25 PASS
```

**Tally A fallback: 25 PASS / 0 FAIL.**

Command B (cancel after committed RUNNING):

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 5.49s
RESULT 1 PASS
===== RUN 2 =====
.                                                                        [100%]
1 passed in 5.55s
RESULT 2 PASS
===== RUN 3 =====
.                                                                        [100%]
1 passed in 10.58s
RESULT 3 PASS
===== RUN 4 =====
.                                                                        [100%]
1 passed in 5.38s
RESULT 4 PASS
===== RUN 5 =====
.                                                                        [100%]
1 passed in 5.59s
RESULT 5 PASS
===== RUN 6 =====
.                                                                        [100%]
1 passed in 5.61s
RESULT 6 PASS
===== RUN 7 =====
.                                                                        [100%]
1 passed in 5.27s
RESULT 7 PASS
===== RUN 8 =====
.                                                                        [100%]
1 passed in 5.51s
RESULT 8 PASS
===== RUN 9 =====
.                                                                        [100%]
1 passed in 5.47s
RESULT 9 PASS
===== RUN 10 =====
.                                                                        [100%]
1 passed in 5.43s
RESULT 10 PASS
```

**Tally B fallback: 10 PASS / 0 FAIL.**

Full file after fallback, burners still on: `11 passed in 12.21s`.

---

## Leak check

After primary A+B, after fallback A+B, and after burner kill:

```
ls -ld /tmp/acx-describe-async-*
ls: cannot access '/tmp/acx-describe-async-*': No such file or directory
```

---

## Scope

Edited: `apps/prototype-description-service/scene/tests/test_describe_async_worker.py`, `.s2a/gateflake-s1-report.md`, this file.

Did not touch `scene/application/describe_async_worker.py`.
