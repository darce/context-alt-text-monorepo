# gateflake-r1 — adversarial review of 818d19f2

**Lane:** `gateflake-reviewer`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Subject:** file-backed SQLite `_sessionmaker` + `job_timeout_seconds` 0.05 revert
**Posture:** adversarial. Report assumed optimistic. Mutations uncommitted and restored after each run.
**Sandbox note:** this checkout is history-stripped (`8778ac8`). Commit `818d19f2` / parent `dcb7c49f` are not present as distinct SHAs. Review is of the current tree contents matching the claimed diff.

## Verdict

`fail`

The discrimination guard does catch `:memory:` StaticPool schema death. The 0.05s timeout revert does **not** survive CPU load: 1/25 runs left the item `queued` because `_mark_terminal` hit `sqlite3.OperationalError: database is locked`. The s1 report's "class is dead" / "safe because the pool no longer dies" claim is false.

---

## Findings

### GATEFLAKE-R1-01 — high

**File:line:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py:313` (`job_timeout_seconds=0.05`); failure asserts at `:320`; worker persist at `scene/application/describe_async_worker.py:176` / suppress at `:317`.

**Evidence + impact:** Reverting d866e144's 0.5s dodge puts cancellation back into phase-1's DB write (`mark_item(RUNNING)`). File-backed `AsyncAdaptedQueuePool` then checks out a *second* connection for `_mark_terminal`. The cancelled aiosqlite connection still holds the SQLite write lock. Cleanup commit raises `database is locked`; the CancelledError handler swallows it (`contextlib.suppress`). The item stays `queued`. Schema is intact (no `no such table`) — the old fixture defect is gone — but the worker contract test is now a SQLite lock flake. The s1 report cited 13 idle green runs and called the class dead. Under six busy-loop processes this lane saw **24 PASS / 1 FAIL** (run 14, 11.09s).

**Failure scenario:** 6× `python3 -c 'while True: x = 1234567 * 7654321'` on the box. Run `test_worker_timeout_marks_failed_exactly_once` with `job_timeout_seconds=0.05` and CPU adapter `delay_s=2.0`. Timeout fires during the phase-1 write. `_mark_terminal` opens a different pooled connection, `session.commit()` raises `OperationalError: database is locked`, cleanup is logged and suppressed, assertion `item.status == FAILED` sees `queued`. Idle CI can stay green; a loaded or slow host reproduces CON-17.

### GATEFLAKE-R1-02 — medium

**File:line:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py:268-334` (`test_worker_timeout_marks_failed_exactly_once`); same substrate used by `test_worker_cancellation_marks_failed_then_re_raises` (`:456` `asyncio.sleep(0.05)`).

**Evidence + impact:** [TEST-16] Passing is not the same as still testing the same thing. Old StaticPool `:memory:` serialized every session on one connection — no cross-connection SQLite lock. New file-backed `AsyncAdaptedQueuePool` (confirmed `type(engine.sync_engine.pool).__name__ == "AsyncAdaptedQueuePool"`) makes concurrent checkout real. The timeout test's meaning shifted from "exactly one FAILED persist after wait_for" to "exactly one FAILED persist *unless* cancel lands mid-write and the other connection loses the lock race." Production is Postgres; this lock failure is fixture-only. `test_worker_records_cpu_provisional_then_gpu_final`, degraded/GPU-fail, cache-session identity, commit-fail rollback, and terminal re-entry still commit-then-open-next-session and do not depend on shared-connection uncommitted visibility.

**Failure scenario:** Same inputs as R1-01. Operator reads a green idle run as proof the worker double-write contract holds. Under load the test fails on `queued` even though the worker's sequential shield+timeout `_mark_terminal` pair is correct — the fixture substrate invented a lock the production DB does not have. Sister test `test_worker_cancellation_marks_failed_then_re_raises` sits in the same 0.05s cancel-during-phase-1 window (not 25-runned here).

### GATEFLAKE-R1-03 — low

**File:line:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py:148-158` (UDF register on `engine.connect()`, then `sf()` execute; `asyncio.wait_for(started.wait(), timeout=3.0)`).

**Evidence + impact:** UDF `sleep_ms` is registered on one aiosqlite connection. Sequential checkout in the current guard *does* reuse that connection (`engine.connect()` and later `sf()` shared `aiosqlite_id`; `SELECT sleep_ms(1)` succeeded). That is pool LIFO/lazy luck, not a guarantee (`pool_size=5`). If `sf()` gets a different connection, the query raises `OperationalError: no such function: sleep_ms`, `started` never sets, and the test fails with a **bare `TimeoutError`** (empty message) from `wait_for`. Probe: hold the UDF connection, let `sf()` open a second — `MISSING_UDF_WAIT_EXC TimeoutError`; task already done with `no such function: sleep_ms`. Same for file-backed `NullPool`. Not a silent pass — a confusing fail. `pytest.raises(CancelledError)` is *not* satisfied by cancelling an already-done task (probe: `DONE_TASK_CANCEL_AWAIT no-exception`). It *is* satisfied by cancelling during session teardown after a completed query (`sleep_ms(0)` still GREEN on file-backed).

**Failure scenario:** Guard setup leaves two pooled connections (or someone sets `poolclass=NullPool`). `sf()` checks out the connection without `sleep_ms`. Test dies at line 158 with `TimeoutError` and no hint that the UDF missed the checkout. A reader debugs "why didn't the UDF start?" instead of "wrong connection."

### GATEFLAKE-R1-04 — low

**File:line:** `.s2a/gateflake-s1-report.md:23-25` ("`AsyncEngine.dispose` is read-only"); `:84` ("the class is dead"); `:157` ("Safe because…").

**Evidence + impact:** Report honesty. (1) `AsyncEngine.dispose` is a plain `function`, not a read-only property; `AsyncEngine.dispose = lambda self: None` succeeded in this venv (SQLAlchemy 2.0.49). Wrapping the instance method remains available; the event+finalize design is a choice, not a language constraint. (2) "13 green runs" are idle full-file passes, not loaded timeout isolation. They do not license "class is dead." (3) TEST-15 `:memory:` RED / restore GREEN transcripts match this lane's reruns; that part is honest.

**Failure scenario:** A later agent treats "dispose is read-only" as a constraint and keeps the dual-cleanup design; or treats "class is dead" as permission to keep `0.05` and merge. The loaded flake (R1-01) then lands on main.

---

## Mutation matrix (angle 1 / TEST-15)

All mutations uncommitted; file restored from `/tmp/test_describe_async_worker.py.orig` after each row. Guard target: `test_sessionmaker_survives_cancelled_in_flight_query`.

| Mutation | Caught? | Transcript |
|----------|---------|------------|
| Baseline file-backed (current) | n/a (GREEN) | `1 passed in 1.90s` then restore-confirm `1 passed in 1.86s` |
| `_sessionmaker` → `sqlite+aiosqlite:///:memory:` | **YES** (RED) | `FAILED` `sqlite3.OperationalError: no such table: image_description_run_items` `1 failed in 2.42s` |
| File-backed + `poolclass=StaticPool` | **NO** (GREEN) | `1 passed in 1.87s` — schema lives in the file; StaticPool invalidation does not drop it |
| File-backed + `sleep_ms(0)` | **NO** (GREEN) | `1 passed in 1.02s` — cancel lands after query / during session teardown; `CancelledError` still raised |
| File-backed + `sleep_ms(1)` | **NO** (GREEN) | `1 passed in 0.98s` |
| File-backed + `sleep_ms(50)` | **NO** (GREEN) | `1 passed in 1.03s` |
| File-backed + `sleep_ms(100)` | **NO** (GREEN) | `1 passed in 1.11s` |
| `:memory:` + `sleep_ms(0)` | **YES** (RED) | `no such table: image_description_run_items` `1 failed in 0.96s` — even teardown-cancel kills `:memory:` |
| `:memory:` + `sleep_ms(1)` | **YES** (RED) | same `no such table` `1 failed in 0.94s` |
| File-backed + `NullPool` (probe, not pytest) | loud fail, wrong reason | `NULLPOOL_WAIT_EXC TimeoutError` + `no such function: sleep_ms` — does not reach schema check |

Guard **does** discriminate the claimed fixture defect (`:memory:` StaticPool). It does **not** discriminate pool class on a file URL. Shortening the UDF sleep does **not** silently accept a broken `:memory:` fixture, but it also does **not** prove the cancel was mid-query.

---

## 25 under-load runs (angle 4 / CON-17)

**Load:** 6 background processes, each `python3 -c 'while True: x = 1234567 * 7654321'`.
**Command:** `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_describe_async_worker.py::test_worker_timeout_marks_failed_exactly_once -q -p no:randomly --tb=short`
**Sampled burner CPU:** PIDs 864325–864333 at ~15–53% each.

Verbatim per-run results:

```
===== RUN 1 =====
.                                                                        [100%]
1 passed in 5.50s
RESULT 1 PASS
===== RUN 2 =====
.                                                                        [100%]
1 passed in 5.61s
RESULT 2 PASS
===== RUN 3 =====
.                                                                        [100%]
1 passed in 5.11s
RESULT 3 PASS
===== RUN 4 =====
.                                                                        [100%]
1 passed in 5.56s
RESULT 4 PASS
===== RUN 5 =====
.                                                                        [100%]
1 passed in 5.39s
RESULT 5 PASS
===== RUN 6 =====
.                                                                        [100%]
1 passed in 5.88s
RESULT 6 PASS
===== RUN 7 =====
.                                                                        [100%]
1 passed in 7.36s
RESULT 7 PASS
===== RUN 8 =====
.                                                                        [100%]
1 passed in 5.48s
RESULT 8 PASS
===== RUN 9 =====
.                                                                        [100%]
1 passed in 2.99s
RESULT 9 PASS
===== RUN 10 =====
.                                                                        [100%]
1 passed in 5.39s
RESULT 10 PASS
===== RUN 11 =====
.                                                                        [100%]
1 passed in 5.60s
RESULT 11 PASS
===== RUN 12 =====
.                                                                        [100%]
1 passed in 5.38s
RESULT 12 PASS
===== RUN 13 =====
.                                                                        [100%]
1 passed in 5.30s
RESULT 13 PASS
===== RUN 14 =====
F                                                                        [100%]
FAILED ... assert 'queued' == FAILED
ERROR ... cancellation cleanup failed to persist terminal job state
sqlite3.OperationalError: database is locked
→ sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
  at describe_async_worker.py:176 _mark_terminal / session.commit()
1 failed in 11.09s
RESULT 14 FAIL
===== RUN 15 =====
.                                                                        [100%]
1 passed in 5.49s
RESULT 15 PASS
===== RUN 16 =====
.                                                                        [100%]
1 passed in 7.34s
RESULT 16 PASS
===== RUN 17 =====
.                                                                        [100%]
1 passed in 5.57s
RESULT 17 PASS
===== RUN 18 =====
.                                                                        [100%]
1 passed in 5.72s
RESULT 18 PASS
===== RUN 19 =====
.                                                                        [100%]
1 passed in 5.60s
RESULT 19 PASS
===== RUN 20 =====
.                                                                        [100%]
1 passed in 4.58s
RESULT 20 PASS
===== RUN 21 =====
.                                                                        [100%]
1 passed in 5.49s
RESULT 21 PASS
===== RUN 22 =====
.                                                                        [100%]
1 passed in 5.49s
RESULT 22 PASS
===== RUN 23 =====
.                                                                        [100%]
1 passed in 5.56s
RESULT 23 PASS
===== RUN 24 =====
.                                                                        [100%]
1 passed in 6.20s
RESULT 24 PASS
===== RUN 25 =====
.                                                                        [100%]
1 passed in 5.11s
RESULT 25 PASS
```

**Tally: 24 PASS / 1 FAIL.** Idle full-file control (no extra load): `11 passed in 12.31s`.

Full run-14 traceback is in `/tmp/gateflake-r1-load25.txt` (copied above in condensed form; assertion at test line 320, lock at worker line 176).

---

## Leak check (angle 3 / RES-02) — ran here, not taken from the s1 report

Commands actually run:

1. After green full file (`11 passed in 12.31s`):
   `ls -ld /tmp/acx-describe-async-*` → **no leftover dirs**.
2. After pytest `-x` with injected `assert False` **before** `await engine.dispose()` in `test_worker_records_cpu_provisional_then_gpu_final` (restored after):
   process exited `1 failed in 1.43s`; `ls -ld /tmp/acx-describe-async-*` → **no leftover dirs**.
3. In-process hold: `_sessionmaker()` then `AssertionError` with traceback kept alive:
   `AFTER_FAIL_WITH_TB ['/tmp/acx-describe-async-12126uhg']` — dir exists while `engine` is in the traceback.
   Drop traceback + `gc.collect()` → `AFTER_DROP_TB_GC []`.
4. `TemporaryDirectory.cleanup()` twice → `DOUBLE_CLEANUP_OK`; dir gone.
5. After the 25-run load series: **no leftover dirs**.
6. After all mutations/probes: **no leftover dirs**.
7. Finalize-without-dispose probe: dropping the engine + GC removed the tmpdir. No immortal cycle (`engine → listener → _cleanup → tmpdir` has no back-edge). `weakref.finalize(engine, _cleanup)` invoked with no args (`_eng is None`).
8. SIGKILL: neither listener, finalize, nor `TemporaryDirectory` atexit runs. Dir would leak. Expected; not tested by killing this review process.

No permanent leak on clean process exit. In-session leak only while pytest holds a failure traceback (cleared at process exit). Dual cleanup is idempotent.

---

## What I checked and found clean

- Guard **does** go RED on uncommitted `:memory:` revert and GREEN on restore. s1 TEST-15 claim holds. Reran; did not take the report on faith.
- `:memory:` + `sleep_ms(0|1)` still RED — short-sleep is not a silent-pass of the *broken fixture*.
- File-backed + StaticPool still GREEN — expected if the defect is `:memory:` identity, not StaticPool itself. Not a missed broken fix for schema survival.
- Sequential UDF checkout identity holds for the guard as written (same `aiosqlite_id`; UDF callable). Split only when a connection is held or `NullPool` is used.
- `pytest.raises(CancelledError)` is not satisfied by cancelling an already-finished task.
- No immortal tmpdir cycle; no double-cleanup exception; no leftover `/tmp/acx-describe-async-*` after green runs, after pytest `-x` process exit, or after the load series.
- Happy-path tests do not rely on seeing uncommitted writes across sessions. `_create_run` commits; worker phases commit before the next session; session-identity spy (`test_final_phase_item_final_and_cache_insert_share_one_session`) and commit-fail rollback (`test_final_phase_commit_failure_rolls_back_cache_and_item_final`) are session-scoped, not connection-scoped. Their meaning did not change.
- `test_worker_timeout_after_provisional_projects_degraded` still uses `job_timeout_seconds=0.3` after a no-delay CPU phase; not part of the 0.05 revert.
- `_sessionmaker` arity still `(engine, sessionmaker)`.
- This sandbox cannot `git show 818d19f2`; history is one squashed commit. Within the tree, production `scene/application/` was not edited by this review lane; the s1 report claims it was not touched by the runner. No independent parent-diff proof.
- Source file restored to orig after every mutation (`diff` against `/tmp/test_describe_async_worker.py.orig` empty before this review file was written).

---

## Scope (angle 6)

Review-lane edits: this file only (`.s2a/gateflake-r1-review.md`).
Subject files inspected: `apps/prototype-description-service/scene/tests/test_describe_async_worker.py`, `.s2a/gateflake-s1-report.md`, `scene/application/describe_async_worker.py` (read-only).
Cannot confirm the original commit touched only those two paths — git history is stripped.

---

## Report honesty (angle 7)

| Claim | Verdict |
|-------|---------|
| `:memory:` guard RED with `no such table` | Confirmed (2.42s here vs report 1.74s) |
| Restore GREEN | Confirmed (1.86s) |
| Full file 11 passed | Confirmed (`11 passed in 12.31s`) |
| Leak check empty after green run | Confirmed independently |
| Guard discriminates the fixture | Confirmed for `:memory:`; not for StaticPool-on-file |
| `job_timeout_seconds` 0.5 → 0.05 is safe; class dead | **False.** 1/25 loaded runs failed (R1-01) |
| 13 green runs | True as idle full-file evidence; oversold as flake-death |
| `AsyncEngine.dispose` is read-only | **False** (plain function) |
| Production not touched | Plausible; not independently diffable here |
