# Lens D — state machine & composition (local Claude reviewer)

**Verdict:** FINDINGS FOUND

Tree: `feature/febt-1` @ `82bb245a0e6ca6cbb2bc354750a30ebcd7cf3e89`, true base `08379faf30dfa7b2d6e840b02920d96466de0a5b`.
Read-only lens: no production file was edited, no suite was run locally (all suites belong on the remote gate).

## F-1 Objective 2 is not met: the job machine is dispatched to, never adopted

- severity: **high**
- file: `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts:62`
- rule: DATA-14 (single source of truth), REF-40, card `evidence-before-commitment`
- evidence:

```
const [, dispatch] = useReducer(jobReducer, initialJobState);
```

`grep -rn "jobMachine\|jobReducer\|JobMachineState" --include=*.ts --include=*.tsx .` outside `hooks/jobMachine.ts` and its test matches **only** `useJobProgressStream.ts`, and only for `JOB_EVENT` / `dispatch` / `initialJobState` / `jobReducer`. Every field the hook actually returns (`progress`, `status`, `etaSeconds`, `lastEventAt`, `stalledForSeconds`, `isOnline`) is a separate `useState` slot written directly by the SSE listeners (`:243-249`, `:268-273`). The reducer's transition table, terminal guards, offline/`resumeStatus` resume path and reconnect ceiling are unreachable in production.

- failure scenario: the branch reads as delivering "convert the job state machine to a typed `useReducer` machine with named events" — `jobMachine.test.ts` (555 lines) is green, `JOB_EVENT` appears in production code, and no dead-code lint fires because `dispatch` is called. But no rendered transition passes through the machine. A maintainer who later fixes a status bug by editing `TRANSITIONS` changes nothing a user can observe, and the green test file confirms the edit.
- fix: consume the state (`const [machine, dispatch] = …`, derive the returned fields from `machine`, delete the parallel `useState` slots) — **but not before F-2** — or delete `jobMachine.ts` + its test and record the objective as not met.
- adjudicates banked **FEBT1-W2C-01**: upheld, raised medium → high. It is an objective-not-met finding, not a tidiness nit.

## F-2 The machine is not safe to adopt: quiet time is counted as reconnect attempts, so a healthy slow job is failed

- severity: **high**
- file: `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:127-152`
- rule: RES-06 (the comment cites it; the counter measures the wrong thing), RES-13, NAME-*
- evidence:

```
const onQuietTick = (state, event, quietStatus) => {
  ...
  if (delta < JOB_MACHINE_STALL_THRESHOLD_MS) { return state; }
  const attempts = state.reconnectAttempts + 1;
  if (attempts > JOB_MACHINE_RECONNECT_CEILING) {
    return failReconnectCeiling(state, attempts, event.now);
  }
  return { ...state, status: quietStatus, lastEventAt: event.now, reconnectAttempts: attempts };
};
```

`stallIfQuiet` and `boundOfflineWait` both route through it. Each quiet transition rewrites `lastEventAt = event.now`, so the counter advances once per `JOB_MACHINE_STALL_THRESHOLD_MS` (30 000 ms) of silence. With `JOB_MACHINE_RECONNECT_CEILING = 3`, **120 s of silence ⇒ `status: 'failed'`, `error.message = "Reconnect ceiling exceeded (4 attempts)"`.** Only `applyProgress` resets `reconnectAttempts` to 0. Nothing reconnected; nothing was attempted.

- failure scenario: a describe run on the burst-GPU path waits on model warmup, or a single large image takes >120 s between `progress` frames. The stream is healthy and `EventSource.readyState === OPEN`. The moment F-1 is fixed by simply un-discarding the reducer state, the UI flips to a terminal **Failed** with a reconnect message that names an event type (`RECONNECTED`) the production code never dispatches. The job continues server-side; the operator is told it failed.
- fix: separate the two counters — a stall/quiet counter that only drives the display state, and a reconnect counter incremented at an actual reconnect site. Do not make a quiet stream terminal without a `done`/`error` frame or an explicit transport failure.

## F-3 `RECONNECTED` is a named event with zero production dispatch sites

- severity: medium
- file: `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:42`
- rule: REF-16, ARCH-* (unreachable branch presented as behavior)
- evidence: `grep -rn "RECONNECTED" --include=*.ts --include=*.tsx .` outside tests returns only the four definition sites in `jobMachine.ts` (`:42`, `:57`, `:161`, `:261`, `:317`). The hook's `retry()` (`:69-76`) bumps `connectionNonce` to force a fresh `EventSource` and never dispatches. So the only edge out of `stalled` back to `running` other than `PROGRESS` is dead, and `reconnectAttempts` has no reset path other than progress.
- failure scenario: compounds F-2 — after a reconnect the counter keeps its pre-reconnect value, so the ceiling fires earlier than the constant advertises.
- fix: dispatch `RECONNECTED` from `retry()` / the `open` handler, or delete the event, the handler and the `stalled → RECONNECTED` table entry.

## F-4 The terminal invariant is encoded in the machine and absent from the path that renders

- severity: medium
- file: `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts:229-249`
- rule: DATA-14, REF-19
- evidence: `TRANSITIONS[completed]` and `TRANSITIONS[failed]` accept only `START` and `RESET` (`:277-287`) — the machine states the invariant "no PROGRESS after a terminal event". The rendering path has no such guard; the `progress` listener checks only the cleanup flag:

```
eventSource.addEventListener('progress', (event) => {
  if (closed) { return; }
  ...
  setProgress(parsed.progress);
  setStatus(parsed.status);
```

`closed` is set only in the effect teardown (`:200`), not by the `done` handler, and the `done` handler does not close the source. A late or duplicate `progress` frame delivered after `done` therefore regresses the rendered status out of the terminal state.
- failure scenario: server flushes a buffered `progress` frame after `done`. UI moves from "Completed" back to a running progress bar with no way to reach terminal again except another `done`.
- fix: guard the listener on the terminal statuses (or adopt the machine per F-1 after F-2 is fixed, which gives the guard for free).

## F-5 `emitTerminal` invents payload fields to satisfy the event types

- severity: medium
- file: `apps/prototype-wp-alt-context/js/admin/hooks/useJobProgressStream.ts:205-220`
- rule: **rg-015** (boundary adapters must not invent contract metadata), OBS-06
- evidence:

```
if (nextStatus === JOB_STATUS.COMPLETED_WITH_ERRORS) {
  dispatch({ type: JOB_EVENT.COMPLETE_WITH_ERRORS, failedCount: 0, at });
} else if (nextStatus === JOB_STATUS.FAILED) {
  dispatch({ type: JOB_EVENT.FAIL, error: { message: 'stream failed' } });
}
...
  failedCount: nextStatus === JOB_STATUS.FAILED ? 1 : undefined,
```

`failedCount: 0` is hardcoded on the one status whose definition is a non-zero failure count; `'stream failed'` is a literal standing in for a server reason; the logged `failedCount` (`1` on FAILED, `undefined` on COMPLETE_WITH_ERRORS) is the inverse of the dispatched one. Three different fabricated values for the same concept in one function.
- failure scenario: adopting the machine (F-1) surfaces `failedCount: 0` in the "completed with errors" UI, and the structured log for the same event reports a different number than the state does.
- fix: carry the real counts on the `done`/`error` frame through `parseDoneEvent` and pass them; if the wire does not carry them, do not invent them — omit the field and widen the event type.
- adjudicates banked **FEBT1-W2C-02**: upheld at medium, with rg-015 as the governing guard rather than a style preference.

## VERDICT
FINDINGS FOUND
