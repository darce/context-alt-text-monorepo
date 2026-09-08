# FEBT-1 W1 review — logging lens
VERDICT: fail
COMBINED_TREE: 6da49ca7

The logger module is a competent sink/threshold/flatten helper. It does not yet do the job the slice claimed: a job or request id on every line, and one wide event per unit of work. Production has two logger emits and nine leftover `console.*` sites. Neither logger emit carries a correlation id. `newRequestId()` and `child()` are dead outside tests.

## Correlation-id coverage

Production `createLogger` / emit sites only. Tests that pass `requestId`/`jobId` prove the API can carry them; production never does.

| call site (file:line) | scope | carries job/request id? | fields |
| --- | --- | --- | --- |
| `main.tsx:9` `createLogger('bootstrap')` | bootstrap | no | none bound |
| `main.tsx:67` `bootstrapLog.warn(...)` | bootstrap | no | `missingGlobals` |
| `useJobPersistence.ts:38` `createLogger('jobPersistence')` | jobPersistence | no | none bound |
| `useJobPersistence.ts:88` `log.error(...)` | jobPersistence | no | `error` (JSON `SyntaxError`) |

`newRequestId` (`logger.ts:94`) is imported only by `logger.test.ts`. `Logger.child` is called only in that test file. `LogFields.jobId` / `LogFields.requestId` exist as optional keys and are never populated on a production line.

Unconverted `console.*` sites (also no job/request id; listed so the 11-site claim can be scored):

| call site (file:line) | scope (implicit) | carries job/request id? | fields |
| --- | --- | --- | --- |
| `useJobStateMachineMutations.ts:82` | scan submit | no (`jobIds` exist only on the success path) | raw `error` |
| `useJobStateMachineMutations.ts:161` | cancel | no (`activeJobIds` is in closure, unused) | raw `error` |
| `useJobProgressStream.ts:174` | SSE progress parse | no (`jobId` is in closure, unused) | none |
| `useJobProgressStream.ts:196` | SSE done parse | no (`jobId` in closure, unused) | none |
| `useJobProgressStream.ts:227` | SSE server error | no (`jobId` in closure, unused) | `errorData.message` |
| `useJobProgressStream.ts:233` | SSE reconnect | no | `event` |
| `useJobProgressStream.ts:238` | SSE closed | no | none |
| `api/config.ts:77` | config normalize | no | field name only |
| `useClusterSuggestionsLoader.ts:211` | cluster label search | no | raw `err` |

Score: 0 of 2 logger emits carry a correlation id. 0 of 9 leftover console sites do. The logger can take an id; it is called without one everywhere that matters.

## Mutation results (TEST-15)

Baseline: `npx vitest run js/admin/utils/__tests__/logger.test.ts` — 11 passed. Each mutant reverted with `git checkout --` before the next. Working tree clean of `logger.ts` after the series.

| # | file:line | mutation | KILLED / SURVIVED |
| --- | --- | --- | --- |
| 1 | `logger.ts:106` | disable threshold: `if (LOG_LEVEL_ORDER[level] < LOG_LEVEL_ORDER[minLevel])` → `if (false)` so every record reaches the sink | KILLED (`drops records below minLevel`; `setLogLevel(null)` hidden-debug case) |
| 2 | `logger.ts:110` | `ts: Date.now()` → `ts: 0` | KILLED (OBS-02 capture test expects fake-timer `1700000000000`) |
| 3 | `logger.ts:112` | `scope` → `scope: ''` | KILLED (capture/child tests; console prefix becomes `[alt-context/]`) |
| 4 | `logger.ts:56` | stop flattening cause: `flattenError(value.cause, false)` → `value.cause` | KILLED (one-level flatten test expects `{name,message}` not a `TypeError` instance) |
| 5 | `logger.ts:56` | flatten cause two levels: `flattenError(value.cause, false)` → `flattenError(value.cause, true)` | SURVIVED (11/11 still pass) |
| 6 | `logger.ts:79` | drop console prefix: `` `[alt-context/${record.scope}] ${record.message}` `` → `record.message` | KILLED (consoleSink / restore-default-sink prefix assertions) |

SURVIVOR exact edit: in `flattenError`, change the recursive call from `flattenError(value.cause, false)` to `flattenError(value.cause, true)`. The one-level test only builds a single nested `Error`; a two-level chain is untested, so the advertised depth is not pinned.

## Findings

### O-01 | severity: high | `logger.ts:94` / `main.tsx:67` / `useJobPersistence.ts:88` | canon: OBS-03
evidence:
OBS-03: "Correlation ID on every line: without a request/trace id threaded through every log line and span, multi-service debugging degrades to guesswork; propagate it at every boundary." The production logger is constructed with empty parent fields (`main.tsx:9`, `useJobPersistence.ts:38`) and both emits omit `jobId`/`requestId`. `newRequestId()` is unused outside tests. On the actual job path, `useJobProgressStream` already holds `jobId` and still logs through `console.*` without it (see table). A grep for a job UUID cannot reconstruct submit → SSE → cancel.
consequence:
The slice replaced two `console.*` calls with a structured logger and left correlation as an unused type field. Multi-tab / multi-job debugging is still guesswork. Shipping this as "OBS-03 done" would be false.
recommendation:
Require a correlation id at the logger boundary, not at each call site. Add `createJobLogger(scope, { jobId, requestId })` (or make `createLogger` bind `requestId: newRequestId()` by default and `child({ jobId })` at job start). In non-test builds, drop or `console.assert` records that lack both ids. Convert the nine leftover console sites through that factory so the id is inherited, not re-supplied.

### O-02 | severity: high | `hooks/jobMachine.ts:237` / `hooks/useJobProgressStream.ts:189` / `hooks/useJobStateMachineMutations.ts:62` | canon: OBS-02
evidence:
OBS-02: "One wide event per unit of work: many thin log lines force multi-line joins to reconstruct a request; emit one wide, structured event per unit of work carrying all its dimensions." Named units of work in this tree: one scan-submit request, one scan/clustering job (SSE lifetime), one cancel request, one bootstrap, one localStorage hydrate. None of them emit one structured record with their dimensions. Scan success (`useJobStateMachineMutations.ts:62`) is silent. SSE `done` (`useJobProgressStream.ts:189`) updates React state and broadcasts to a `BroadcastChannel` but logs nothing on success; parse/connection failures are thin `console.error`/`console.warn` lines without `jobId`, `done`, `total`, or terminal status. `jobReducer` terminal events (`COMPLETE`, `COMPLETE_WITH_ERRORS`, `FAIL`, `CANCEL`) are side-effect free and have no log hook. The two logger records that do exist are a bootstrap warn and a JSON-parse error — not job outcomes.
consequence:
Operators cannot query "this job's story" as one record. They would stitch React state, BroadcastChannel payloads, and leftover console lines by hand. The logger's `LogRecord` shape (`ts`, `scope`, `level`, `message`, `fields`) is wide enough; no unit of work uses it that way.
recommendation:
Keep `jobReducer` pure. On terminal `JobEvent`s, a dispatch wrapper (effects layer, not the reducer) should emit one record: `{ jobId, event: event.type, status, done, total, failedCount, error? }`. Scan submit and cancel should each emit one record at settle (success or classified failure), not a scatter of console lines. Do not add per-progress-tick logs to satisfy this; the wide event is the completion/failure of the job.

### O-03 | severity: medium | `hooks/useJobStateMachineMutations.ts:82` / `utils/http.ts:175` / `logger.ts:50-57` | canon: OBS-03 / REF-19
evidence:
`HTTPError` is constructed with `message: \`Request to ${endpoint} failed (${status}): ${errorText}\`` — the full response body, not the 240-char `bodyPreview`. `console.error('Scan submission failed', error)` and `console.error('Cancel failed', error)` therefore dump that body (and enumerable `bodyPreview`) to the console. `flattenError` copies `Error.message` verbatim and, for a non-`Error` cause, assigns `value.cause` as-is (`logger.ts:56`). `AppError` is a plain object, so `flattenFieldValue` would pass `{ _tag, message, cause }` through untouched, re-attaching the original `HTTPError` / `NonceRefreshFailedError` (including `bodyPreview`). The one production logger error path (`useJobPersistence.ts:88`) is a `JSON.parse` `SyntaxError` and does not currently leak a nonce, email, or image path.
consequence:
A logger makes leaks systemic once the leftover console sites are converted without a redaction policy. Failed auth that still surfaces as `HTTPError` (401 other than `rest_not_logged_in`; 403 other than nonce) would log the raw body. A `cause` that is a `Response` or request config with `X-WP-Nonce` would be attached raw. `NonceRefreshFailedError.bodyPreview` is dropped by `flattenError` today only because that class is not logged through the logger yet.
recommendation:
Redact inside the logger (REF-21), not at each caller. For `HTTPError` / `ResponseParseError` / `NonceRefreshFailedError`, log `{ name, status?, endpoint?, causeStatus? }` and drop `message`/`bodyPreview`. For unknown `Error`, keep `{ name, message }` but never assign a non-plain-object cause (`Response`, `Headers`, request init). Recognize `isAppError` and emit `{ tag, message, status?, endpoint? }` with cause flattened through the same redaction. Do not log SSE `event` objects (`useJobProgressStream.ts:233`).

### O-04 | severity: low | `logger.ts:105-114` | canon: PERF-06
evidence:
PERF-06: "Measure, don't guess." There is no production `debug()` call and no logger call on a per-image / per-poll / per-render path. SSE `progress` ticks do not log on success. The cost question is still real at the API shape: `debug(message, fields)` always evaluates arguments, then `emit` drops the record if `LOG_LEVEL_ORDER[level] < minLevel`. Template literals and object literals at the call site are not gated. Default prod minLevel is `info`, so a future `log.debug(\`tick ${done}/${total}\`, { jobId, done, total, payload })` on the SSE progress handler would allocate every tick in production and then discard.
consequence:
No measured hot-path cost today. Converting progress/poll sites to `debug` without a lazy/gated API would pay construction cost while "suppressed."
recommendation:
Do not log per-tick progress. If debug on a hot path is needed later, add `isLevel(level)` or accept `fields?: LogFields | (() => LogFields)` and skip thunk evaluation when dropped. Do not "optimize" the current two call sites; they run once per bootstrap / failed hydrate.

### O-05 | severity: medium | `utils/logger.ts:61-66` / `utils/appError.ts:37` / `hooks/jobMachine.ts:42` | canon: REF-21 / REF-19
evidence:
REF-21: "Pull complexity downward: the module implementer should suffer so its many users don't." REF-19: "No information leakage: every leaked decision couples modules so a change fans out invisibly." Wave-1 landed three modules that do not compose. `flattenFieldValue` special-cases `instanceof Error` only. `AppError` is a tagged union (`_tag`) with `cause` holding the original error; it is not an `Error`. `JobEvent` is a closed union of named events; the reducer never logs. Current (and leftover console) callers pass raw `unknown` errors. Nothing reads `_tag` or `event.type` into a first-class log field. If callers later write `{ errorTag: err._tag, jobEvent: event.type }`, those key names leak into every site and a rename of the union fans out.
consequence:
The next conversion wave will hand-destructure `AppError` and job events into ad-hoc fields, or dump the whole object (O-03). The logger will not stay the single place that knows how to describe a failure or a terminal job.
recommendation:
Concrete, not optional:
1. Logger owns AppError: `flattenFieldValue` calls `isAppError` and emits `{ tag: value._tag, message: value.message, status?, endpoint? }` plus a redacted one-level cause. Callers pass `{ error }` and stop packing `_tag`.
2. Logger owns terminal job events via `logJobEvent(log, event, state)` that writes `event` (the `JobEvent['type']`) and `jobId` as first-class fields. Call it from the dispatch/effects wrapper on `COMPLETE` / `COMPLETE_WITH_ERRORS` / `FAIL` / `CANCEL` only. Do not log from inside `jobReducer`.
3. Do not add `errorTag` / `kind` / `jobEvent` keys at call sites. If the union grows a tag, only `flattenFieldValue` / `logJobEvent` change.

### O-06 | severity: medium | `hooks/useJobProgressStream.ts:174` | canon: OBS-01
evidence:
Nine `console.*` sites remain under `js/admin` (full list in "Surviving console.* sites"). None are bootstrap-before-logger: `logger.ts` has no WP/DOM import, and `main.tsx` already uses it. The job SSE/submit/cancel path — the path OBS-01 would instrument at write time — still uses `console`. `useJobPersistence` tests still spy on `console.error` (`useJobPersistence.test.ts:70`), so the hydrate logger is only accidentally covering that spy via `consoleSink`.
consequence:
The structured logger is not the production log path for jobs. Dual sinks (logger + console) will drift; correlation and redaction policies cannot be applied in one place.
recommendation:
Convert the nine sites to scoped loggers. Keep raw `console.*` out of `js/admin` except a documented sink implementation (`consoleSink` itself). Update the persistence test to assert on a capture sink or `consoleSink`'s prefix, not an implicit console spy.

### O-07 | severity: low | `logger.ts:56` / `utils/__tests__/logger.test.ts:99` | canon: TEST-15
evidence:
Mutant 5 (recurse with `includeCause: true`) survived. The test named "flattens Error cause one level without stack" never builds a two-level chain, so it cannot fail when the production path flattens two levels.
consequence:
Cause-depth is specified in code and comments, not locked by a test. A later change can walk an unbounded cause chain (more leakage surface) without reddening CI.
recommendation:
Add a fixture `new Error('a', { cause: new Error('b', { cause: new Error('c') }) })` and assert the flattened cause has `name/message` only — no nested `cause`. That mutant must die.

## Surviving console.* sites

| file:line | call | legitimate exception? |
| --- | --- | --- |
| `logger.ts:82,85` | `console[level](...)` inside `consoleSink` | yes — the sink |
| `useJobProgressStream.ts:174` | `console.error('Failed to parse SSE progress data')` | no — unconverted; `jobId` in closure |
| `useJobProgressStream.ts:196` | `console.error('Failed to parse SSE done data')` | no — unconverted |
| `useJobProgressStream.ts:227` | `console.error('SSE server error:', errorData.message)` | no — unconverted |
| `useJobProgressStream.ts:233` | `console.warn('SSE connection error, will auto-reconnect...', event)` | no — unconverted; logs the Event object |
| `useJobProgressStream.ts:238` | `console.warn('SSE connection closed unexpectedly')` | no — unconverted |
| `useJobStateMachineMutations.ts:82` | `console.error('Scan submission failed', error)` | no — unconverted; comment is about UI copy, not logs |
| `useJobStateMachineMutations.ts:161` | `console.error('Cancel failed', error)` | no — unconverted |
| `api/config.ts:77` | `console.warn(\`... field "${field}" ...\`)` | no — `normalizeConfig` can import the logger; this is not pre-logger bootstrap |
| `useClusterSuggestionsLoader.ts:211` | `console.warn('Failed to find cluster by label:', err)` | no — unconverted |

No remaining `console.log` / `console.debug` under `js/admin`. Test spies on `console.*` are not production sites.

## Composition with appError / jobMachine

They do not compose. The logger flattens `instanceof Error`. `AppError` is not an `Error`. `jobReducer` is a pure function of `JobEvent` and does not log. Callers still `console.error` the raw `unknown`.

Should `_tag` and the machine event name be first-class logger fields? Yes. Not as ad-hoc keys each caller invents.

Do this:
- `flattenFieldValue`: if `isAppError(value)`, record `{ tag, message, status?, endpoint? }` and a redacted one-level cause. Callers pass `{ error: classifyError(err) }` or `{ error: err }` and let the logger classify.
- `logJobEvent(log, event, state)`: first-class field `event` = `event.type`, plus `jobId` from `state.jobId`. Invoke only on terminal events from the effects/dispatch wrapper.
- Keep the reducer pure; do not import the logger into `jobMachine.ts`.
- Do not ask every mutation hook to write `{ errorTag: classified._tag, machineEvent: 'FAIL' }`. That is REF-19 leakage.

## Not-doing / out of scope

- No source or test file was left modified. TEST-15 mutants were reverted; `logger.ts` matches HEAD.
- Did not convert the leftover `console.*` sites (review lane; emit findings only).
- Did not profile a live SSE session (PERF-06: no current hot-path log to measure).
- Did not review sibling-lane PHP/Python services or non-`js/admin` consoles.
- Handoff MCP Python package was not importable in this sandbox (`.venv` present, `workbay_handoff_mcp` missing); findings live in this file only.
- Sandbox `HEAD` is `0fe84202` on `master` (history-stripped). Assignment tree id `6da49ca7` is recorded above as `COMBINED_TREE`.
- `make context` is not a target in this checkout (`exit 2`).
