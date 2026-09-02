# Lens C — test strength
**Verdict:** IN PROGRESS

Observed HEAD for this lane: `4aee7a9` (sandbox snapshot; object `82bb245a0` is not in this clone). Numbers below are from files read at this HEAD, not from `docs/reviews/` evidence dumps.

### F-1 parseRetryAfter HTTP-date branch has no assertion
- severity: high
- file:line (test): `apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts:198-212`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/utils/http.ts:107-110`
- rule: TEST-15, TEST-11, TEST-06
- evidence:
```
describe('parseRetryAfter', () => {
  it('parses non-negative delta-seconds', () => {
    expect(parseRetryAfter('5')).toBe(5);
    expect(parseRetryAfter('0')).toBe(0);
    expect(parseRetryAfter('120')).toBe(120);
  });

  it('returns undefined for missing or malformed values (never NaN)', () => {
    expect(parseRetryAfter(null)).toBeUndefined();
    expect(parseRetryAfter('')).toBeUndefined();
    expect(parseRetryAfter('  ')).toBeUndefined();
    expect(parseRetryAfter('soon')).toBeUndefined();
    expect(parseRetryAfter('-3')).toBeUndefined();
    expect(parseRetryAfter('5.5')).toBeUndefined();
  });
});
```
Comment on production (`http.ts:85`) says "Accepts delta-seconds or HTTP-date". No test in this file contains `Date.parse`, `HTTP-date`, or an RFC 7231 date string.
- mutant: in `http.ts:107-110`, delete the HTTP-date branch (`const t = Date.parse(trimmed); if (!Number.isNaN(t)) { return Math.max(0, Math.ceil((t - Date.now()) / 1000)); }`). `parseRetryAfter('Wed, 21 Oct 2015 07:28:00 GMT')` becomes `undefined`; every existing test stays GREEN.
- fix: freeze time and assert `parseRetryAfter(<HTTP-date>)` returns the ceil-delta in seconds, plus a past-date → `0` pin.

### F-2 DEFAULT_FETCH_TIMEOUT_MS is only compared to itself
- severity: high
- file:line (test): `apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts:504-525`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/utils/http.ts:4` and `http.ts:171-173`
- rule: TEST-15, TEST-06, TEST-17
- evidence:
```
it('rejects a hung fetch within the default deadline as a classified abort', async () => {
    hungFetch();

    let rejected: unknown;
    void fetchApi(REST_URL).then(
      () => {
        throw new Error('expected hung fetch to reject');
      },
      (error: unknown) => {
        rejected = error;
      },
    );

    await vi.advanceTimersByTimeAsync(DEFAULT_FETCH_TIMEOUT_MS - 1);
    expect(rejected).toBeUndefined();

    await vi.advanceTimersByTimeAsync(1);

    expect(rejected).toBeInstanceOf(DOMException);
    expect((rejected as DOMException).name).toBe('TimeoutError');
    expect(classifyError(rejected)._tag).toBe('abort');
  });
```
No literal `300_000` (or `5 * 60 * 1000`) appears in this test file. Production is `export const DEFAULT_FETCH_TIMEOUT_MS = 300_000`.
- mutant: `http.ts:4` change `300_000` → `60_000`. The test still advances `DEFAULT_FETCH_TIMEOUT_MS - 1` then `+1`, so it stays GREEN while the product deadline silently becomes 1 minute.
- fix: pin a literal (`expect(DEFAULT_FETCH_TIMEOUT_MS).toBe(300_000)`) and keep the hung-fetch behaviour on that literal, matching jobMachine's 30_000 stall pin.

### F-3 applyProgress reconnectAttempts reset is unasserted
- severity: high
- file:line (test): `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/jobMachine.test.ts:203-207` and `:231-238`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:114`
- rule: TEST-15, TEST-17, REF-29
- evidence:
```
it.each(tableCells)('$status + $eventType => $expected', ({ status, eventType, expected }) => {
    const state = fixtureFor(status);
    const next = jobReducer(state, SAMPLE_EVENTS[eventType]);
    expect(next.status).toBe(expected ?? status);
  });
```
```
it('PROGRESS updates done/total/lastEventAt and keeps status running', () => {
    const state = fixtureFor(JOB_MACHINE_STATE.running);
    const next = jobReducer(state, { type: JOB_EVENT.PROGRESS, done: 7, total: 20, at: 9_000 });
    expect(next).not.toBe(state);
    expect(next.status).toBe(JOB_MACHINE_STATE.running);
    expect(next.done).toBe(7);
    expect(next.total).toBe(20);
    expect(next.lastEventAt).toBe(9_000);
  });
```
`fixtureFor` always sets `reconnectAttempts: 0`. Grep of this test file for `reconnectAttempts` hits only the fixture (`:189`) and `initialJobState` equality (`:328`). No test reads `next.reconnectAttempts` after a PROGRESS/START event.
- mutant: in `jobMachine.ts:114`, delete `reconnectAttempts: 0,` from `applyProgress`. A stalled job that then receives PROGRESS keeps its attempt counter; the fourth later stall still fails in M-03 because that test never sends PROGRESS. Table + PROGRESS tests stay GREEN.
- fix: start from `reconnectAttempts: 2`, dispatch PROGRESS, assert `next.reconnectAttempts === 0`, then prove one subsequent stall does not fail.

### F-4 jobReducer table only asserts status; CANCEL need not reset
- severity: high
- file:line (test): `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/jobMachine.test.ts:203-207`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:244` (`pending` CANCEL → `resetIdle`)
- rule: TEST-15, TEST-17, REF-29
- evidence:
```
it.each(tableCells)('$status + $eventType => $expected', ({ status, eventType, expected }) => {
    const state = fixtureFor(status);
    const next = jobReducer(state, SAMPLE_EVENTS[eventType]);
    expect(next.status).toBe(expected ?? status);
  });
```
`EXPECTED_STATUS[pending].CANCEL` is `idle`. There is no `it(...)` that reads `jobId` / `done` / `total` / `error` after CANCEL. RESET from running only checks `lastEventAt` and `resumeStatus` (`:412-416`). The 8×12 table covers every `JOB_EVENT` variant for **status** (no missing event type); it does not cover payload fields.
- mutant: `jobMachine.ts:244` change `[JOB_EVENT.CANCEL]: resetIdle` to `[JOB_EVENT.CANCEL]: (s) => ({ ...s, status: JOB_MACHINE_STATE.idle })`. pending+CANCEL still reports status `idle`; the table stays GREEN; a cancelled job keeps `jobId: 'job-1'`, `done: 5`, `total: 10`.
- fix: after CANCEL from a non-idle fixture, `expect(next).toEqual(initialJobState)` (same pin M-06 already uses for RESET-from-idle).

### F-5 negative stall-tick delta is an untested branch
- severity: medium
- file:line (test): `apps/prototype-wp-alt-context/js/admin/hooks/__tests__/jobMachine.test.ts:528-537`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:137`
- rule: TEST-15, TEST-11
- evidence:
```
it('does not stall on a 6-hour jump in one tick', () => {
      const state = fixtureFor(JOB_MACHINE_STATE.running);
      const sixHours = AT + 6 * 60 * 60 * 1000;
      const jumped = jobReducer(state, { type: JOB_EVENT.STALL_TICK, now: sixHours });
      expect(jumped.status).toBe(JOB_MACHINE_STATE.running);

      const after = jobReducer(jumped, { type: JOB_EVENT.STALL_TICK, now: sixHours + 31_000 });
      expect(after.status).toBe(JOB_MACHINE_STATE.stalled);
    });
```
M-05 covers `delta > JOB_MACHINE_MAX_TICK_DELTA_MS` (forward jump). Production is `if (delta < 0 || delta > JOB_MACHINE_MAX_TICK_DELTA_MS)`. No test dispatches `STALL_TICK` with `now < lastEventAt`.
- mutant: `jobMachine.ts:137` change `delta < 0 || delta > JOB_MACHINE_MAX_TICK_DELTA_MS` to `delta > JOB_MACHINE_MAX_TICK_DELTA_MS`. A clock-rewind tick (`now = AT - 1`) then falls into stall/identity logic; M-05 stays GREEN.
- fix: dispatch `STALL_TICK` with `now: AT - 1` from a running fixture, assert status stays running and `lastEventAt` becomes `AT - 1`, then a +31s tick from that new origin stalls.

### F-6 RETRY_MAX_ATTEMPTS bound is compared only to itself
- severity: medium
- file:line (test): `apps/prototype-wp-alt-context/js/admin/utils/__tests__/retryPolicy.test.ts:104-108`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/utils/retryPolicy.ts:4` and `:24`
- rule: TEST-15, TEST-06, TEST-17
- evidence:
```
it('is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class', () => {
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS - 1, httpError(429))).toBe(true);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, httpError(429))).toBe(false);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, new TypeError('Failed to fetch'))).toBe(false);
  });
```
Contrast: `clusterAutoRetry.test.ts:40` pins `expect(CLUSTER_RETRY_MAX_ATTEMPTS).toBe(3)`. This file never writes the literal `3` against `RETRY_MAX_ATTEMPTS`.
- mutant: `retryPolicy.ts:4` change `export const RETRY_MAX_ATTEMPTS = 3` to `export const RETRY_MAX_ATTEMPTS = 4`. The bound test still uses the constant, so it stays GREEN while QueryClient now retries one extra time.
- fix: add `expect(RETRY_MAX_ATTEMPTS).toBe(3)` and keep the `failureCount` 2/3 behaviour on those literals.

### F-7 HTTP 205 empty-body branch has no covering test
- severity: medium
- file:line (test): `apps/prototype-wp-alt-context/js/admin/utils/__tests__/http.test.ts:51-57`
- file:line (production): `apps/prototype-wp-alt-context/js/admin/utils/http.ts:232-235`
- rule: TEST-15, TEST-11
- evidence:
```
it('returns undefined for 204 responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    const result = await fetchApi<void>('http://example.test/endpoint', { method: 'POST' });

    expect(result).toBeUndefined();
  });
```
Production:
```
// 204/205 intentionally return no body.
if (response.status === 204 || response.status === 205) {
  return undefined;
}
```
No `205` appears in `http.test.ts`.
- mutant: `http.ts:233` change `response.status === 204 || response.status === 205` to `response.status === 204`. A 205 with a JSON body is then parsed (or throws); the 204 test stays GREEN.
- fix: add a 205 case that returns `undefined` even when the mock body is non-empty, so dropping the 205 clause fails.
