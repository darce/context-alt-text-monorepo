import { classifyError, isCooldown } from './appError';
import type { HTTPError } from './http';

export const RETRY_MAX_ATTEMPTS = 3;
export const MAX_RETRY_DELAY_MS = 30_000;

/** AbortError and TimeoutError (from AbortSignal.timeout) — both are abort-like, never retry. */
export const isAbortLike = (error: unknown): boolean => classifyError(error)._tag === 'abort';

/**
 * The server's explicit "ask again later": 429, or 503 carrying Retry-After.
 * Single classification shared by the retry predicate and the recognition
 * cooldown (REF-19: one policy, no per-consumer re-derivation).
 */
export const isCooldownSignal = (error: unknown): error is HTTPError => isCooldown(error);

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
  return classified._tag === 'transport';
};

/**
 * Shared retry delay: honor Retry-After when present, else bounded exponential backoff.
 * Both branches clamped at MAX_RETRY_DELAY_MS to avoid hour freezes and setTimeout overflow.
 */
export const getRetryDelay = (attemptIndex: number, error: unknown): number => {
  const classified = classifyError(error);
  if (classified._tag === 'http' && classified.retryAfterMs !== undefined) {
    return Math.min(classified.retryAfterMs, MAX_RETRY_DELAY_MS);
  }
  return Math.min(1000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
};
