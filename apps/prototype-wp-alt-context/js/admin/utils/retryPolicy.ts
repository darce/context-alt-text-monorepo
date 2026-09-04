import { classifyError, isCooldown } from './appError';
import { clampRetryAfterMs, hasRetryAfterWait, RETRY_AFTER_MIN_MS } from './retryAfter';

export const RETRY_MAX_ATTEMPTS = 3;
export const MAX_RETRY_DELAY_MS = 30_000;

/**
 * Attempt cap for an *ambiguous* outcome — one where the request may or may not
 * have reached the server (DDIA ch-8: a timed-out call has an UNKNOWN result,
 * not a failed one; the client must decide, and repeating it is only safe when
 * the operation is idempotent).
 *
 * One retry, not RETRY_MAX_ATTEMPTS. `shouldRetryRequest` is wired only to
 * React Query *queries* (appQueryClient.ts:28, useLiveReviewTarget.ts:105) —
 * idempotent GETs — never to a mutation, so a single repeat is safe; but the
 * outcome is unknown, so the budget must be smaller than the one used for a
 * definitively-failed transport attempt. Ported from the repo's existing bound
 * for the same shape: http.ts "one safe retry ([RES-01][API-02])" on nonce
 * refresh, and useLiveReviewTarget.ts:105 `failureCount < 1`.
 */
export const AMBIGUOUS_RETRY_MAX_ATTEMPTS = 1;

/** Tags whose outcome is unknown rather than known-failed. Bounded retry only. */
const AMBIGUOUS_OUTCOME_TAGS = {
  timeout: true,
  nonce_refresh: true,
} as const;

/**
 * Cancellation-shaped: a deliberate abort *or* an elapsed deadline. Its one
 * UI-facing consumer is `isFrozenPollFailure` in `hooks/useDescribeRunProgress`,
 * which names the "the poll did not come back, freeze rather than dead-end"
 * decision; nothing in the UI calls `isAbortLike` directly. The contract is
 * unchanged by the FEBT1-W2A-05 tag split — both shapes still answer true.
 *
 * No line numbers here on purpose (FEBT2-W2-Q-02): the previous
 * `useDescribeRunProgress.ts:54,132,151` reference had drifted to 72/150/169 and
 * pointed at the wrong symbol, so the comment asserted a call site the code did
 * not have (NAME-03, lexicons/engineering.md:650; CLM-03,
 * lexicons/business-marketing.md:297 — the doc is the stale side). A symbol name
 * is greppable and survives every edit above it; a line number does not.
 */
export const isAbortLike = (error: unknown): boolean => {
  const tag = classifyError(error)._tag;
  return tag === 'abort' || tag === 'timeout';
};

/**
 * A *deliberate* cancellation only — never retried. FEBT1-W2A-05 split
 * `AbortSignal.timeout` (`_tag 'timeout'`) out of this: a deadline that elapsed
 * is a server-side ambiguity (DDIA ch-8 UNKNOWN outcome), whereas an abort is
 * the caller withdrawing interest, and retrying it resurrects work nobody is
 * waiting for. Retry decisions must use this, not `isAbortLike`.
 */
export const isDeliberateAbort = (error: unknown): boolean => classifyError(error)._tag === 'abort';

/**
 * True when this error should open the shared recognition cooldown:
 * 429, or 503 carrying Retry-After. Not an `HTTPError` type guard —
 * classified AppError values and raw HTTPError instances both qualify
 * (W1-L1-09). Shared with the retry predicate (REF-19).
 */
export const isCooldownSignal = (error: unknown): boolean => isCooldown(error);

/**
 * Shared QueryClient retry predicate.
 * Retries 429, 503-with-Retry-After, and transport failures up to
 * RETRY_MAX_ATTEMPTS; retries the ambiguous outcomes (timeout, nonce refresh)
 * up to AMBIGUOUS_RETRY_MAX_ATTEMPTS; never 4xx, parse, unknown, or abort.
 * AuthExpiredError is an explicit non-retry pin (UXP-NET-2): session recovery is user-driven.
 */
export const shouldRetryRequest = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= RETRY_MAX_ATTEMPTS) {
    return false;
  }
  const classified = classifyError(error);
  // Regression pin: auth expiry is terminal for RQ retry (distinct from HTTPError 4xx).
  if (classified._tag === 'auth_expired') {
    return false;
  }
  if (classified._tag === 'http') {
    return isCooldown(classified);
  }
  if (classified._tag === 'parse') {
    return false;
  }
  // Abort is checked on the raw error too: a duck-typed AbortError that never
  // reached fetchApi must still short-circuit. Deliberate aborts only — a
  // timeout falls through to the bounded ambiguous-outcome budget below.
  if (isDeliberateAbort(error)) {
    return false;
  }
  if (Object.hasOwn(AMBIGUOUS_OUTCOME_TAGS, classified._tag)) {
    return failureCount < AMBIGUOUS_RETRY_MAX_ATTEMPTS;
  }
  return classified._tag === 'transport';
};

/**
 * Shared retry delay: honor Retry-After when it carries a real wait (clamped,
 * no jitter), else bounded exponential backoff with full jitter (RES-06).
 * Retry-After is also min-capped at MAX_RETRY_DELAY_MS so QueryClient waits
 * stay short even when the shared operational ceiling is higher.
 *
 * FEBT1-LB-01: the jittered branch is floored at RETRY_AFTER_MIN_MS. Full
 * jitter multiplies by rng() over [0,1), so an unfloored product reaches 0 and
 * the "backoff" degenerates into an immediate retry against a fault that is
 * still present — the exact amplification Release It! ch-5 warns about. The
 * floor removes the zero without removing the jitter: the delay is still drawn
 * from a random window, so a fleet does not resynchronise.
 */
export const getRetryDelay = (attemptIndex: number, error: unknown, rng: () => number = Math.random): number => {
  const exponential = Math.min(1000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
  const classified = classifyError(error);
  const retryAfterMs = classified._tag === 'http' ? classified.retryAfterMs : undefined;
  if (hasRetryAfterWait(retryAfterMs)) {
    return Math.min(clampRetryAfterMs(retryAfterMs / 1000, exponential), MAX_RETRY_DELAY_MS);
  }
  return Math.max(exponential * rng(), RETRY_AFTER_MIN_MS);
};
