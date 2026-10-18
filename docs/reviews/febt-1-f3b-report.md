# FEBT-1 F3B terminal lane report

Lane: `febt-1-f3b-terminal`. Task: `FEBT-1`.
Heuristics: https://github.com/darce/heuristics-canon (cite IDs only).
Rules applied: rg-015, DATA-14, OBS-06, REF-16, REF-19, RES-13, TEST-15, sr-001, sr-007.

Two implementation commits, not squashed. Findings referenced by id and test name.

## COMMIT 1 — FEBT1-W2D-05 + FEBT1-W2C-02

Subject: `fix(febt-1): W2D-05 terminal events carry real payload, not fabricated counts`

### What changed

`emitTerminal` in `useJobProgressStream.ts` stopped inventing contract metadata (rg-015, DATA-14, OBS-06):

- `COMPLETE_WITH_ERRORS.failedCount` is optional. When the SSE done payload does not carry a count, the dispatched event **omits** the key. A zero is not written.
- Parsed server `error` MessageEvent data is threaded into `FAIL.error.message`. Fallback `'job stream error'` is used only when no message was parsed (transport-level EventSource error). The literal `'stream failed'` is gone.
- `stream.done` logs no longer derive `failedCount` from status (`1` on FAILED / `undefined` on COMPLETE_WITH_ERRORS). The key is omitted. `last_error_code` is on the wire but `logJobEvent` / `JobLogStateSummary` cannot copy it without editing `logger.ts` (out of lane scope), so it is not fabricated into that record either.

Reducer: `completeWithErrors` copies `failedCount` only when the event carries it. No `?? 0` at the read site.

### Tests (names)

- `omits failedCount on completed_with_errors when the wire carries none (FEBT1-W2D-05)`
- `FAIL uses the parsed server error message, not the literal stream failed (FEBT1-W2C-02)`
- `FAILED terminal log record omits failedCount rather than deriving it (FEBT1-W2D-05)`

### RED (tests vs pre-fix emitTerminal)

```
 Test Files  1 failed | 2 passed (3)
      Tests  3 failed | 230 passed (233)

 FAIL  useJobProgressStream > omits failedCount on completed_with_errors when the wire carries none (FEBT1-W2D-05)
AssertionError: expected true to be false // Object.is equality
- Expected
+ Received
- false
+ true
 ❯ useJobProgressStream.test.tsx:289:42
    expect('failedCount' in (evt ?? {})).toBe(false);

 FAIL  useJobProgressStream > FAIL uses the parsed server error message, not the literal stream failed (FEBT1-W2C-02)
AssertionError: expected 'running' to be 'failed'
Expected: "failed"
Received: "running"
 ❯ useJobProgressStream.test.tsx:303:37
    expect(result.current.status).toBe(JOB_STATUS.FAILED);

 FAIL  useJobProgressStream > FAILED terminal log record omits failedCount rather than deriving it (FEBT1-W2D-05)
AssertionError: expected false to be true
 ❯ useJobProgressStream.test.tsx:326:83
    expect(logJobEventSpy.mock.calls.some((call) => call[1] === 'stream.done')).toBe(true);
```

### GREEN (after omit-rather-than-default)

```
 ✓ useJobProgressStream.test.tsx (11 tests) 98ms
 ✓ jobMachine.test.ts (205 tests) 51ms
 ✓ useJobProgressStreamHelpers.test.ts (17 tests) 15ms
 Test Files  3 passed (3)
      Tests  233 passed (233)
```

### TEST-15 proof (commit 1)

Broke `COMPLETE_WITH_ERRORS` by restoring `failedCount: 0`. Re-ran `omits failedCount on completed_with_errors when the wire carries none (FEBT1-W2D-05)`.

RED after break:

```
 FAIL  useJobProgressStream > omits failedCount on completed_with_errors when the wire carries none (FEBT1-W2D-05)
AssertionError: expected true to be false // Object.is equality
- Expected
+ Received
- false
+ true
 ❯ useJobProgressStream.test.tsx:289:42
    expect('failedCount' in (evt ?? {})).toBe(false);
 Tests  1 failed | 10 skipped (11)
```

GREEN after restore:

```
 ✓ useJobProgressStream.test.tsx (11 tests | 10 skipped) 35ms
      Tests  1 passed | 10 skipped (11)
```

Then full scoped gate: 233 passed.

## COMMIT 2 — FEBT1-W2D-03 residual

Subject: `fix(febt-1): W2D-03 remove the dead RECONNECTED edge`

### Decision

**Deleted `RECONNECTED` entirely** (delete-over-flag / REF-16, REF-19). STREAM_OPEN-from-stalled already routes through `applyReconnect` and is the live reconnect counter (RES-13). The RECONNECTED tests did not encode behaviour STREAM_OPEN-from-stalled lacked.

Removed: `JOB_EVENT` key, union member, `reconnect` handler, `TRANSITIONS.stalled` entry, exhaustive switch case. Tests updated. Added `reconnect after a stall increments reconnectAttempts exactly once via STREAM_OPEN`.

### RED (production deletion before test update)

```
 Test Files  1 failed | 2 passed (3)
      Tests  10 failed | 216 passed (226)

 FAIL  jobReducer table (FEBT-1 L6a) > 'idle' + 'undefined' => undefined
TypeError: Cannot read properties of undefined (reading 'type')
 ❯ jobReducer jobMachine.ts:316:51
 ❯ jobMachine.test.ts:295:18
 (same for pending/running/stalled/offline/completed/completed_with_errors/failed)

 FAIL  compile-time exhaustiveness tables > covers every JobMachineStatus and JobEvent type exactly once
AssertionError: expected [ 'START', 'STREAM_OPEN', …(10) ] to deeply equal [ 'START', 'STREAM_OPEN', …(9) ]
+   "undefined",
    "OFFLINE",
 ❯ jobMachine.test.ts:480:29

 FAIL  M-01 handler writes > RECONNECTED writes lastEventAt
Error: Unhandled job-machine value: {"at":11000}
 ❯ assertNever jobMachine.ts:88:9
 ❯ jobReducer jobMachine.ts:337:14
 ❯ jobMachine.test.ts:541:20
```

### GREEN (after test update)

```
 ✓ jobMachine.test.ts (190 tests) 51ms
 ✓ useJobProgressStream.test.tsx (11 tests) 103ms
 ✓ useJobProgressStreamHelpers.test.ts (17 tests) 15ms
 Test Files  3 passed (3)
      Tests  218 passed (218)
```

### TEST-15 proof (commit 2)

Broke `openStream` so STREAM_OPEN-from-stalled skipped `applyReconnect`. Re-ran `reconnect after a stall increments reconnectAttempts exactly once via STREAM_OPEN`.

RED after break:

```
 FAIL  FEBT1-W2D-03 STREAM_OPEN from stalled is the surviving reconnect path > reconnect after a stall increments reconnectAttempts exactly once via STREAM_OPEN
AssertionError: expected +0 to be 1 // Object.is equality
- Expected
+ Received
- 1
+ 0
 ❯ jobMachine.test.ts:739:40
    expect(reopened.reconnectAttempts).toBe(1);
 Tests  1 failed | 189 skipped (190)
```

GREEN after restore:

```
 ✓ jobMachine.test.ts (190 tests | 189 skipped) 6ms
      Tests  1 passed | 189 skipped (190)
```

Then full scoped gate: 218 passed.

### Grep after deletion

Command: `grep -rn RECONNECTED --include='*.ts' --include='*.tsx' . | grep -v __tests__`

Output:

```
(no matches)
```

Chosen outcome: nothing outside tests. No dispatch site because the edge is gone.

## Scoped gate (final)

```
cd apps/prototype-wp-alt-context && npx vitest run \
  js/admin/hooks/__tests__/jobMachine.test.ts \
  js/admin/hooks/__tests__/useJobProgressStream.test.tsx \
  js/admin/hooks/__tests__/useJobProgressStreamHelpers.test.ts
```

218 passed / 3 files. Did not run `npm run test`, `npm run typecheck`, or `npm run lint` (sr-001; lint owned elsewhere).

## Out of scope / notes

- Did not re-fix W2D-01 / W2D-02 / W2D-04 (already on base).
- Did not add a second terminal guard on the progress listener.
- Did not touch `appError.ts`, `http.ts`, `retryPolicy.ts`, or `pages/workbench/identity-clusters/`.
- `docs/ux-maps/` is absent in this checkout; not created.
- Handoff MCP / `workbay_handoff_mcp` Python API were not importable in this sandbox venv; decisions live in this report for orchestrator harvest.
