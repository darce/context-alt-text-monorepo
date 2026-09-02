# FEBT-1 W1 errors lane — fix evidence

Lane `febt-1-fix-errors` on `fix/febt-1-w1-errors`. TDD: tests written and observed RED, then implemented.

Shared ceiling: `RETRY_AFTER_MAX_MS = 300_000` (5 minutes). QueryClient retry delay still min-caps at existing `MAX_RETRY_DELAY_MS = 30_000` so those assertions keep their meaning.

## E-01 — hostile Retry-After clamp

New tests:

- `clampRetryAfterMs [E-01] > clamps Retry-After: 3600 to the operational ceiling`
- `clampRetryAfterMs [E-01] > clamps overflow-scale Retry-After: 2_678_400 below the 32-bit setTimeout bound`
- `clampRetryAfterMs [E-01] > rejects negative, NaN, Infinity, and undefined and falls back`
- `recognitionCooldown > openCooldownFromError > clamps Retry-After: 3600 to the shared ceiling at the cooldown call site [E-01]`
- `recognitionCooldown > openCooldownFromError > clamps overflow-scale Retry-After below the 32-bit setTimeout bound [E-01]`
- `recognitionCooldown > openCooldownFromError > falls back to DEFAULT_COOLDOWN_SECONDS for negative/NaN/Infinity Retry-After [E-01]`
- `clusterAutoRetry pure helpers > clamps Retry-After: 3600 to the shared ceiling [E-01]`
- `clusterAutoRetry pure helpers > clamps overflow-scale Retry-After below the 32-bit setTimeout bound [E-01]`
- `clusterAutoRetry pure helpers > falls back to DEFAULT_COOLDOWN_SECONDS for negative/NaN/Infinity Retry-After [E-01]`
- `getRetryDelay > clamps Retry-After: 3600 through the shared ceiling at the retry-delay call site [E-01]`
- `getRetryDelay > falls back off the Retry-After branch for negative/NaN/Infinity [E-01]`

RED (assertion lines):

```
AssertionError: expected 3600000 to be 300000 // Object.is equality
- 300000
+ 3600000
 ❯ js/admin/utils/__tests__/retryAfter.test.ts:9:50
     expect(clampRetryAfterMs(3600, FALLBACK_MS)).toBe(RETRY_AFTER_MAX_MS);

AssertionError: expected 2678400000 to be 300000 // Object.is equality
- 300000
+ 2678400000
 ❯ js/admin/utils/__tests__/retryAfter.test.ts:14:21
     expect(clamped).toBe(RETRY_AFTER_MAX_MS);

AssertionError: expected 3600 to be 300 // Object.is equality
- 300
+ 3600
 ❯ js/admin/hooks/__tests__/clusterAutoRetry.test.ts:60:64
     expect(resolveClusterRetryDelaySeconds(rateLimited(3600))).toBe(RETRY_AFTER_MAX_MS / 1000);

AssertionError: expected 3600000 to be 300000 // Object.is equality
- 300000
+ 3600000
 ❯ js/admin/utils/__tests__/recognitionCooldown.test.ts:104:37
       expect(cooldownRemainingMs()).toBe(RETRY_AFTER_MAX_MS);
```

GREEN: `Tests  2898 passed (2898)` (`Test Files  232 passed (232)`).

## E-04 — fetchApi default timeout

New tests:

- `fetchApi default timeout [E-04] > rejects a hung fetch within the default deadline as a classified abort`
- `fetchApi default timeout [E-04] > lets an explicit timeoutMs override the default`
- `fetchApi default timeout [E-04] > still aborts when a caller-supplied signal aborts early`
- `fetchApi default timeout [E-04] > does not abort a fast successful response`

RED (assertion lines):

```
AssertionError: expected undefined to be an instance of DOMException
 ❯ js/admin/utils/__tests__/http.test.ts:522:22
     expect(rejected).toBeInstanceOf(DOMException);

AssertionError: expected 'unknown' to be 'abort' // Object.is equality
Expected: "abort"
Received: "unknown"
 ❯ js/admin/utils/__tests__/http.test.ts:545:42
     expect(classifyError(rejected)._tag).toBe('abort');
```

Caller-signal abort and fast-success were already true (regression pins) and stayed green.

Timeout abort reuses the existing `abort` AppError tag (`TimeoutError` DOMException). Default deadline is `DEFAULT_FETCH_TIMEOUT_MS = 300_000`, composed with a caller `signal` via `AbortSignal.any` when present so existing 180s describe signals are not clipped.

GREEN: `Tests  2898 passed (2898)` (`Test Files  232 passed (232)`).

## E-06 — full jitter on the exponential branch

New tests:

- `getRetryDelay > applies full jitter: rng 0 → 0, rng ~1 → full computed exponential [E-06]`
- `getRetryDelay > keeps the Retry-After branch byte-identical regardless of rng [E-06]`

RED (assertion lines):

```
AssertionError: expected 1000 to be +0 // Object.is equality
- 0
+ 1000
 ❯ js/admin/utils/__tests__/retryPolicy.test.ts:163:50
     expect(getRetryDelay(0, transport, () => 0)).toBe(0);
```

Retry-After invariance was already true (no rng on that branch) and stayed green. Existing exponential assertions keep `toBe(1_000)` / `toBe(2_000)` / `toBe(4_000)` / `toBe(30_000)`; the describe spies `Math.random` at `1` so those values remain the unjittered computed delay.

GREEN: `Tests  2898 passed (2898)` (`Test Files  232 passed (232)`).

## W1-L1-09 — isCooldownSignal contract

New tests:

- `classifier clauses after F3/F5 [TEST-15] > isCooldownSignal means "should open a cooldown", not instanceof HTTPError [W1-L1-09]`
- `recognitionCooldown > openCooldownFromError > honors retryAfterMs on a pre-classified AppError [W1-L1-09]`

The type predicate `error is HTTPError` was the lie: `isCooldown` is true for classified AppError values that are not `HTTPError` instances, and false for HTTPError 500. The name means "should open a cooldown". Boolean behaviour for HTTPError 429/503-with-Retry-After is unchanged (M17 kept). Opposite-way input: a pre-classified 429 AppError was treated as HTTPError, so `retryAfterSeconds` was undefined and the cooldown armed the 30s default instead of 5s.

RED (assertion lines):

```
AssertionError: expected 30000 to be 5000 // Object.is equality
- 5000
+ 30000
 ❯ js/admin/utils/__tests__/recognitionCooldown.test.ts:128:37
       expect(cooldownRemainingMs()).toBe(5_000);
```

GREEN: `Tests  2898 passed (2898)` (`Test Files  232 passed (232)`).
