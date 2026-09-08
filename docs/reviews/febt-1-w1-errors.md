# FEBT-1 W1 review — errors lens
VERDICT: pass_with_findings
COMBINED_TREE: 6da49ca7

Expand-phase read. Union + single classifier at the fetch-class boundary are closed for the outcomes they claim. Call-site `instanceof HTTPError` / `AuthExpiredError` still branch. Retry-After is clamped only in `getRetryDelay`. Utils tests 127/127 green before mutations; every mutation reverted; tree clean except this report.

Declared `_tag` set (`appError.ts:5-13`): `http | parse | auth_expired | nonce_refresh | abort | transport | unknown`.

Production paths that emit a tag:
- passthrough already-classified `AppError` (`appError.ts:140-141`)
- `AuthExpiredError` → `auth_expired` (`appError.ts:143-150`; thrown at `http.ts:231,252,267,270`)
- `HTTPError` → `http` (`appError.ts:152-154` / `classifyHttpError` `118-136`; thrown at `http.ts:170-176,277`)
- `ResponseParseError` → `parse` (`appError.ts:155-161`; thrown at `http.ts:196-201`)
- `NonceRefreshFailedError` → `nonce_refresh` (`appError.ts:163-168`; thrown from `api/config.ts` only — `fetchApi` swallows it into `AuthExpiredError`)
- abort-like name → `abort` (`appError.ts:170-176`)
- `TypeError` → `transport` (`appError.ts:177-183`)
- other `Error` / non-Error / classifier catch → `unknown` (`appError.ts:184-201`)

## Tag coverage matrix
| upstream outcome | expected tag | actual tag | file:line | OK / MISMATCH |
|---|---|---|---|---|
| 401 `rest_not_logged_in` | auth_expired | auth_expired | http.ts:228-231 → appError.ts:143 | OK |
| 401 other JSON / empty / HTML | http (code-gated) | http | http.ts:233 → appError.ts:152 | OK |
| 403 `rest_cookie_invalid_nonce` + refresh fail / second nonce-403 | auth_expired | auth_expired | http.ts:246-267 → appError.ts:143 | OK |
| 403 other / WAF HTML | http | http | http.ts:238-240 → appError.ts:152 | OK |
| 404 | http | http | http.ts:277 | OK |
| 409 | http | http | http.ts:277 | OK |
| 429 with Retry-After | http + retryAfterMs | http + retryAfterMs | http.ts:169-176 → appError.ts:128-135 | OK |
| 429 without Retry-After | http; cooldown true | http; `isCooldown` true | appError.ts:210-216 | OK |
| 500 / 502 / 504 | http; no retry | http; `shouldRetryRequest` false | retryPolicy.ts:27-32 | OK |
| 503 with Retry-After | http; cooldown | http; cooldown | appError.ts:214 | OK |
| 503 without Retry-After | http; no cooldown | http; `isCooldown` false | appError.ts:214 | OK |
| fetch TypeError (dropped connection) | transport | transport | appError.ts:177-183 | OK |
| `TypeError('x is not a function')` | unknown (not transport) | transport | appError.ts:177-183 | MISMATCH (E-05) |
| AbortController abort / `TimeoutError` | abort | abort | appError.ts:170-176 | OK |
| JSON parse failure on 200 | parse | parse | http.ts:190-201 → appError.ts:155 | OK |
| HTML error page on 200 | parse | parse | http.ts:190-201 | OK |
| empty body on 200 (`fetchApi`) | success (`undefined`) | `undefined` | http.ts:186-188 | OK |
| empty body on 200 (`fetchRequiredApi`) | explicit empty/parse | `unknown` (generic `Error`) | http.ts:285-287 → appError.ts:184 | OK (no empty tag; expand-phase leftover) |
| nonce refresh failure inside `fetchApi` | nonce_refresh exists | auth_expired | http.ts:246-252 | OK (intentional UX collapse) |

## Mutation results (TEST-15)
Baseline: `npx vitest run js/admin/utils` → 9 files / 127 tests pass. Each mutation reverted with `git checkout --`.

| # | file:line | mutation | KILLED / SURVIVED |
|---|---|---|---|
| 1 | appError.ts:147 | swap 401/403 on `AuthExpiredError` classify (`status: error.status === 401 ? 403 : 401`) | KILLED (appError M4 + 401/403 round-trip) |
| 2 | appError.ts:179 | classifier returns `_tag: 'unknown'` for `TypeError` | KILLED (M7/M8/M15 + retry TypeError pins) |
| 3 | http.ts:169 | `throwHttpError` sets `retryAfterSeconds = undefined` (skip `parseRetryAfter`) | KILLED (http 429/503 Retry-After pins) |
| 4 | appError.ts:210 | `isCooldown` always `return true` | KILLED (retry 4xx/5xx + M17 + cooldown ignore pins) |
| 5 | appError.ts:157 | `ResponseParseError` classified as `unknown` (drop parse tag) | KILLED (appError parse equality). Note: `shouldRetryRequest` parse pin still green — `unknown` is also non-retry. |
| 6 | sessionExpiredCopy.ts:6 | `'sign in'` → `'log in'` | SURVIVED (127/127). Utils tests import the same constant they assert. `UserFacingErrorNotice` hardcodes a second copy, so the constant is not the UI source. |
| 7 | http.ts:102-105 | delete HTTP-date `Date.parse` branch in `parseRetryAfter` | SURVIVED (127/127). No utils test feeds an HTTP-date `Retry-After`. |
| 8 | retryPolicy.ts:49-52 | drop `MAX_RETRY_DELAY_MS` clamp on both delay branches | KILLED (3600s / overflow-scale / exp-cap pins) |

SURVIVOR exact edits:

```ts
// #6 sessionExpiredCopy.ts:6
sessionExpired: 'Your session expired — reload the page and log in again.',

// #7 http.ts: parseRetryAfter — after the numeric-reject arm, return undefined
// (delete the Date.parse / Math.ceil((t - Date.now()) / 1000) block)
```

## Findings
### E-01 | severity: medium | recognitionCooldown.ts:51-54, clusterAutoRetry.ts:18-19,112-116 | canon: RES-06 / REF-21
evidence:
`getRetryDelay` (`retryPolicy.ts:47-53`) honours Retry-After and clamps at `MAX_RETRY_DELAY_MS` (30s), including the overflow-scale pin at 2_678_400s. `openCooldownFromError` does `openCooldown(error.retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS)` with no clamp — a 3600s header parks every gated poller for an hour. `resolveClusterRetryDelaySeconds` returns the raw seconds; `noteError` then `setTimeout(..., seconds * 1000)`. `2_678_400 * 1000 > 2^31-1`, so the same header the retry-delay tests treat as a hot-loop fires the cluster timer immediately. `runAfterCooldown` (`recognitionCooldown.ts:120`) has the same `setTimeout(remainingMs)` overflow. Clamp knowledge leaked into one consumer instead of living on the parse/delay owner.
consequence:
Hostile or buggy `Retry-After` either freezes recognition polling for hours or collapses cluster auto-retry into an immediate loop. RQ retries stay safe; the other two Retry-After readers do not.
recommendation:
Parse once into a clamped delay helper (seconds and ms). `openCooldownFromError`, `getRetryDelay`, and `resolveClusterRetryDelaySeconds` must share it. Cap at `MAX_RETRY_DELAY_MS`. Add the 3600 / 2_678_400 cases to cooldown + cluster tests.

### E-02 | severity: medium | clusterAutoRetry.ts:15-16, useLiveReviewTarget.ts:50,91,100 | canon: expand-phase instanceof
evidence:
Classifier exists and is used by `retryPolicy` / `userFacingError`. Two call sites still branch on the classes: `isRetryableClusterError = error instanceof HTTPError && error.status === 429`; `isClusterNotFound = err instanceof HTTPError && err.status === 404`; existence-query retry/status uses `error instanceof AuthExpiredError` twice. That is exactly the scatter the union was introduced to end. Pre-classified `AppError` 429/404/`auth_expired` will miss both.
consequence:
Contract-phase (stop throwing the classes, pass the union) silently changes cluster auto-retry and live-review retirement/auth handling. Expand phase still works because `fetchApi` throws the classes.
recommendation:
Replace with `isCooldown` / `isHttpStatus(err, 404)` / `_tag === 'auth_expired'`. Keep class `instanceof` only inside `classifyError`.

### E-03 | severity: medium | UserFacingErrorNotice.tsx:29-45 vs sessionExpiredCopy.ts:5-7 | canon: REF-19
evidence:
`sessionExpiredCopy.ts` extracted `sessionExpired` and `reloadPage`. `toUserMessage` / `formatUserFacingError` read the constant. `UserFacingErrorNotice` re-hardcodes both strings through `__()` with a comment that the literal must stay extractable. Mutation #6 (one-word change to the constant) left all 127 utils tests green and would not change the notice UI. Two modules own one copy decision.
consequence:
Copy edits fan out invisibly; i18n catalog and SPA constant can diverge; utils tests cannot catch a wording bug.
recommendation:
One owner. Either `__()` wraps `SPA_SESSION_EXPIRED_COPY.sessionExpired` (and pin the literal in an i18n fixture), or the notice imports the constant and a test asserts notice text ≠ a second literal.

### E-04 | severity: medium | http.ts:209-215 | canon: RES-02
evidence:
`fetchApi` forwards `options.signal` and otherwise calls `fetch` with no timeout. No default `AbortSignal.timeout`. A hung origin blocks the request until the browser tab dies. Callers that do pass a timeout (recognition poller, cluster save `withTimeout`) are ad hoc; the shared boundary does not enforce a bound.
consequence:
One stuck REST call can pin in-flight UI with no abort, no retry budget tick, no cooldown. Defaults block forever.
recommendation:
Default a bounded timeout inside `fetchApi` (caller signal wins; compose via `AbortSignal.any` where available). Keep abort classified as `abort` and non-retry.

### E-05 | severity: low | appError.ts:177-183, retryPolicy.ts:40 | canon: tag mismatch / F5 parity
evidence:
Any `TypeError` becomes `transport` and is retried, including `new TypeError('x is not a function')`. Tests pin this as F5 parity with the old `instanceof TypeError` retry. Fetch network failures are TypeErrors; so are programming bugs.
consequence:
A caller TypeError is retried up to `RETRY_MAX_ATTEMPTS` as if the network dropped. Expand-phase behaviour match, not a closed taxonomy.
recommendation:
Contract phase: match fetch-shaped TypeErrors (or only classify TypeErrors thrown from `fetchApi`) and leave the rest `unknown` / no retry.

### E-06 | severity: low | retryPolicy.ts:52 | canon: RES-06
evidence:
Backoff is `1000 * 2 ** attemptIndex` with a 30s cap and no jitter. After a shared 503, every admin tab that shares the delay function retries at 1s/2s/4s in lockstep. Attempt ceiling exists: `RETRY_MAX_ATTEMPTS = 3` (`retryPolicy.ts:22-24`).
consequence:
Retry bursts amplify a recovering origin. Window is short (three delays), so impact is bounded.
recommendation:
Add full-jitter on the exponential branch. Leave Retry-After branch deterministic (server-specified).

### E-07 | severity: low | clusterAutoRetry.ts:15-16 vs appError.ts:210-216 | canon: REF-19
evidence:
Query retry/cooldown: 429, or 503 with Retry-After, via `isCooldown`. Cluster auto-retry: only `instanceof HTTPError && status === 429`. A 503+Retry-After that quiets every poller is a terminal cluster failure. Two modules own retry classification.
consequence:
Same server signal, two behaviours. A later tweak to `isCooldown` will not move cluster retry.
recommendation:
Cluster helper should call `isCooldown` (or a mutation-specific wrapper that still uses the same tag test) instead of re-deriving 429 via `instanceof`.

## Surviving instanceof call sites
Classifier / class internals (expected expand-phase):
- `appError.ts:99,143,152,155,163,177,184` — `classifyError` itself
- `http.ts:156,195` — abort reason + JSON.parse failure message

Taxonomy branching that should already be tags (defects; see E-02):
- `hooks/clusterAutoRetry.ts:16` — `HTTPError` + 429
- `pages/workbench/identity-clusters/useLiveReviewTarget.ts:50` — `HTTPError` + 404
- `pages/workbench/identity-clusters/useLiveReviewTarget.ts:91,100` — `AuthExpiredError`

Abort re-derived beside `isAbortLike` / `_tag === 'abort'`:
- `pages/workbench/identity-clusters/ClusterLabelingPanel.tsx:105`
- `pages/workbench/identity-clusters/useClusterSuggestionsLoader.ts:205-208`

Generic `error instanceof Error` message extraction (not HTTPError-class scatter; still bypasses `toUserMessage`):
- `clusterMutationUtils.ts:32`, `useJobStateMachine.ts:28` (message includes `'(404)'`), cluster mutation hooks, retention page, `describeApi.ts`, `wpErrorMessage.ts`, `scanApiError.ts`, `api/config.ts:195`

DOM `instanceof` (HTMLElement/Node/MessageEvent) and test helpers: out of taxonomy scope.

## Known findings, confirmed or refuted
- FEBT-1-W1-L1-09 CONFIRMED. `isCooldownSignal` (`retryPolicy.ts:15`) is `error is HTTPError => isCooldown(error)`. `isCooldown` is true for a pre-classified `{_tag:'http', status:429, retryAfterMs}` that is not an `HTTPError`. M17 pins `isCooldownSignal(classified) === true`, so a type-honest fix (`instanceof HTTPError && isCooldown(error)`) would go red. Blast radius: `openCooldownFromError` then reads `error.retryAfterSeconds`; on an `AppError` that field is undefined and the header is replaced by `DEFAULT_COOLDOWN_SECONDS` (30s). Production RQ still throws `HTTPError`, so this is a contract-phase landmine — severity stays low, but it is the only lying `x is T` in the scoped files. `isRetryableClusterError` is honest (`instanceof` actually establishes `HTTPError`) and is a false-negative on tags, not a lie. `isAppError` / `isAppErrorTag` hold for the shapes they check.
- L1-01 through L1-08: not re-litigated. Sandbox history is stripped (`HEAD` d816824); `parseRetryAfter` still rejects `'-3'` before `Date.parse` (`http.ts:97-101`), which matches a surviving fix. No regression spotted against the current tree.

## Not-doing / out of scope
- Implementing the contract-phase call-site migration.
- Changing user-visible copy (expand phase: text unchanged).
- `payload as T` on 2xx JSON (`http.ts:191-192`) — contract validation, not error taxonomy.
- Synthesised `HTTPError.message` (`Request to ${endpoint} failed (${status}): ${body}`) — legacy format, status/body from the response, not invented envelope metadata (rg-015). Retry delay is parsed from `Retry-After` or left undefined; the classifier does not invent a status.
- Recording findings into MCP: `make context` has no target in this sandbox; handoff MCP tools were unavailable. This file is the lane deliverable.
