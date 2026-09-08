# FEBT-1 W1 machine fix evidence

Lane `febt-1-fix-machine` on `fix/febt-1-w1-machine`. TDD: tests first, RED captured, then implementation.

GREEN summary: `js/admin/hooks/__tests__/jobMachine.test.ts` — Tests 199 passed (199). Full gate: `npx vitest run js/admin` — Test Files 231 passed / Tests 2898 passed; `npm run typecheck` exit 0.

Existing assertion meaning was preserved except where M-04 required the table cell to stop being a dash: `pending × STALL_TICK` is now `stalled` (sample tick is at the 30s threshold) and `offline × STALL_TICK` is now handled-stay `offline` (not object identity). `initialJobState` gained `reconnectAttempts: 0`. OFFLINE/ONLINE fixtures gained `at` without changing status/resumeStatus expects.

---

## L6A-01 (high) — OFFLINE/ONLINE timestamps

Tests:

- `does not stall one millisecond after a 5-minute offline window, then stalls 30s later`
- `OFFLINE writes lastEventAt from event.at and stores resumeStatus`
- `ONLINE writes lastEventAt from event.at and clears resumeStatus`
- `offline → online → stall writes lastEventAt and resumeStatus at each step`

RED (first run, before implementation):

```
AssertionError: expected 'stalled' to be 'running' // Object.is equality
Expected: "running"
Received: "stalled"
 ❯ jobMachine.test.ts:341:32
    expect(immediate.status).toBe(JOB_MACHINE_STATE.running);
```

```
AssertionError: expected 1000 to be 5000
- 5000
+ 1000
 ❯ jobMachine.test.ts:397:32
    expect(next.lastEventAt).toBe(5_000);
```

```
AssertionError: expected 1000 to be 8000
- 8000
+ 1000
 ❯ jobMachine.test.ts:404:32
    expect(next.lastEventAt).toBe(8_000);
```

```
AssertionError: expected 1000 to be 301000
- 301000
+ 1000
 ❯ jobMachine.test.ts:426:34
    expect(online.lastEventAt).toBe(t + 300_000);
```

**goOffline timestamp decision:** `goOffline` *does* refresh `lastEventAt` from `event.at`. Offline wait (M-04) must measure time spent offline, not mix in pre-offline quiet. Stall vs offline are distinct recoveries; starting the offline clock on disconnect keeps a 29s-quiet job from stalling one tick after going offline. `goOnline` still overwrites `lastEventAt` for the post-reconnect stall clock.

GREEN: included in 199/199.

---

## L6A-03 (low) — ux-map STALL_TICK cell

No reducer test. Markdown cell `running × STALL_TICK` changed from `stalled` to `stalled (if quiet >= 30s) else running`. `.uxmap.json` untouched. Adjacent pending/stalled/offline STALL_TICK cells updated so M-03/M-04 do not reintroduce table/code contradiction.

---

## M-01 (high) — pin handler writes

Tests: `START|STREAM_OPEN|PROGRESS|RECONNECTED|COMPLETE|COMPLETE_WITH_ERRORS|FAIL|OFFLINE|ONLINE|RESET writes lastEventAt/resumeStatus` plus `offline → online → stall writes lastEventAt and resumeStatus at each step`.

RED (writes that were missing): same OFFLINE/ONLINE `lastEventAt` failures as L6A-01. Handlers that already wrote those fields stayed green on first run and are now pinned.

GREEN: included in 199/199.

---

## M-02 (medium) — 30s numeric pin

Tests:

- `pins JOB_MACHINE_STALL_THRESHOLD_MS to 30_000`
- `stalls after a literal 30_000 ms quiet interval and not after 29_999`

First run was green (contract pin). TEST-15 mutation `JOB_MACHINE_STALL_THRESHOLD_MS = 29_000`:

```
AssertionError: expected 29000 to be 30000 // Object.is equality
- 30000
+ 29000
 ❯ jobMachine.test.ts:446:46
    expect(JOB_MACHINE_STALL_THRESHOLD_MS).toBe(30_000);
```

Restored to `30_000`. Literal `30_000` / `29_999` timings do not import the constant.

GREEN: included in 199/199.

---

## M-03 (high) — reconnect ceiling (RES-06)

Tests:

- `stays stalled below the ceiling and fails when the ceiling is crossed`
- `ONLINE resets the reconnect counter so the next stall does not fail immediately`
- `pins JOB_MACHINE_RECONNECT_CEILING to 3 and MAX_TICK_DELTA_MS to 120_000`

RED (first run):

```
AssertionError: expected 'stalled' to be 'failed' // Object.is equality
Expected: "failed"
Received: "stalled"
 ❯ jobMachine.test.ts:469:28
    expect(state.status).toBe(JOB_MACHINE_STATE.failed);
```

Keyed on `(stalled|pending|running, STALL_TICK)` and `(offline, STALL_TICK)` via shared `onQuietTick` (GRPH-27/28). Failed error message: `Reconnect ceiling exceeded (3 attempts)`.

**Ceiling value:** `JOB_MACHINE_RECONNECT_CEILING = 3`. Three quiet windows stay stalled/offline (`attempts` 1..3); the 4th (`attempts > 3`) fails. ~90s of reconnecting UI after first stall, then a terminal state the operator can act on. `ONLINE` resets the counter; `PROGRESS` also resets (job liveness). `STREAM_OPEN` / `RECONNECTED` do not, so a flapping SSE still hits the ceiling.

GREEN: included in 199/199.

---

## M-04 (medium) — pending STALL_TICK and bounded offline wait

Tests:

- `STALL_TICK from pending stalls after 30s quiet`
- `an offline pending job fails after the reconnect ceiling of quiet ticks`

RED (first run):

```
AssertionError: expected 'pending' to be 'stalled' // Object.is equality
Expected: "stalled"
Received: "pending"
 ❯ jobMachine.test.ts:495:27
    expect(next.status).toBe(JOB_MACHINE_STATE.stalled);
```

```
AssertionError: expected 'offline' to be 'failed' // Object.is equality
Expected: "failed"
Received: "offline"
 ❯ jobMachine.test.ts:513:28
    expect(state.status).toBe(JOB_MACHINE_STATE.failed);
```

pending/running/stalled share `stallIfQuiet` (GRPH-28). offline uses `boundOfflineWait` (same quiet classifier, stay offline until ceiling, then fail). Job remains `offline` so `ONLINE` still restores `resumeStatus` until the wait is exhausted.

GREEN: included in 199/199.

---

## M-05 (medium) — clock discontinuity clamp

Tests:

- `does not stall on a 6-hour jump in one tick`
- `two consecutive 31s-quiet ticks still stall`

RED (first run):

```
AssertionError: expected 'stalled' to be 'running' // Object.is equality
Expected: "running"
Received: "stalled"
 ❯ jobMachine.test.ts:522:29
    expect(jumped.status).toBe(JOB_MACHINE_STATE.running);
```

**Clamp value:** `JOB_MACHINE_MAX_TICK_DELTA_MS = 120_000` (2 minutes). Must be `> 30_000` so a genuine 31s gap still stalls. Browser background timers can delay to ~60s; 2 minutes leaves headroom. Laptop sleep / NTP / 6-hour jumps are far above. Oversized or negative deltas realign `lastEventAt` to `event.now` and do not count as quiet.

GREEN: included in 199/199.

---

## M-06 (low) — RESET pin

Test: `RESET from idle is deep-equal to initialJobState`

First run was green (`resetIdle` already returned `initialJobState`). TEST-15 mutation (idle `RESET` identity):

```
AssertionError: expected { Object (status, jobId, ...) } to deeply equal { status: 'idle', jobId: null, …(7) }
-   "done": 0,
+   "done": 5,
-   "jobId": null,
-   "lastEventAt": null,
+   "jobId": "job-1",
+   "lastEventAt": 1000,
-   "total": 0,
+   "total": 10,
 ❯ jobMachine.test.ts:552:20
    expect(next).toEqual(initialJobState);
```

Restored idle `RESET` to `resetIdle`. Input is `fixtureFor(idle)`, not `initialJobState`, so a status-only idle RESET cannot pass.

GREEN: included in 199/199.
