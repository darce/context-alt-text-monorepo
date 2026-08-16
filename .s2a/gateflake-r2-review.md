# gateflake-r2 FAIL — poll does not observe a committed RUNNING row

**Lane:** `gateflake-reviewer`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Subject:** s2 fallback — does the poll-for-RUNNING observe a COMMITTED row on a StaticPool shared connection?
**Posture:** adversarial. s2 report assumed optimistic. Probe first, batteries only if the commit barrier is real.
**Sandbox note:** this checkout is history-stripped (`87469e5`). `de473ece` / parent `cca32ad1` are not present as distinct SHAs. Review is of the current tree contents matching the claimed fallback (file-backed `_sessionmaker` + `poolclass=StaticPool`, timeout `0.5`, cancel test polls for `RUNNING`).

**Verdict:** fail

---

## Step 1 — does session B see session A's uncommitted write?

**Answer: yes, on the same StaticPool construction the fixture uses. High finding.**

`_sessionmaker` is `create_async_engine(sqlite+aiosqlite:///{tmpdir}/test.db, poolclass=StaticPool)`. Phase-1 `mark_item(RUNNING)` flushes then `session.commit()` (`describe_async_worker.py:192-213`). The cancel test poll is `_load_item(sf, ...)` (`test_describe_async_worker.py:489`), a second `sf()` session. The comment at `:485-486` claims that poll waits for the **committed** `RUNNING` row.

Standalone probe (not pytest): same engine construction; session A `add`+`flush` a `RUNNING` row and does **not** commit; session B is a separate `sf()` checkout and SELECTs. Then the same script with `poolclass` omitted.

### Raw output — visibility + connection ids

```
----- StaticPool (same as _sessionmaker) -----
========================================================================
use_static=True
pool=StaticPool
url=sqlite+aiosqlite:////tmp/acx-probe-4i39qspw/test.db
A session_id=252781409768448
A raw_id=252781426334640 raw_type=_ConnectionFairy
A driver_id=252781426255216 driver_type=Connection
A sqlite3_id=252781400911888 sqlite3_type=Connection
B session_id=252781420168448
B raw_id=252781426331568 raw_type=_ConnectionFairy
B driver_id=252781426255216 driver_type=Connection
B sqlite3_id=252781400911888 sqlite3_type=Connection
same_raw=False
same_driver=True
same_sqlite3=True
B_sees_uncommitted=True status='RUNNING'
B_raw_count=1
----- poolclass omitted (default file URL) -----
========================================================================
use_static=False
pool=AsyncAdaptedQueuePool
url=sqlite+aiosqlite:////tmp/acx-probe-xhp_4syi/test.db
A session_id=252781417156336
A raw_id=252781426331568 raw_type=_ConnectionFairy
A driver_id=252781426257328 driver_type=Connection
A sqlite3_id=252781399182208 sqlite3_type=Connection
B session_id=252781398579904
B raw_id=252781426328784 raw_type=_ConnectionFairy
B driver_id=252781398582064 driver_type=Connection
B sqlite3_id=252781399185088 sqlite3_type=Connection
same_raw=False
same_driver=False
same_sqlite3=False
B_sees_uncommitted=False status=None
B_raw_count=0
```

Fairy wrappers differ (`same_raw=False`). The aiosqlite driver `Connection` and the inner `sqlite3.Connection` are **the same object** under StaticPool (`same_driver=True same_sqlite3=True`). B sees A's uncommitted `RUNNING`. Contrast with default `AsyncAdaptedQueuePool`: different driver/sqlite3 ids, B does **not** see the row.

### Follow-up — B's `async with sf()` close rolls A back

`_load_item` is `async with sf() as s: return await repo.get_single_run_item(...)`. If that close issues rollback on the shared connection, the poll does not merely *see* a dirty write — it can **undo** phase-1.

```
A flushed RUNNING, not committed
B_inside sees=True status='RUNNING'
B_in_transaction=True A_in_transaction=True
B context exited (default session close)
A_after_B_exit sees=False status=None
A_in_transaction_after_B=True
A_commit=ok
C_after_A_commit sees=False status=None
```

After B exits, A's flushed row is gone. A's later `commit()` succeeds and persists nothing. A third session does not see `RUNNING`.

### Interpretation

The poll comment is false. On this fixture, `_load_item` is not a commit barrier. It dirty-reads the worker's flush on the shared sqlite3 connection, then its session close can roll that flush back. Cancel can therefore land inside the phase-1 write window the fallback claims to avoid. Default QueuePool (poolclass omitted) does **not** leak the dirty row — the leak is StaticPool sharing one connection.

s2's 10/10 cancel-test greens do not prove the poll observed a committed row. They are consistent with "usually missed the flush-to-commit window." The comment at `:485-486` must not keep asserting committed-ness.

### Finding

### GATEFLAKE-R2-01 — high

**File:line:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py:482-497` (poll comment `:485-486`; `_load_item` `:124-126`); fixture `poolclass=StaticPool` at `:57-60`. Worker phase-1 flush then commit at `scene/application/describe_async_worker.py:192-213` (not edited).

**Evidence + impact:** Standalone probe on the same `_sessionmaker` construction: session A flush-without-commit of `RUNNING`; session B via a second `sf()` sees `B_sees_uncommitted=True status='RUNNING'` and shares `driver_id` / `sqlite3_id`. Same probe with `poolclass` omitted (`AsyncAdaptedQueuePool`) yields `B_sees_uncommitted=False`. Follow-up: B's `async with` exit leaves A unable to persist — `C_after_A_commit sees=False`. The poll is a dirty read on a shared connection, not a commit barrier. s2's "wait for the committed RUNNING row" is not what the test can know.

**Failure scenario:** Worker has flushed `mark_item(RUNNING)` and not yet `session.commit()`. Poll `_load_item` checks out the StaticPool connection, sees `RUNNING`, returns, session close rolls back the shared transaction. Test breaks out of the wait loop and `task.cancel()`s inside the phase-1 write. `_mark_terminal` then hits the R1-01 lock / `queued` path the fallback was written to avoid — or the RUNNING write is silently discarded and the item stays `queued`. Idle 10/10 can still pass if the poll misses the flush-to-commit window.

---

## Step 2 — headroom on `job_timeout_seconds=0.5`

**Load:** 6× `python3 -c 'while True: x = 1234567 * 7654321'` (PIDs 950834–950839, sampled 26–53% each; `nproc=4`). Burners still up.

**What was timed:** standalone script (not pytest) using the test's `_sessionmaker` / `_create_run` / `_Adapter`. Clock starts immediately before `run_async_describe_job`. First wrapped `session.commit()` after `mark_item(RUNNING)` is phase-1. Adapter `delay_s=0.0` and `job_timeout_seconds=None` so the number is the write, not the 2.0s CPU sleep the timeout test races against.

### Raw samples (n=15)

```
phase1_samples=15
SAMPLE 1 commit_s=0.095807 mark_s=0.091652 flush_s=0.091649
SAMPLE 2 commit_s=0.031867 mark_s=0.027234 flush_s=0.027231
SAMPLE 3 commit_s=0.031349 mark_s=0.027423 flush_s=0.027420
SAMPLE 4 commit_s=0.086446 mark_s=0.082610 flush_s=0.082607
SAMPLE 5 commit_s=0.029425 mark_s=0.025838 flush_s=0.025836
SAMPLE 6 commit_s=0.083520 mark_s=0.078754 flush_s=0.078751
SAMPLE 7 commit_s=0.027089 mark_s=0.022849 flush_s=0.022847
SAMPLE 8 commit_s=0.078076 mark_s=0.073827 flush_s=0.073825
SAMPLE 9 commit_s=0.064783 mark_s=0.060568 flush_s=0.060566
SAMPLE 10 commit_s=0.085865 mark_s=0.079237 flush_s=0.079234
SAMPLE 11 commit_s=0.083426 mark_s=0.077966 flush_s=0.077963
SAMPLE 12 commit_s=0.032488 mark_s=0.027588 flush_s=0.027585
SAMPLE 13 commit_s=0.082921 mark_s=0.077167 flush_s=0.077164
SAMPLE 14 commit_s=0.077785 mark_s=0.073830 flush_s=0.073827
SAMPLE 15 commit_s=0.031330 mark_s=0.025582 flush_s=0.025579
SUMMARY n=15 min=0.027089 median=0.077785 max=0.095807 mean=0.061478 margin_to_0.5=0.404193
```

**min / median / max commit:** 0.027s / 0.078s / 0.096s. **Margin to 0.5s:** 0.404s (max). Flush and mark-return sit ~4ms before commit; the flush-to-commit window the poll can dirty-read is a few milliseconds.

**Is the margin thin?** Not on this 4-CPU sandbox under this load. 0.5s is ~5× the worst of 15 samples. I would not retune 0.5 from this data. Caveats that keep this from licensing "0.5 is safe": n=15 is not a tail; `d866e144` also picked 0.5 and later lost; this clock excludes pytest/import/`wait_for` overhead; a worse host could eat the 404ms. Separately, **0.05 would have been inside this distribution** (max 96ms > 50ms) — that matches R1-01 and does not need re-litigating.

The 0.5s timeout path is a different mechanism from the poll. Step 1 already falsifies the poll's committed-ness claim. Step 2 does not rehabilitate the comment.

---

## Step 3 — 25 under-load runs of `test_worker_timeout_marks_failed_exactly_once`

**Load:** same 6 burners (PIDs 950834–950839) still up.
**Command:** `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_describe_async_worker.py::test_worker_timeout_marks_failed_exactly_once -q -p no:randomly --tb=short`
No retries.

### Runs 1–5

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 7.53s
RESULT 1 PASS
ELAPSED 1 12.0
===== RUN 2 =====
.                                                                        [100%]
1 passed in 7.38s
RESULT 2 PASS
ELAPSED 2 11.81
===== RUN 3 =====
.                                                                        [100%]
1 passed in 7.31s
RESULT 3 PASS
ELAPSED 3 13.1
===== RUN 4 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 4 PASS
ELAPSED 4 11.72
===== RUN 5 =====
.                                                                        [100%]
1 passed in 7.88s
RESULT 5 PASS
ELAPSED 5 12.95
```

Tally so far: 5 PASS / 0 FAIL.

### Runs 6–10

```
===== RUN 6 =====
.                                                                        [100%]
1 passed in 7.50s
RESULT 6 PASS
ELAPSED 6 12.71
===== RUN 7 =====
.                                                                        [100%]
1 passed in 7.41s
RESULT 7 PASS
ELAPSED 7 11.22
===== RUN 8 =====
.                                                                        [100%]
1 passed in 11.90s
RESULT 8 PASS
ELAPSED 8 17.0
===== RUN 9 =====
.                                                                        [100%]
1 passed in 7.59s
RESULT 9 PASS
ELAPSED 9 12.08
===== RUN 10 =====
.                                                                        [100%]
1 passed in 7.31s
RESULT 10 PASS
ELAPSED 10 11.63
```

Tally so far: 10 PASS / 0 FAIL.

### Runs 11–15

```
===== RUN 11 =====
.                                                                        [100%]
1 passed in 12.90s
RESULT 11 PASS
ELAPSED 11 18.89
===== RUN 12 =====
.                                                                        [100%]
1 passed in 7.38s
RESULT 12 PASS
ELAPSED 12 11.76
===== RUN 13 =====
.                                                                        [100%]
1 passed in 7.50s
RESULT 13 PASS
ELAPSED 13 12.01
===== RUN 14 =====
.                                                                        [100%]
1 passed in 7.91s
RESULT 14 PASS
ELAPSED 14 12.32
===== RUN 15 =====
.                                                                        [100%]
1 passed in 7.67s
RESULT 15 PASS
ELAPSED 15 12.18
```

Tally so far: 15 PASS / 0 FAIL.

### Runs 16–20

```
===== RUN 16 =====
.                                                                        [100%]
1 passed in 7.47s
RESULT 16 PASS
ELAPSED 16 11.83
===== RUN 17 =====
.                                                                        [100%]
1 passed in 12.51s
RESULT 17 PASS
ELAPSED 17 21.39
===== RUN 18 =====
.                                                                        [100%]
1 passed in 7.96s
RESULT 18 PASS
ELAPSED 18 12.62
===== RUN 19 =====
.                                                                        [100%]
1 passed in 8.10s
RESULT 19 PASS
ELAPSED 19 12.51
===== RUN 20 =====
.                                                                        [100%]
1 passed in 9.79s
RESULT 20 PASS
ELAPSED 20 14.91
```

Tally so far: 20 PASS / 0 FAIL.

### Runs 21–25

```
===== RUN 21 =====
.                                                                        [100%]
1 passed in 7.40s
RESULT 21 PASS
ELAPSED 21 11.12
===== RUN 22 =====
.                                                                        [100%]
1 passed in 10.16s
RESULT 22 PASS
ELAPSED 22 16.97
===== RUN 23 =====
.                                                                        [100%]
1 passed in 7.50s
RESULT 23 PASS
ELAPSED 23 14.8
===== RUN 24 =====
.                                                                        [100%]
1 passed in 7.51s
RESULT 24 PASS
ELAPSED 24 14.72
===== RUN 25 =====
.                                                                        [100%]
1 passed in 7.59s
RESULT 25 PASS
ELAPSED 25 12.12
```

**Tally A: 25 PASS / 0 FAIL.** No run retried. This battery does **not** rehabilitate the poll comment. The timeout test uses `wait_for(0.5)` vs a 2.0s adapter delay, not `_load_item`. 25/25 under this load is consistent with step 2's 404ms margin. It is not evidence that the cancel-test poll observes a committed row.

Burners 950834–950839 killed after run 25. `pgrep` after kill: none.

---

## Verdict

`fail`

The one question this review had to answer: **does the poll observe a committed `RUNNING` row?** No. On the fixture's StaticPool, a second `sf()` session sees the worker's uncommitted flush and can roll it back on close. The comment at `:485-486` is false. s2's 10/10 cancel greens do not prove a commit barrier.

The 0.5s timeout retune is a different mechanism. On this 4-CPU box under the same 6 burners, phase-1 commit is 27–96ms (margin 0.404s) and `test_worker_timeout_marks_failed_exactly_once` is 25/25. I am not filing a finding against 0.5s from this data. I am failing the fallback because its *stated* cancel-test mechanism is not what it claims.

---

## What I checked and found clean

- `scene/application/describe_async_worker.py` was not edited. Phase-1 is a short session: `mark_item` flush then `session.commit()` at `:213`.
- Default file URL without `poolclass` (`AsyncAdaptedQueuePool`) does **not** leak uncommitted writes. The leak is StaticPool sharing one sqlite3 connection, not file-backed SQLite itself.
- Phase-1 flush-to-commit gap is ~4ms. That is why a dirty-read poll can still go 10/10: it usually misses the window. Luck is not a barrier.
- `/tmp/acx-describe-async-*` after the battery: no such file. (One unrelated `/tmp/acx-probe-6a6a062640c94` dated Jul 29, owner `ubuntu`, is not from this session.)
- Scope of this review: only `.s2a/gateflake-r2-review.md`. Did not touch the test file, the worker, sibling reports, or MCP findings.
