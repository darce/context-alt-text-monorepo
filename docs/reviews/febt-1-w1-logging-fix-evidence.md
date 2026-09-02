# FEBT-1 W1 logger fix evidence

Lane: `febt-1-fix-logging`. Branch: `fix/febt-1-w1-logging`.
RED captured against stubs + the O-07 recursion mutant before production behavior landed.
GREEN: `npx vitest run js/admin/utils/__tests__/logger.test.ts` → `Tests  22 passed (22)`.
Full lane verification: `npx vitest run js/admin` → `Test Files  231 passed (231)` / `Tests  2889 passed (2889)`; `npm run typecheck` exit 0.

Call sites `main.tsx` and `useJobPersistence.ts` already use `createLogger(scope)`, which now binds `requestId` at the logger boundary. Neither site has a job id at construction, so `createJobLogger` is the wave-2 factory rather than a fake module-level job id.

One existing assertion was adapted, not weakened: `setLogSink(null) restores the default console sink` still proves sink restoration. After O-01, `createLogger('x')` always has fields, so the expected `console.warn` args now include `{ requestId }`. The dedicated empty-fields `consoleSink` test is unchanged.

## O-01 — correlation id is bound at the logger boundary (OBS-03)

Tests:

- `createLogger without fields still emits requestId on every level [O-01][OBS-03]`
- `two loggers receive distinct request ids [O-01][OBS-03]`
- `child logger inherits the parent requestId [O-01][OBS-03]`
- `createJobLogger records jobId and requestId on every line [O-01][OBS-03]`

RED (assertion lines):

```
FAIL  js/admin/utils/__tests__/logger.test.ts > correlation id binding [O-01] > createLogger without fields still emits requestId on every level [O-01][OBS-03]
AssertionError: expected undefined to deeply equal Any<String>
- Expected:
Any<String>
+ Received:
undefined
 ❯ js/admin/utils/__tests__/logger.test.ts:245:23
    245|     expect(requestId).toEqual(expect.any(String));

FAIL  js/admin/utils/__tests__/logger.test.ts > correlation id binding [O-01] > two loggers receive distinct request ids [O-01][OBS-03]
AssertionError: expected undefined to deeply equal Any<String>
 ❯ js/admin/utils/__tests__/logger.test.ts:258:41
    258|     expect(records[0].fields.requestId).toEqual(expect.any(String));

FAIL  js/admin/utils/__tests__/logger.test.ts > correlation id binding [O-01] > child logger inherits the parent requestId [O-01][OBS-03]
AssertionError: expected undefined to deeply equal Any<String>
 ❯ js/admin/utils/__tests__/logger.test.ts:272:23
    272|     expect(requestId).toEqual(expect.any(String));

FAIL  js/admin/utils/__tests__/logger.test.ts > correlation id binding [O-01] > createJobLogger records jobId and requestId on every line [O-01][OBS-03]
AssertionError: expected undefined to deeply equal Any<String>
 ❯ js/admin/utils/__tests__/logger.test.ts:287:23
    287|     expect(requestId).toEqual(expect.any(String));
```

GREEN: `Tests  22 passed (22)` in `logger.test.ts`; `Tests  2889 passed (2889)` for `js/admin`.

## O-02 — wide-event API for a job unit of work (OBS-02)

Test:

- `emits exactly one wide record with event, state, job id, and request id [O-02][OBS-02]`

RED (assertion lines):

```
FAIL  js/admin/utils/__tests__/logger.test.ts > logJobEvent [O-02] > emits exactly one wide record with event, state, job id, and request id [O-02][OBS-02]
AssertionError: expected [] to have a length of 1 but got +0
- Expected
+ Received
- 1
+ 0
 ❯ js/admin/utils/__tests__/logger.test.ts:311:21
    311|     expect(records).toHaveLength(1);
```

GREEN: `Tests  22 passed (22)` in `logger.test.ts`; `Tests  2889 passed (2889)` for `js/admin`.

`logJobEvent` is shipped as API-only. It is not wired into the job machine.

## O-03 — boundary errors do not leak response bodies (REF-19)

Tests:

- `HTTPError message secrets are absent from the serialized record [O-03][REF-19]`
- `ResponseParseError and NonceRefreshFailedError omit bodyPreview and raw message [O-03][REF-19]`
- `HTTPError as Error.cause is a plain projection, never the class instance [O-03][REF-19]`
- `plain Error message still round-trips [O-03]` (stayed green against the old suite; kept as the round-trip pin)

RED (assertion lines):

```
FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > HTTPError message secrets are absent from the serialized record [O-03][REF-19]
AssertionError: expected '{"ts":1788362577277,"level":"error","…' not to contain 'SECRET_BODY_LEAK_XYZ_42'
Expected: "SECRET_BODY_LEAK_XYZ_42"
Received: "{"ts":1788362577277,"level":"error","scope":"http","message":"request failed","fields":{"error":{"name":"HTTPError","message":"Request to http://example.test/jobs failed (500): SECRET_BODY_LEAK_XYZ_42"}}}"
 ❯ js/admin/utils/__tests__/logger.test.ts:336:28
    336|     expect(serialized).not.toContain(BODY_SECRET);

FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > ResponseParseError and NonceRefreshFailedError omit bodyPreview and raw message [O-03][REF-19]
AssertionError: expected '[{"ts":1788362577282,"level":"error",…' not to contain 'SECRET_BODY_LEAK_XYZ_42'
 ❯ js/admin/utils/__tests__/logger.test.ts:376:28
    376|     expect(serialized).not.toContain(BODY_SECRET);

FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > HTTPError as Error.cause is a plain projection, never the class instance [O-03][REF-19]
AssertionError: expected '{"ts":1788362577289,"level":"error","…' not to contain 'SECRET_BODY_LEAK_XYZ_42'
 ❯ js/admin/utils/__tests__/logger.test.ts:394:44
    394|     expect(JSON.stringify(records[0])).not.toContain(BODY_SECRET);
```

Projection: HTTPError → `{ name, message: "HTTP <status>", status, endpoint: pathname }`; ResponseParseError → `{ name, message: "JSON parse error", status, endpoint: pathname }`; NonceRefreshFailedError → `{ name, message: "Nonce refresh failed" }`. `bodyPreview` is omitted. Endpoint is pathname-only (query stripped). Cause is never a class instance.

GREEN: `Tests  22 passed (22)` in `logger.test.ts`; `Tests  2889 passed (2889)` for `js/admin`.

## O-05 — flattenFieldValue projects AppError (REF-19 / REF-21)

Test:

- `AppError field values flatten to a tagged safe projection [O-05][REF-19]`

RED (assertion lines):

```
FAIL  js/admin/utils/__tests__/logger.test.ts > boundary error redaction [O-03][O-05] > AppError field values flatten to a tagged safe projection [O-05][REF-19]
AssertionError: expected { _tag: 'http', status: 500, …(3) } to deeply equal { tag: 'http', …(3) }
- Expected
+ Received
  {
-   "endpoint": "/jobs",
-   "message": "HTTP 500",
+   "_tag": "http",
+   "cause": HTTPError { ... bodyPreview ... },
+   "endpoint": "http://example.test/jobs?token=SECRET_QUERY_TOKEN_XYZ_42",
+   "message": "Request to http://example.test/jobs failed (500): SECRET_BODY_LEAK_XYZ_42",
  }
 ❯ js/admin/utils/__tests__/logger.test.ts:409:37
    409|     expect(records[0].fields.error).toEqual({
```

`flattenFieldValue` calls `isAppError` and uses the same endpoint/message redaction helpers as O-03. Projection is exactly `{ tag, message, status?, endpoint? }`.

GREEN: `Tests  22 passed (22)` in `logger.test.ts`; `Tests  2889 passed (2889)` for `js/admin`.

## O-07 — two-level cause fixture kills the recursion-guard mutant (TEST-15)

Test:

- `follows cause only one level in a two-level chain [O-07][TEST-15]`

Surviving mutant: `flattenError(value.cause, false)` → `flattenError(value.cause, true)` at the cause-recursion call. The old one-level fixture (`outer` → `TypeError('inner')` with no further cause) is observationally identical for `true` vs `false`, so the suite stayed green.

RED against that mutant (assertion lines):

```
FAIL  js/admin/utils/__tests__/logger.test.ts > flattenError cause recursion [O-07] > follows cause only one level in a two-level chain [O-07][TEST-15]
AssertionError: expected { name: 'Error', …(2) } to deeply equal { name: 'Error', …(2) }
@@ -1,7 +1,11 @@
  {
    "cause": {
+     "cause": {
+       "message": "leaf-secret",
+       "name": "Error",
+     },
      "message": "mid",
      "name": "Error",
    },
    "message": "outer",
    "name": "Error",
 ❯ js/admin/utils/__tests__/logger.test.ts:436:37
    436|     expect(records[0].fields.error).toEqual({
```

Contract: `error → cause → cause` flattens to `{ name, message, cause: { name, message } }` and stops. `leaf-secret` must not appear.

GREEN: `Tests  22 passed (22)` in `logger.test.ts`; `Tests  2889 passed (2889)` for `js/admin`.
