# FEBT-1 lane f2 (http-fix) report

Closed FEBT1-W2A-03 and FEBT1-W2A-02 on `feature/febt-1-f2`. Lane verification: `npm run typecheck` + 80 vitest tests passing.

## FEBT1-W2A-03 — past HTTP-date Retry-After is absent, not zero

- Commit: `1af5ae861f35db65981cc75137ce37ecac5f56c6`
- Test: `past HTTP-date Retry-After yields undefined, not 0 (FEBT1-W2A-03 — flips when F2 lands)`
- Also: `429 with a past HTTP-date Retry-After falls back to exponential backoff, not 0`
- RED: `✓ js/admin/utils/__tests__/http.test.ts > fetchApi HTTP-date Retry-After [FEBT1-W2C-08] > past HTTP-date Retry-After yields undefined, not 0 (FEBT1-W2A-03 — flips when F2 lands) 19ms` (`Tests  1 expected fail | 33 skipped (34)`)
- GREEN: same test as `it()` (`Tests  3 passed | 33 skipped (36)`; full `http.test.ts` 36 passed)

`parseRetryAfter` now returns `undefined` for a non-positive HTTP-date delta. Delta-seconds `0` is unchanged. A 503 with a past date is no longer a 0ms cooldown; a 429 with a past date uses exponential backoff.

## FEBT1-W2A-02 — nonce-refresh failure is not session expiry

- Commit: `99d0420c2b4ecfe3b5214a0dd62727fd4ec5ebe3`
- Test: `transport failure during nonce refresh is nonce_refresh, not auth_expired`
- Also: `abort during nonce refresh is abort, not auth_expired`
- RED:
  ```
  × js/admin/utils/__tests__/http.test.ts > fetchApi nonce-refresh failure is not session expiry [FEBT1-W2A-02] > transport failure during nonce refresh is nonce_refresh, not auth_expired 16ms
     → expected AuthExpiredError: Authentication expired … { …(2) } to be an instance of NonceRefreshFailedError
  × js/admin/utils/__tests__/http.test.ts > fetchApi nonce-refresh failure is not session expiry [FEBT1-W2A-02] > abort during nonce refresh is abort, not auth_expired 3ms
     → expected AuthExpiredError: Authentication expired … { …(2) } to not be an instance of AuthExpiredError
  Tests  2 failed | 36 skipped (38)
  ```
- GREEN: both tests pass; lane vitest `Tests  80 passed (80)`

The 403 refresh catch rethrows abort, maps transport/timeout `NonceRefreshFailedError` to `_tag: 'nonce_refresh'` (overlay transport copy + `shouldRetryRequest` true), and keeps `AuthExpiredError` only for WP logged-out sentinels (`0`/`-1`/401/403).

Canon: RES-06, RES-03, REF-01, REF-20, RLSE-05, TEST-15.
