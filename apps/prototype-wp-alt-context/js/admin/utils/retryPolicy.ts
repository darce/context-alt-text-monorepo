import { classifyError, isCooldown } from './appError';
import { clampRetryAfterMs } from './retryAfter';

export const RETRY_MAX_ATTEMPTS = 3;
export const MAX_RETRY_DELAY_MS = 30_000;

/** AbortError and TimeoutError (from AbortSignal.timeout) — both are abort-like, never retry. */
export const isAbortLike = (error: unknown): boolean => classifyError(error)._tag === 'abort';

/**
 * True when this error should open the shared recognition cooldown:
 * 429, or 503 carrying Retry-After. Not an `HTTPError` type guard —
 * classified AppError values and raw HTTPError instances both qualify
 * (W1-L1-09). Shared with the retry predicate (REF-19).
 */
export const isCooldownSignal = (error: unknown): boolean => isCooldown(error);

/**
 * Shared QueryClient retry predicate.
 * Retries 429, 503-with-Retry-After, and TypeError transport failures; never 4xx, parse, or abort-like.
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
  if (isAbortLike(error)) {
    return false;
  }
  return classified._tag === 'transport' || classified._tag === 'nonce_refresh';
};

/**
 * Shared retry delay: honor Retry-After when present (clamped, no jitter),
 * else bounded exponential backoff with full jitter (RES-06).
 * Retry-After is also min-capped at MAX_RETRY_DELAY_MS so QueryClient waits
 * stay short even when the shared operational ceiling is higher.
 */
export const getRetryDelay = (
  attemptIndex: number,
  error: unknown,
  rng: () => number = Math.random,
): number => {
  const exponential = Math.min(1000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
  const classified = classifyError(error);
  if (classified._tag === 'http' && classified.retryAfterMs !== undefined) {
    const seconds = classified.retryAfterMs / 1000;
    return Math.min(clampRetryAfterMs(seconds, exponential), MAX_RETRY_DELAY_MS);
  }
  return exponential * rng();
};
