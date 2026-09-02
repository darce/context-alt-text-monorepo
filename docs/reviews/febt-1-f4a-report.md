# FEBT-1 F4A errors lane — FEBT1-W2A-05 then FEBT1-W2A-01

Lane: `febt-1-f4a-errors`  
Branch: `feature/febt-1-f4a`  
Commits: `a2e7f75` (W2A-05), `e9ff200` (W2A-01)

Canon applied: REF-01, REF-19, REF-20, REF-29, REF-33, RES-06, RES-13, RLSE-05, TEST-15, sr-001, sr-007, rg-015.

## COMMIT 1 — FEBT1-W2A-05 split `timeout` out of `abort`

`TimeoutError` and `AbortError` no longer collapse to `_tag: 'abort'`.

- Added `'timeout'` to `APP_ERROR_TAGS`, `APP_ERROR_TAG_INDEX`, the `AppError` union, `isAppError`, and `logger.ts` `safeAppErrorMessage`.
- `classifyError` routes name `'TimeoutError'` → `_tag: 'timeout'` and `'AbortError'` → `_tag: 'abort'` via duck-typed `name` (not `instanceof DOMException`).
- Deduped http.ts: deleted private `ABORT_LIKE_NAMES` / `isAbortLikeError`; http imports shared `isAbortOrTimeoutName`.
- Renamed lying `isAbortLike` → `isAbortOrTimeout` (`abort` **or** `timeout`). Polling uses that. Retry uses the narrow tags.
- `shouldRetryRequest`: `_tag === 'abort'` never retries; `_tag === 'timeout'` retries once (`failureCount < 1`). WHY: a 300s timeout retried on the transport budget multiplies a slow-backend incident into a multi-minute hang (retry amplification / circuit-breaker family, Release It!). RES-13 / RES-06.
- User-facing copy, verbatim: `The server took too long to respond — try again`. Abort still uses the caller fallback.
- `getDescribeRunRefetchInterval` keeps polling on timeout (`not.toBe(false)` regression guard). Frozen-poll streak still counts timeout.

### clusterMutationUtils.isAbortError — decision

**Keep `isAbortError` as abort-only** (`classifyError(err)._tag === 'abort'`). A timed-out cluster mutation is not a user cancel.

- User cancel: silent / non-retryable; must not announce a slow server.
- Timeout: bounded retry + timeout copy.
- Cluster UI still has a message-sniff for `timed out`/`timeout` (`Save is taking too long. Please try again.`) as a fallback for untagged Errors. That sniff is not `isAbortError`. Abort copy in that helper is unchanged.

### COMMIT 1 TEST-15 proof (classify TimeoutError → timeout)

RED (tests first, old classifier still maps TimeoutError → abort):

```
 FAIL  js/admin/utils/__tests__/appError.test.ts > classifyError > classifies TimeoutError as timeout and AbortError as abort — distinguishable [FEBT1-W2A-05]
AssertionError: expected 'abort' to be 'timeout' // Object.is equality

Expected: "timeout"
Received: "abort"

 ❯ js/admin/utils/__tests__/appError.test.ts:95:41
     93|     const timeout = { name: 'TimeoutError', message: 'timed out' };
     94|     const abort = { name: 'AbortError', message: 'aborted' };
     95|     expect(classifyError(timeout)._tag).toBe('timeout');

 FAIL  js/admin/utils/__tests__/retryPolicy.test.ts > shouldRetryRequest > retries a timeout once and never retries a user abort [FEBT1-W2A-05]
AssertionError: expected false to be true // Object.is equality
- true
+ false
 ❯ js/admin/utils/__tests__/retryPolicy.test.ts:94:47
     94|     expect(shouldRetryRequest(0, timeoutErr)).toBe(true);

 FAIL  js/admin/utils/__tests__/http.test.ts > fetchApi default timeout [E-04] > rejects a hung fetch within the default deadline as a classified timeout
AssertionError: expected 'abort' to be 'timeout'
 ❯ js/admin/utils/__tests__/http.test.ts:653:42
    653|     expect(classifyError(rejected)._tag).toBe('timeout');

 Test Files  4 failed | 1 passed (5)
      Tests  10 failed | 101 passed (111)
```

GREEN after implementation:

```
 ✓ js/admin/utils/__tests__/http.test.ts (38 tests) 94ms
 ✓ js/admin/utils/__tests__/appError.test.ts (29 tests) 24ms
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 22ms
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (4 tests) 9ms
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 271ms

 Test Files  5 passed (5)
      Tests  111 passed (111)
```

## COMMIT 2 — FEBT1-W2A-01 close the fetch boundary

Every value thrown from `fetchApi` / `fetchRequiredApi` is `instanceof Error` **and** `isAppError`. Did **not** `throw classifyError(err)` (plain object, no stack).

- Classes carry the tag: `HTTPError._tag = 'http'` (+ `retryAfterMs` getter), `ResponseParseError` → `parse`, `AuthExpiredError` → `auth_expired`, `NonceRefreshFailedError` → `nonce_refresh`. `classifyError` already short-circuits `if (isAppError(e)) return e`.
- `throwAsAppError` at the fetch catch: tagged Errors rethrown; other `Error` instances stamped; non-Error (jsdom `DOMException` is **not** `instanceof Error`) wrapped in `new Error` preserving `name` and a stack.
- Existing `instanceof HTTPError` call sites kept (expand now, contract later). REF-19 / REF-29 / RLSE-05.

Table test covers 4xx→http, non-JSON→parse, `rest_not_logged_in`→auth_expired, TypeError→transport, hung fetch→timeout, user cancel→abort. Assertions use `isAppError` + `_tag` on the thrown value — no `classifyError` in the assertion.

### COMMIT 2 TEST-15 proof (break `throwAsAppError` to `throw error`)

RED:

```
 FAIL  ... > 'transport failure → transport' is instanceof Error, isAppError, and keeps a stack
AssertionError: expected false to be true
 ❯ expectThrownAppError js/admin/utils/__tests__/http.test.ts:722:33
    722|       expect(isAppError(error)).toBe(true);

 FAIL  ... > 'hung fetch → timeout' is instanceof Error, isAppError, and keeps a stack
AssertionError: expected DOMException{ stack: 'TimeoutError: …', …(1) } to be an instance of Error
 ❯ expectThrownAppError js/admin/utils/__tests__/http.test.ts:721:21
    721|       expect(error).toBeInstanceOf(Error);

 FAIL  ... > 'user cancel → abort' is instanceof Error, isAppError, and keeps a stack
AssertionError: expected DOMException{ stack: 'AbortError: Th…', …(1) } to be an instance of Error

 Test Files  1 failed (1)
      Tests  3 failed | 3 passed | 38 skipped (44)
```

Tagged classes (4xx/parse/auth_expired) still passed — `_tag` on the class is load-bearing. Stamping/wrapping is load-bearing for transport/timeout/abort.

GREEN after restore:

```
 ✓ js/admin/utils/__tests__/http.test.ts (44 tests) 105ms
 ✓ js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx (13 tests) 256ms
 ✓ js/admin/utils/__tests__/appError.test.ts (29 tests) 24ms
 ✓ js/admin/utils/__tests__/retryPolicy.test.ts (27 tests) 23ms
 ✓ js/admin/utils/__tests__/userFacingError.test.ts (4 tests) 9ms

 Test Files  5 passed (5)
      Tests  117 passed (117)
```

Initial RED for the new table (before any class tags / catch wrapper), 6/6 paths failed `isAppError` or `instanceof Error`:

```
 Test Files  1 failed (1)
      Tests  6 failed | 38 passed (44)
AssertionError: expected false to be true   // 4xx, parse, auth_expired, transport
AssertionError: expected DOMException{…} to be an instance of Error  // timeout, abort
```

## Gate

```
cd apps/prototype-wp-alt-context && npx vitest run \
  js/admin/utils/__tests__/appError.test.ts \
  js/admin/utils/__tests__/http.test.ts \
  js/admin/utils/__tests__/userFacingError.test.ts \
  js/admin/utils/__tests__/retryPolicy.test.ts \
  js/admin/hooks/__tests__/useDescribeRunProgress.test.tsx
```

Final: 117/117 pass. Did not run `npm run lint` (pre-existing red; sr-001). Did not run the whole package suite.
