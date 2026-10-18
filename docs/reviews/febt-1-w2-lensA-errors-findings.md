# Lens A — errors
**Verdict:** IN PROGRESS

HEAD observed: `git rev-parse HEAD` after TURN 1 stub; source read at worktree files matching `82bb245a0` combined tree in this sandbox.

### F-1 Fetch boundary never emits a tagged AppError
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/utils/http.ts:257
- rule: REF-19, REF-29, RLSE-05
- evidence: `http.ts` has zero matches for `classifyError`, `appError`, or `_tag` (rg over that file). `fetchApi` still throws untagged class instances:

```
export const fetchApi = async <T>(endpoint: string, options: HTTPOptions = {}): Promise<T | undefined> => {
...
        throw new AuthExpiredError({ endpoint, status: 401 });
...
        throwHttpError(endpoint, response.status, errorText, retryAfterHeader);
```

http.test.ts:522-524 (this run's file contents): hung fetch rejects as `DOMException` named `TimeoutError`; `classifyError` is applied only by the test, not by `fetchApi`.
- failure scenario: a queryFn throws `HTTPError`/`TimeoutError` with no `_tag`. Any caller that forgets `classifyError` (or uses `instanceof Error` / `error.message`) sees an untagged wire error. The tagged union is not closed at the advertised fetch boundary; it is an opt-in adapter.
- fix: have `fetchApi`/`fetchRequiredApi` throw `classifyError(...)` (or a tagged AppError subclass) so every fetch path leaves the crumple zone with a tag.

### F-2 Nonce-refresh timeout/network is rewritten as session expiry
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/utils/http.ts:303
- rule: REF-01, REF-20, REF-33, RLSE-05, API-08
- evidence:

```
      try {
        await refreshRestNonce();
      } catch {
        // An abort that landed while the refresh was failing is an abort, not
        // session expiry — never surface recovery UI for an unmounted caller.
        throwIfAborted(signal);
        throw new AuthExpiredError({ endpoint, status: 403 });
      }
```

`refreshRestNonce` (config.ts:199-206) maps timeout-abort AND transport failure to `NonceRefreshFailedError`. `classifyError` has a dedicated `nonce_refresh` tag (appError.ts:163-168) that this catch never lets through. `toUserMessage` maps `auth_expired` to `SPA_SESSION_EXPIRED_COPY.sessionExpired`.
- failure scenario: admin-ajax rest-nonce hangs > `NONCE_REFRESH_TIMEOUT_MS` (10000). User is still logged in. SPA shows "Your session expired — reload the page and sign in again." QueryClient will not retry (`shouldRetryRequest` pins `auth_expired` false). A transient network blip during refresh is indistinguishable from a dead session.
- fix: rethrow abort as abort; map `NonceRefreshFailedError` to `_tag: 'nonce_refresh'` (or retry the refresh) instead of minting `AuthExpiredError`.

### F-3 Past HTTP-date Retry-After becomes 0s wait and flips 503 into an immediate retry
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/utils/http.ts:107
- rule: RES-06, API-08, RES-03
- evidence: `parseRetryAfter` lives in `http.ts`, not `retryAfter.ts`. HTTP-date branch:

```
  const t = Date.parse(trimmed);
  if (!Number.isNaN(t)) {
    return Math.max(0, Math.ceil((t - Date.now()) / 1000));
  }
```

Observed this session (`node -e Date.parse`):
`Thu, 01 Jan 1970 00:00:00 GMT` → parse=0 → secs=0
`Wed, 21 Oct 2015 07:28:00 GMT` → secs=0

`retryAfter.ts` only clamps; `RETRY_AFTER_MIN_MS = 0`. `isCooldown` (appError.ts:210-215) treats `503` + `retryAfterMs !== undefined` as cooldown, including `0`. `getRetryDelay` (retryPolicy.ts:57-59) honors that 0 with no jitter. `shouldRetryRequest` then retries 503-with-Retry-After. Tests pin `getRetryDelay(0, httpError(429, 0)) === 0` and `isCooldownSignal(httpError(503, 0)) === true`. `parseRetryAfter` describe in http.test.ts:198-212 has no HTTP-date case.
- failure scenario: 503 + `Retry-After: Thu, 01 Jan 1970 00:00:00 GMT` (stale proxy date / clock skew). Without the header, 503 is not retried. With the past date, classification becomes cooldown, delay is 0ms, QueryClient retries immediately up to `RETRY_MAX_ATTEMPTS`. Same header on 429 skips exponential backoff and hot-loops.
- fix: treat non-positive HTTP-date deltas as missing (undefined) so 503 stays non-retryable and 429 falls back to clamped backoff; add an HTTP-date test.

### F-4 Cluster UI still maps wire errors via error.message and leaks HTTP bodies
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/clusterMutationUtils.ts:28
- rule: REF-19, REF-16, REF-26
- evidence:

```
export const getClusterMutationErrorMessage = (error: unknown, label: string): string => {
  if (isAbortError(error)) {
    return __('Save is taking too long. Please try again.', 'alt-context');
  }
  if (isAuthExpiredError(error)) {
    return formatUserFacingError(error, __('An unexpected error occurred. Please try again.', 'alt-context'));
  }
  if (error instanceof Error) {
    ...
    if (error.message.includes('409') || normalized.includes('conflict')) {
      return __('Label already exists. Use the dropdown to merge.', 'alt-context');
    }
    if (error.message.includes('NetworkError') || error.message.includes('Failed to fetch')) {
      return __('Network error. Please check your connection and try again.', 'alt-context');
    }
    return error.message;
  }
```

Same scrape in ClusterLabelingPanel.tsx:69-87. `HTTPError.message` is `Request to ${endpoint} failed (${status}): ${errorText}` (http.ts:227). userFacingError.test.ts:27-35 names the test "never leaks raw error internals" then asserts `getClusterMutationErrorMessage(new Error('plain failure'), 'Sam') === 'plain failure'`. Retention uses `toUserMessage` (fallback only); cluster does not. `clusterAutoRetry.ts:134` also does `error instanceof Error ? error.message : listener.fallbackErrorMessage`.
- failure scenario: POST merge/label returns 400 with a JSON/WAF body. User sees `Request to https://.../clusters/... failed (400): {...}`. A pre-classified AppError (plain object, tests already pass this shape for abort) skips the `instanceof Error` branch, so a 409 becomes the generic "unexpected error" instead of the label-exists copy.
- fix: route cluster copy through `classifyError` + `toUserMessage` (status/tag switches), never `error.message`; drop the duplicate string classifier.

### F-5 TimeoutError and user abort share one tag, then get timeout copy
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/utils/appError.ts:87
- rule: REF-33, REF-01, REF-20, RES-13
- evidence:

```
const ABORT_LIKE_NAMES = new Set(['AbortError', 'TimeoutError']);
...
    if (isAbortLikeName(error)) {
      return {
        _tag: 'abort',
        message: abortMessage(error),
        cause: error,
      };
    }
```

http.ts:180-181 aborts hung fetch with `TimeoutError`. http.test.ts:522-524: default 300s hang classifies as `_tag: 'abort'`, same tag as user `AbortError`. `isAbortError` (clusterMutationUtils.ts:8) is `_tag === 'abort'`. `getClusterMutationErrorMessage` maps that tag to "Save is taking too long. Please try again." (lines 29-31; clusterMutationUtils.test.ts:39-44 pins pre-classified abort → timeout copy). `shouldRetryRequest` never retries abort, so a real timeout is not retried as transport.
- failure scenario: user cancels/unmounts a label save (AbortError). UI announces a timeout. Conversely, a recognition `AbortSignal.timeout(2000)` TimeoutError is indistinguishable from cancel: `findClusterByLabel` (useClusterSuggestionsLoader.ts:209-210) returns `null` on abort with no warn, same as "no matching cluster".
- fix: split `_tag: 'timeout'` from `_tag: 'abort'`; swallow only caller-cancel/unmount; surface timeout as a real bounded failure.

### F-6 Live-target probe bypasses shared retry policy and absorbs timeout into live
- severity: high
- file: apps/prototype-wp-alt-context/js/admin/pages/workbench/identity-clusters/useLiveReviewTarget.ts:88
- rule: REF-19, API-08, RLSE-05, RES-13
- evidence:

```
    retry: (failureCount, error) => {
      if (isClusterNotFound(error)) {
        return false;
      }
      if (isAuthExpired(error)) {
        return false;
      }
      return failureCount < 1;
    },
...
  const status: LiveReviewTargetStatus = authExpired
    ? 'auth_expired'
    : !retired
      ? 'live'
      : survivorId
        ? 'rebound'
        : 'retired';
...
  const error: unknown | null = authExpired ? existenceQuery.error : null;
```

This `retry` callback does not call `shouldRetryRequest` / `isAbortLike`. `fetchClusterMembers` uses `createRecognitionTimeoutSignal(2_000)` (identityQueriesApi / conflictApi timeout 2s → TimeoutError → `_tag: 'abort'`). Shared policy never retries abort; this site retries once. After failure, non-404/non-auth errors keep `retired === false` so status is `'live'` and `error` is null.
- failure scenario: open-cluster members probe times out at 2s (or 500/parse). Query retries once (against API-08 abort/4xx/parse pins), then the pane treats the target as live with no error surface. Auth expiry is the only failure that is not absorbed.
- fix: use `shouldRetryRequest` (or at least skip abort/parse/4xx); do not map probe timeout/5xx onto `'live'`.
