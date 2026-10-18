# FEBT-1 W1 review — machine lens
VERDICT: pass_with_findings
COMBINED_TREE: 6da49ca7

Reviewer: grok-4.6 (lane `febt-1-rev-machine`). Read-only against
`apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts` (276 lines),
`js/admin/hooks/__tests__/jobMachine.test.ts` (327 lines, 179 tests),
`apps/prototype-wp-alt-context/docs/ux-maps/febt-1-job-error-states.md` (+ `.uxmap.json`).
No production/test edits kept. Baseline: `npx vitest run js/admin/hooks/__tests__/jobMachine.test.ts` → 179 passed.
Each mutant applied to `jobMachine.ts` only, suite re-run, file restored. Final restore confirmed; `npm run typecheck` green.

179 tests is 8 statuses × 12 events = 96 status cells + 57 dash identity cells + 26 dedicated/exhaustiveness cases. The cartesian table only asserts `next.status`. That is why the count looks thorough and why store/liveness mutants survive.

## Mutation results (TEST-15)

| # | file:line | mutation | KILLED / SURVIVED |
| --- | --- | --- | --- |
| 1 | jobMachine.ts:105 | `stallIfQuiet`: `>=` → `>` | KILLED (2 tests: table `running+STALL_TICK`, dedicated threshold) |
| 2 | jobMachine.ts:14 | `JOB_MACHINE_STALL_THRESHOLD_MS = 30_000` → `30_001` | SURVIVED (179 passed) |
| 3 | jobMachine.ts:126 | `goOffline`: `resumeStatus: state.status` → `state.resumeStatus` | KILLED (3 OFFLINE/ONLINE round-trip tests) |
| 4 | jobMachine.ts:136 | `goOnline`: `status: state.resumeStatus` → `JOB_MACHINE_STATE.running` | KILLED (pending + stalled restore) |
| 5 | jobMachine.ts:202 | drop `[JOB_EVENT.CANCEL]: resetIdle` from `running` row | KILLED (table `running+CANCEL => idle`) |
| 6 | jobMachine.ts:100 | `applyProgress`: `total: event.total` → `state.total` | KILLED (PROGRESS store test) |
| 7 | jobMachine.ts:154 | `completeWithErrors`: `failedCount: event.failedCount` → `state.failedCount` | KILLED (COMPLETE_WITH_ERRORS store test) |
| 8 | jobMachine.ts:82-83 | `startJob`: `done/total: 0` → `_state.done/_state.total` | KILLED (3 terminal START tests) |
| 9 | jobMachine.ts:84 | `startJob`: `lastEventAt: event.at` → `_state.lastEventAt` | SURVIVED (179 passed) |
| 10 | jobMachine.ts:144 | `complete`: omit `lastEventAt: event.at` | SURVIVED (179 passed) |
| 11 | jobMachine.ts:93 | `openStream`: omit `lastEventAt: event.at` | SURVIVED (179 passed) |
| 12 | jobMachine.ts:116 | `reconnect`: omit `lastEventAt: event.at` | SURVIVED (179 passed) |
| 13 | jobMachine.ts:183 | drop `[JOB_EVENT.RESET]: resetIdle` from `idle` row | SURVIVED (179 passed) |
| 14 | jobMachine.ts:162 | `fail`: `error: event.error` → `state.error` | KILLED (FAIL store test) |
| 15 | jobMachine.ts:105 | drop `lastEventAt !== null &&` in `stallIfQuiet` | KILLED (dedicated null-anchor identity) |

Suggested eight: 7 KILLED, 1 SURVIVED (#2). Extra liveness/no-op mutants: 4 lastEventAt SURVIVED, idle RESET SURVIVED.

## Findings

### M-01 | severity: medium | file: jobMachine.ts:84,93,116,144 | canon: TEST-15, GRPH-26
evidence: Mutants 9–12 deleted the `lastEventAt: event.at` write from `startJob`, `openStream`, `reconnect`, and `complete`. 179 tests stayed green. The only store assertion on `lastEventAt` is the PROGRESS case (`jobMachine.test.ts:228-236`). `stallIfQuiet` (`jobMachine.ts:104-108`) uses `lastEventAt` as the gate for `running → stalled`, so it is de-facto control state living on the unbounded store (GRPH-26). Table tests never look at it.
consequence: A refactor can stop refreshing the liveness clock on start/open/reconnect/complete and the suite still certifies the machine. That is the same family as FEBT-1-L6A-01: after OFFLINE/ONLINE the clock is already stale, and the tests cannot catch either the existing bug or a new one.
recommendation: Assert `lastEventAt` (and `resumeStatus`) on every handler that is supposed to write it. Pin `START`/`STREAM_OPEN`/`RECONNECTED`/`COMPLETE`/`COMPLETE_WITH_ERRORS` with an `at` distinct from the fixture (`AT = 1000`). Add a chained case: running → OFFLINE → (clock advance) → ONLINE → STALL_TICK.

### M-02 | severity: medium | file: jobMachine.ts:14 | canon: TEST-15
evidence: Mutant 2 changed `JOB_MACHINE_STALL_THRESHOLD_MS` from `30_000` to `30_001`. Suite still 179 passed because `jobMachine.test.ts` imports the constant for SAMPLE_EVENTS and the threshold test (`:50`, `:215-223`). Nothing asserts the numeric product value. A comparison that inlined `31_000` would have been killed; changing the exported constant is invisible.
consequence: The 30 s stall window is a user-visible product choice (map banner "No progress for 35 s"; uxmap.json flow "stalled (30 s no event)"). Tests will not fail if someone "tunes" it to 1 s or 5 min.
recommendation: One literal pin: `expect(JOB_MACHINE_STALL_THRESHOLD_MS).toBe(30_000)` next to the threshold test, or drive the test from a numeric `30_000` and import the constant only as the SUT.

### M-03 | severity: medium | file: jobMachine.ts:205-216 | canon: RES-06
evidence: `stalled` accepts `STREAM_OPEN` / `PROGRESS` / `RECONNECTED` back to `running` and `STALL_TICK` as `stay`. There is no attempt counter, ceiling, or `stalled → failed` path except an explicit `FAIL` event. Contrast `clusterAutoRetry.ts:12-23` (`CLUSTER_RETRY_MAX_ATTEMPTS = 3`). The markdown map flow says `running → stalled → running (SSE reopen) | failed (after bounded reconnects, RES-06)`. The reducer cannot fail after N stalls; a consumer would have to count outside and inject `FAIL`.
consequence: A persistent dead stream can ping-pong `running ↔ stalled` forever. Operator sees the stalled banner + reconnect loop and never the failed row with Retry. Immediate reconnect on every stall also amplifies a backend outage (RES-06).
recommendation: Put a finite `reconnectAttempts` (or equivalent) on the store and a `STALL_TICK` / `RECONNECTED` arm that `FAIL`s at a named ceiling. Do not leave the budget to L6b.

### M-04 | severity: medium | file: jobMachine.ts:185-194 | canon: RES-02
evidence: `pending` has no `STALL_TICK` handler (map cell is `—`; code is identity). `offline` waits only for `ONLINE`/`FAIL`/`CANCEL`/`RESET`. `stalled` × `STALL_TICK` is `stay` with no escalate. The only timeout in the machine is `running` × `STALL_TICK` via `stallIfQuiet`. `FAIL` itself carries no `at` (`jobMachine.ts:52,159-164`) so it does not refresh the clock either.
consequence: If SSE never opens, the banner stays "Queued…" with Cancel and no stall/fail escape. If the tab goes offline and `online` never fires, "You are offline — will resume" is immortal. Stalled never times out to failed (see M-03).
recommendation: Accept `STALL_TICK` from `pending` (same quiet check, baseline = `START.at`). Give `OFFLINE`/`ONLINE`/`FAIL` an `at` and treat a bounded offline wait as `failed` or return-to-idle. Escalate `stalled` after N ticks (M-03).

### M-05 | severity: medium | file: jobMachine.ts:14,104-108 | canon: RES-02
evidence: Stall is `event.now - lastEventAt >= 30_000` with `now` supplied by the caller. Three misclassifications:
1. Slow-but-alive: a describe item that takes 31 s between PROGRESS events is stalled. Banner becomes "No progress for 35 s — reconnecting" and Cancel, and L6b will reopen SSE on a live job.
2. Background tab: Chromium throttles timers (1 s floor, sometimes minutes). A late `STALL_TICK` carries a wall-clock `now` that is already past threshold even if the stream is healthy; EventSource may be throttled too, so `lastEventAt` is also stale.
3. Laptop sleep: `Date.now()` jumps. First tick after wake is hours past `lastEventAt` → immediate stall, then reconnect. Combined with L6A-01, an offline/online pair around sleep resumes `running` with a stale clock and the next tick false-stalls.
consequence: Operators get a false stalled banner and a reconnect storm after lid-open, after tabbing back, or on large-image jobs. Not a hang; a lie about liveness.
recommendation: Clamp one tick's delta (ignore jumps >> threshold as clock discontinuity; reset `lastEventAt` to `now` instead of stalling). Keep 30 s for true quiet. Do not stall solely because the tab was frozen.

### M-06 | severity: low | file: jobMachine.ts:183 | canon: TEST-15, GRPH-28
evidence: Mutant 13 dropped `RESET` from the `idle` row. 179 passed. Map cell is `idle`, not `—`. `resetIdle` returns `initialJobState` (new object, `jobId: null`, `done: 0`). Fixture idle has `jobId: 'job-1'`, `done: 5`. Table asserts status only; dash identity is skipped because expected is `idle` not `null`. Dropping the handler leaves the dirty store in place and tests still pass.
consequence: Idle RESET is the pull-up copy (GRPH-28) that tests cannot distinguish from a dash cell. A later edit that stops wiping idle store will ship green.
recommendation: Either mark the map cell `—` and delete the handler, or assert `idle+RESET` is referentially/`initialJobState` equal.

### M-07 | severity: low | file: jobMachine.ts:179-235 | canon: GRPH-28
evidence: `RESET: resetIdle` is on all eight rows. `CANCEL: resetIdle` is on pending/running/stalled/offline only (not idle, not terminals). `OFFLINE: goOffline` is on idle/pending/running/stalled only. Membership differences are load-bearing; idle RESET is the one that is not (M-06). Terminals correctly refuse CANCEL/OFFLINE.
consequence: Copy-paste drift is real for RESET (already invisible on idle). Blind pull-up of CANCEL/OFFLINE onto a "non-terminal parent" would be correct; pulling them onto idle/terminals would not.
recommendation: Introduce a shared `activeJobHandlers` (pending/running/stalled) and a `terminalHandlers` (START+RESET). Keep idle/offline explicit.

### M-08 | severity: low | file: jobMachine.ts:237-276 | canon: REF-21
evidence: `jobReducer` is not imported by any production file yet (W1 contract; L6b/L6c wire it). Consumers must still dispatch `STALL_TICK` with wall-clock `now`; the reducer owns the comparison but not the timer. Combined tree already has a parallel clock in `useJobProgressStream.ts:21,99-112` (`JOB_PROGRESS_STALL_THRESHOLD_MS = 30_000`, own `lastEventAt`). Two 30 s constants will drift.
consequence: L6b can reimplement stall timing instead of driving this reducer, or tick with a different interval than 30 s. The module did not fully pull complexity downward.
recommendation: Export one threshold and a `shouldStall(state, now)` (already equivalent to `stallIfQuiet`). L6b must delete `JOB_PROGRESS_STALL_THRESHOLD_MS`.

## UX-map fidelity

Map path: `apps/prototype-wp-alt-context/docs/ux-maps/febt-1-job-error-states.md` (JSON sibling). Compared every markdown table cell to `TRANSITIONS` + handlers.

Agree (code matches map status): idle START/OFFLINE/RESET; pending STREAM_OPEN/PROGRESS/OFFLINE/COMPLETE/COMPLETE_WITH_ERRORS/FAIL/CANCEL/RESET; running PROGRESS/OFFLINE/COMPLETE/COMPLETE_WITH_ERRORS/FAIL/CANCEL/RESET; stalled STREAM_OPEN/PROGRESS/STALL_TICK/RECONNECTED/OFFLINE/COMPLETE/COMPLETE_WITH_ERRORS/FAIL/CANCEL/RESET; offline ONLINE(prev via `resumeStatus`)/FAIL/CANCEL/RESET; terminals START/RESET. All dashes are missing handlers (identity fallback).

Disagree:

| cell / flow | map | code | who is right |
| --- | --- | --- | --- |
| running × STALL_TICK | `stalled` unconditional | `stallIfQuiet` (30 s quiet) | **code + uxmap.json flow** ("stalled (30 s no event)"). Markdown table is underspecified. Known L6A-03. |
| job-stall-reconnect flow | md: fail after bounded reconnects (RES-06); json: "running \| failed" | no bound; FAIL is external | **map intent**. Code is a W1 hole (M-03). |
| idle × RESET | status `idle` | `resetIdle` wipes store | **code** if RESET means hard clear; map does not say. Tests do not pin it (M-06). |

JSON open question "navigator.onLine vs no-event timer" is answered in the reducer (distinct `offline` / `stalled`) and should stay distinct.

## Known findings, confirmed or refuted

- **FEBT-1-L6A-01 medium — confirmed.** `OFFLINE`/`ONLINE` carry no `at` (`jobMachine.ts:48-49`). `goOffline`/`goOnline` (`:119-138`) never write `lastEventAt`. ONLINE restores `resumeStatus` with the pre-offline clock. Next `STALL_TICK` on running uses a stale anchor and false-stalls after a long offline gap. Mutants 9–12 show the suite would not catch a fix or a regression on this field. Do not re-file; M-01 is the test-gap companion.
- **FEBT-1-L6A-02 low — confirmed.** Second `switch (event.type)` (`:259-275`) returns `state` in all twelve arms. It does **not** subvert GRPH-27: lookup is still `TRANSITIONS[state.status][event.type]` (state first). The switch is a `never` exhaustiveness sink for dash cells. Runtime-dead, compile-useful.
- **FEBT-1-L6A-03 low — confirmed.** Markdown table: running × STALL_TICK → stalled. Code: 30 s guard. JSON flow already has the 30 s. **Code is right**; update the markdown cell to `stalled (if quiet ≥ 30s) else running`. Table tests pass only because SAMPLE `STALL_TICK.now` is exactly the threshold.

Canon held (not filed): GRPH-27 keying is state-then-event. REF-20 is applied well (`stalled` and `completed_with_errors` are normal states, not thrown errors).

## Not-doing / out of scope

- Did not wire L6b/L6c (`useJobProgressStream` still has its own stall clock). Flagged only as REF-21 drift risk (M-08).
- Did not mutate test files or leave production dirty.
- Did not re-review AppError/logger W1 lanes.
- Did not run full `npx vitest run js/admin` (lane TEST_CMD); ran the owned jobMachine file + `npm run typecheck`.
- No high findings. Inventing one would overstate: the status table is real (CANCEL drop, `>=` flip, resumeStatus round-trip all died). The hole is liveness store + reconnect budget, not a broken reducer.
