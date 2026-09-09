# gateflake-r3 — adversarial review of s3 @a7def04e
**Verdict:** pass_with_findings

**Lane:** `gateflake-reviewer`
**Task:** `MAINT-GATE-FLAKES-20260815`
**Subject:** commit `a7def04e` on `feature/maint-gate-flakes-20260815`, file `apps/prototype-description-service/scene/tests/test_describe_async_worker.py`
**Posture:** adversarial. Two prior review passes each found a real defect in work that looked clean. Assume the same until shown otherwise.
**Sandbox note:** this checkout is history-stripped (`e568db1` sha-guard:ignore — foreign sandbox-clone root SHA, does not exist in this repo's history). `a7def04e` is not a distinct SHA here. Review is of the current tree contents matching the claimed s3 change (file URL, default `AsyncAdaptedQueuePool`, connect-listener `sleep_ms`, `job_timeout_seconds=0.5`, poll `GATEFLAKE-S3-LOCK` instrument).
**Scope:** this file only. Test file and production worker not edited.

Canon: **TEST-08**, **TEST-15**, **TEST-16**, **CON-17**, **REF-25**, **DBG-01**.

---

## Findings

One low finding: **GATEFLAKE-R3-01** (debris `GATEFLAKE-S3-LOCK` print at `test_describe_async_worker.py:495-498`). Full write-up at the bottom. No high/medium.

---

## Angle 1 — is the barrier complete, or just usually lucky again?

### 1a. Isolation probe on shipped `_sessionmaker` (do not take s3's transcript)

Standalone script `/tmp/gateflake_r3_probe_isolation.py` imported the **shipped** `_sessionmaker` + `DescribeRunRepository.mark_item` / `get_single_run_item`. Session A flushed `RUNNING` and did **not** commit. Session B is a second `sf()` checkout.

```
----- shipped _sessionmaker -----
pool=AsyncAdaptedQueuePool
url=sqlite+aiosqlite:////tmp/acx-describe-async-nn6__rvi/test.db
journal_mode='delete'
busy_timeout=5000
locking_mode='normal'
wal_autocheckpoint=1000
engine.pool._timeout=30.0
engine.pool.size=5
dbapi=AsyncAdapt_aiosqlite_connection
dbapi._timeout=None
dbapi.timeout=None
A marked=True flushed_not_committed
A session_id=247455552730608
A raw_id=247455333484592 raw_type=_ConnectionFairy
A driver_id=247455581015968 driver_type=AsyncAdapt_aiosqlite_connection
A sqlite3_id=247455581021552 sqlite3_type=Connection
B session_id=247455351289952
B raw_id=247455333810928 raw_type=_ConnectionFairy
B driver_id=247455333726192 driver_type=AsyncAdapt_aiosqlite_connection
B sqlite3_id=247455333723616 sqlite3_type=Connection
same_raw=False
same_driver=False
same_sqlite3=False
B_sees_uncommitted=False status='queued'
B_sees_row=True
A_after_B_exit sees_running=True status=<DescribeItemStatus.RUNNING: 'running'>
C_after_A_commit status='running'
```

Confirmed independently:
- `same_sqlite3=False`
- `B_sees_uncommitted=False` (`status='queued'`)
- B's session exit does **not** roll A's flush back (`A_after_B_exit sees_running=True`)
- A's later commit persists; session C sees `'running'`

Journal mode is **`delete`** (rollback journal), not WAL. `busy_timeout=5000` ms.

Interpretation so far: the dirty-read / shared-rollback hole that killed s2 is closed on this fixture. Seeing `RUNNING` in the poll *is* a commit observation. Next: can the lock instrument fire, or is 0/25 just the 5s busy timeout swallowing the EXCLUSIVE window?

### 1b. Can `GATEFLAKE-S3-LOCK` fire? (TEST-15 on the instrument)

Journal is rollback (`delete`). A reader should block or raise `database is locked` only while a writer holds **EXCLUSIVE**, not while it holds **RESERVED** (uncommitted flush). Shipped `busy_timeout=5000`. The poll's `try/except` re-raises after printing.

Standalone `/tmp/gateflake_r3_probe_lock.py` used shipped `_sessionmaker` + the poll's exact except around `_load_item`.

**RESERVED (A flushed `RUNNING`, no commit) — instrument does NOT fire:**

```
===== CASE reserved (A flushed RUNNING, no commit) =====
A holding RESERVED (flushed, not committed)
elapsed=0.021
B_status='queued'
LOCK_FIRE reserved=False
```

**EXCLUSIVE via raw `sqlite3` `BEGIN EXCLUSIVE` against the same file — instrument DOES fire:**

```
===== CASE exclusive via raw sqlite3 BEGIN EXCLUSIVE (shipped busy_timeout) =====
holder has EXCLUSIVE
elapsed=5.007
exc_type=OperationalError
exc=(sqlite3.OperationalError) database is locked
[SQL: SELECT image_description_run_items.id, ...
GATEFLAKE-S3-LOCK during poll: OperationalError (sqlite3.OperationalError) database is locked
LOCK_FIRE exclusive_raw=True
```

**EXCLUSIVE via `engine.connect()` `BEGIN EXCLUSIVE` — same fire after 5.007s:**

```
===== CASE exclusive via engine.connect BEGIN EXCLUSIVE =====
engine connection holding EXCLUSIVE
elapsed=5.007
exc_type=OperationalError
exc=(sqlite3.OperationalError) database is locked
GATEFLAKE-S3-LOCK during poll: OperationalError (sqlite3.OperationalError) database is locked
LOCK_FIRE exclusive_engine=True
```

The instrument is live. It prints and re-raises. It does **not** fire on the flush-to-commit RESERVED window (readers proceed and see last committed `queued`). It fires only if EXCLUSIVE is held longer than `busy_timeout=5000`.

s3's **0 lock hits in 25 cancel runs** is therefore the expected result of a millisecond commit EXCLUSIVE being absorbed by a 5s busy wait — not evidence the instrument is dead, and not evidence the EXCLUSIVE window does not exist. After the wait the poll sees committed `RUNNING` and cancels. The poll deadline is also 5.0s, so a held EXCLUSIVE ≥5s would fail the test loudly (`OperationalError`) rather than silently miss.

Barrier claim stands: seeing `RUNNING` means phase-1 committed. 0/25 lock prints do not undermine that.

### 1c. Load cliff

s3 measured 25/25 at 6 burners. Hunt: raise to 12, then 16. Same test: `test_worker_cancellation_marks_failed_then_re_raises`. No retries. `-p no:randomly --tb=short`.

**Load:** 12× `python3 -c 'while True: x = 1234567 * 7654321'` PIDs 1016876–1016887. `nproc=4`.

#### 12 burners, runs 1–5

```
===== CANCEL 12-BURNER RUN 1 =====
.                                                                        [100%]
1 passed in 14.19s
RESULT 1 PASS
ELAPSED 1 22.38
===== CANCEL 12-BURNER RUN 2 =====
.                                                                        [100%]
1 passed in 10.60s
RESULT 2 PASS
ELAPSED 2 15.01
===== CANCEL 12-BURNER RUN 3 =====
.                                                                        [100%]
1 passed in 12.81s
RESULT 3 PASS
ELAPSED 3 17.49
===== CANCEL 12-BURNER RUN 4 =====
.                                                                        [100%]
1 passed in 17.59s
RESULT 4 PASS
ELAPSED 4 25.79
===== CANCEL 12-BURNER RUN 5 =====
.                                                                        [100%]
1 passed in 11.33s
RESULT 5 PASS
ELAPSED 5 16.02
```

5/5 PASS. No `GATEFLAKE-S3-LOCK` line.

Burner CPU at start of runs 6–10 (still the same 12 PIDs): 12.2–24.6% each, `STAT=RN`, `nproc=4` (box saturated).

#### 12 burners, runs 6–10

```
===== CANCEL 12-BURNER RUN 6 =====
.                                                                        [100%]
1 passed in 15.52s
RESULT 6 PASS
ELAPSED 6 20.99
===== CANCEL 12-BURNER RUN 7 =====
.                                                                        [100%]
1 passed in 13.42s
RESULT 7 PASS
ELAPSED 7 20.52
===== CANCEL 12-BURNER RUN 8 =====
.                                                                        [100%]
1 passed in 10.52s
RESULT 8 PASS
ELAPSED 8 16.69
===== CANCEL 12-BURNER RUN 9 =====
.                                                                        [100%]
1 passed in 13.80s
RESULT 9 PASS
ELAPSED 9 21.42
===== CANCEL 12-BURNER RUN 10 =====
.                                                                        [100%]
1 passed in 12.31s
RESULT 10 PASS
ELAPSED 10 21.09
```

12-burner cancel: **10/10 PASS**, lock_hits=0. No behaviour change vs s3's 6-burner battery.

#### 16 burners, runs 1–5

Added PIDs 1021656–1021659 (16 total). CPU still 9.7–19.1% each, box saturated.

```
===== CANCEL 16-BURNER RUN 1 =====
.                                                                        [100%]
1 passed in 16.20s
RESULT 1 PASS
ELAPSED 1 24.49
===== CANCEL 16-BURNER RUN 2 =====
.                                                                        [100%]
1 passed in 16.28s
RESULT 2 PASS
ELAPSED 2 25.5
===== CANCEL 16-BURNER RUN 3 =====
.                                                                        [100%]
1 passed in 14.00s
RESULT 3 PASS
ELAPSED 3 22.51
===== CANCEL 16-BURNER RUN 4 =====
.                                                                        [100%]
1 passed in 17.51s
RESULT 4 PASS
ELAPSED 4 27.78
===== CANCEL 16-BURNER RUN 5 =====
.                                                                        [100%]
1 passed in 12.59s
RESULT 5 PASS
ELAPSED 5 20.02
```

16-burner cancel: **5/5 PASS**, lock_hits=0.

**Cliff:** none found within budget. 10/10 at 12 + 5/5 at 16, 0 lock prints. Runs got slower (elapsed 20–28s vs s3's ~15s at 6) but none failed. Not 25/25 at these loads — bound is 15 extra cancel runs, not a proof of impossibility.

### Angle 1 conclusion

The poll is a real commit barrier on the shipped fixture, not "usually missed the window." Isolation, no shared rollback, instrument can fire, and no load cliff up to 16 burners. s3's 0/25 lock hits are explained by `busy_timeout=5000` absorbing the millisecond EXCLUSIVE commit window.

---

## Angle 2 — does the guard still discriminate for the right reason?

### TEST-15 RED / GREEN (re-run, not s3's transcript)

Uncommitted mutation: `create_async_engine(f"sqlite+aiosqlite:///{path}")` → `create_async_engine("sqlite+aiosqlite:///:memory:")`. Listener left in place. File restored from `/tmp/test_describe_async_worker.py.orig`; `sha256sum` matched before and after.

**RED** (`:memory:`, StaticPool implied)

```
FAILED scene/tests/test_describe_async_worker.py::test_sessionmaker_survives_cancelled_in_flight_query - sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: image_description_run_items
1 failed in 2.42s
```

Failure is at `_load_item` after cancel (`test_describe_async_worker.py:182`), **`no such table: image_description_run_items`**. Same error s3 reported. Not a new error. Schema death on the cancelled StaticPool `:memory:` connection.

**GREEN** (file restored)

```
.                                                                        [100%]
1 passed in 1.81s
```

`git status` clean for the test file after restore.

### Cancelled connection vs schema

Under `:memory:` the RED is still StaticPool-is-the-whole-DB. The connect listener does not change that: UDF fires (`started` must have set — we reached cancel and then `_load_item`, not the TimeoutError), cancel still kills the only connection, `_load_item` finds no table. Guard still fails for the claimed reason.

Under shipped file+QueuePool the schema lives on disk. Cancel invalidates one pooled connection; the next `_load_item` checkout is a different sqlite3 connection (angle 1) and sees the file. GREEN is schema survival, not a skipped cancel.

### Named `TimeoutError` (R1-03) — unreachable?

s3: "R1-03 `TimeoutError` message kept; with the listener it should be unreachable."

Standalone `/tmp/gateflake_r3_probe_timeout.py`:

```
===== shipped _sessionmaker(sleep_ms=_sleep_and_signal) =====
pool=AsyncAdaptedQueuePool
shipped started.set observed
shipped CancelledError on await (expected)
shipped post-cancel load media_id=7
SHIPPED_TIMEOUT_REACHED=False
```

```
===== file URL, NO connect listener (R1-03 regression) =====
dropped-listener wait_for TimeoutError raw=TimeoutError() args=()
dropped-listener NAMED would be: sleep_ms UDF never started; UDF is registered on one aiosqlite connection and this session may have checked out a different one
dropped-listener in_flight OperationalError: (sqlite3.OperationalError) no such function: sleep_ms
DROPPED_LISTENER_TIMEOUT_REACHED=True
```

```
===== shipped listener, hold pool_size=5 connections =====
pool_size=5
held=5
hold-pool UNEXPECTED started
```

With the listener: TimeoutError is **not** reached on the shipped path. Holding all 5 pooled connections still did **not** reach it — QueuePool overflowed a 6th connection, the connect listener registered `sleep_ms` on it, `started` fired. I did **not** find a checkout path that hits the named TimeoutError while the listener is installed.

Without the listener: the bare `TimeoutError()` from `wait_for` still occurs, then the named wrap is the R1-03 tripwire; `_in_flight` dies with `no such function: sleep_ms`. So "unreachable" is true for the shipped fixture, false as an absolute — the message is still the listener-dropped / UDF-miss regression path. That is what keeping it is for. Not a finding.

Guard still discriminates schema death. It does not fail for a new reason.

---

## Angle 3 — did dropping StaticPool change any other test's meaning?

s2 fixture: file URL + `poolclass=StaticPool` (one sqlite3 connection, shared transaction visibility, no cross-connection lock).
s3 fixture: file URL + default `AsyncAdaptedQueuePool` (confirmed `type(engine.sync_engine.pool).__name__ == 'AsyncAdaptedQueuePool'`).

Every test in `test_describe_async_worker.py`:

| Test | Second session sees prior writes how? | Meaning vs s2 StaticPool |
|---|---|---|
| `test_sessionmaker_survives_cancelled_in_flight_query` | `_create_run` commits; post-cancel `_load_item` is a new checkout | **narrowed, for the better.** UDF now on every connect (R1-03 hole closed). Still asserts schema survival after mid-query cancel. RED is still `no such table`. |
| `test_worker_module_importable` | no DB | unchanged |
| `test_worker_records_cpu_provisional_then_gpu_final` | worker commits internally; `_load_item` / `_count_cache_rows` after return | unchanged — sequential commit-then-open |
| `test_worker_keeps_cpu_provisional_when_gpu_fails` | same | unchanged |
| `test_worker_timeout_marks_failed_exactly_once` | `wait_for` cancel concurrent with worker sessions | **yes, meaning changes.** StaticPool made a second-connection lock race impossible. QueuePool brings R1-01 back *if* cancel lands mid phase-1 write. s3 keeps `job_timeout_seconds=0.5` (r2b margin 0.404s) so the test still asserts "exactly one FAILED persist after a committed RUNNING." That is a timing hedge, not lock-race elimination. Production is Postgres. Same R1-02 shape, now vs s2 rather than vs `:memory:`. Documented in the comment. I did **not** re-run this test under 12/16 burners (brief asked for the cancel test). |
| `test_worker_timeout_after_provisional_projects_degraded` | CPU adapter has no delay; 0.3s timeout during 2.0s GPU delay; provisional already committed | unchanged — cancel is after a committed provisional, not mid phase-1 |
| `test_final_phase_item_final_and_cache_insert_share_one_session` | spies compare `self._session` identity | unchanged — session identity, not pool identity |
| `test_worker_cancellation_marks_failed_then_re_raises` | poll `_load_item` while worker holds phase-1 session | **yes — this is the intended fix.** Under StaticPool the poll dirty-read / rolled back (R2-01). Under QueuePool seeing `RUNNING` means committed. Test now asserts what its comment says. |
| `test_cpu_failure_before_provisional_marks_failed_not_cached` | load after worker return | unchanged |
| `test_final_phase_commit_failure_rolls_back_cache_and_item_final` | wrapped factory counts `session.commit` calls; inspect after return | unchanged — still same-session commit #3 failure + rollback |
| `test_worker_bails_on_already_terminal_failed_and_completed` | explicit `await s.commit()` before re-entry | unchanged |

No test besides the cancel poll was relying on uncommitted cross-session visibility. `_create_run` commits. Worker phases commit before returning. Terminal re-entry commits before the next `run_async_describe_job`.

The timeout test is the only silent-meaning risk. I am **not** filing a new finding for it: it is R1-02 restated, s3's comment already names the lock race and the 0.5s hedge, and this lane's cancel-load battery did not produce a flake. Filing it again would be stacking.

Idle confirmation (this lane, no burners):

```
...........                                                              [100%]
11 passed in 12.27s
```

Leak check after that run: `find /tmp -maxdepth 1 -name 'acx-describe-async-*'` → `count=0`.

---

## Angle 4 — debris and honesty

### `GATEFLAKE-S3-LOCK` print in shipped poll

```493:498:apps/prototype-description-service/scene/tests/test_describe_async_worker.py
        while time.monotonic() < deadline:
            try:
                started_item = await _load_item(sf, tenant_id=tenant, run_id=run_id)
            except Exception as exc:
                if "database is locked" in str(exc).lower():
                    print("GATEFLAKE-S3-LOCK during poll:", type(exc).__name__, exc)
                raise
```

Re-raises unconditionally — masks nothing. Angle 1b proved the print can fire. It is a measurement instrument left in shipped test code after the measurement (s3 25-run battery, this lane's 15 extra runs, 0 hits under real cancel). REF-25 boarding-up of the *hole* is dropping StaticPool, not this `print`. Recommend **remove** after r3. Not a behaviour bug. Finding: GATEFLAKE-R3-01 (low).

### s3 report vs transcripts

Checked claims against this lane's reruns:

| Claim | Supported? |
|---|---|
| shipped `same_sqlite3=False`, `B_sees_uncommitted=False` | **yes** — reproduced |
| TEST-15 RED `no such table` / GREEN 1 passed | **yes** — reproduced |
| cancel 25/25 and timeout 25/25 under 6 burners | **not re-run at 6.** Format looks like real pytest output. This lane: 10/10 @12 + 5/5 @16 cancel, 0 lock hits. No reason to call the 6-burner battery fake. |
| lock hits = 0 | **yes**, and expected (busy_timeout=5000). They did **not** show the instrument can fire. Gap, not a lie. |
| 10× idle `11 passed` | this lane: `11 passed in 12.27s` once |
| no temp leaks | this lane: `count=0` |
| "R1-03 … should now be unreachable" | **true on the shipped path.** Over-reads if taken as "the except is dead code" — listener-dropped still reaches the named wrap. They also said they *kept* the message, so the intended reading is "unreachable while the listener lives." Not the s1-style "class is dead" overclaim. |
| "the barrier is real" / "Seeing RUNNING means phase-1 committed" | **yes** on this fixture |
| comment "poll may block or raise database is locked if the worker still holds the write lock" | **half-true.** RESERVED (uncommitted flush) does **not** block readers. Only EXCLUSIVE ≥ `busy_timeout` raises. A normal commit's EXCLUSIVE is waited out, not raised. Mild comment looseness, not a transcript overclaim. |

No s1-style "the class is dead" resting on idle runs. I am not quoting an unsupported headline.

### What I could NOT verify

- Distinct SHA `a7def04e` — sandbox is history-stripped (`e568db1` sha-guard:ignore — foreign sandbox-clone root SHA, does not exist in this repo's history). Review is of tree contents matching the claimed s3 diff.
- s3's exact 6-burner 25/25 timeout battery — not re-run; budget spent on cancel-test cliff at 12/16.
- Timeout test under 12/16 burners — not run. 0.5s hedge not re-timed (r2b already did n=15).
- Process-kill leak behaviour — not tested.

---

## Findings

### GATEFLAKE-R3-01 — low

**File:line:** `apps/prototype-description-service/scene/tests/test_describe_async_worker.py:495-498`

**Evidence + impact:** The poll's `except Exception` + `print("GATEFLAKE-S3-LOCK …")` + re-raise is a live measurement instrument. Angle 1b fired it under held EXCLUSIVE. It does not change pass/fail (re-raises). It is not boarding-up the R2-01 hole (QueuePool did that). Left in shipped tests it will either stay silent forever (0 hits in 40 loaded cancel runs across s3 + this lane) or dump a SQLAlchemy traceback into pytest stdout on the rare EXCLUSIVE>5s path. DBG-01 leftover.

**Failure scenario:** Next agent treats `GATEFLAKE-S3-LOCK` as part of the contract and keeps extending the poll with more print/except probes. Or CI captures the print as a mysterious "failure" in logs when a slow EXCLUSIVE actually trips. Remove the try/except/print; let `OperationalError: database is locked` fail the test plainly if it ever happens.

No high/medium findings. Declining to re-file R1-02 / R2-01: both are addressed on this tree (0.5s hedge documented; poll is a real commit barrier).

---

## What I checked and found clean

- Isolation on shipped `_sessionmaker`: different sqlite3 connections; no dirty read; no rollback of A's flush.
- Journal mode `delete`; `busy_timeout=5000`.
- Lock instrument can fire (TEST-15 on the meter).
- Cancel test 10/10 @12 burners + 5/5 @16 burners, 0 lock prints. No cliff found in budget.
- Guard RED is still `no such table`, not a new error. GREEN after restore.
- Named TimeoutError not reached with listener; reached if listener dropped.
- Other tests (except timeout's known lock-race residual) keep sequential commit-then-open meaning.
- Idle `11 passed in 12.27s`. `count=0` temp dirs.
- Production `describe_async_worker.py` not edited this lane. Only this review file written.
