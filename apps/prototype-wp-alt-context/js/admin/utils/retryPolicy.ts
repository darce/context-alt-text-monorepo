import { HTTPError, ResponseParseError } from './http';

export const RETRY_MAX_ATTEMPTS = 3;
export const MAX_RETRY_DELAY_MS = 30_000;

/** AbortError and TimeoutError (from AbortSignal.timeout) — both are abort-like, never retry. */
const ABORT_LIKE_NAMES = new Set(['AbortError', 'TimeoutError']);

/** Duck-type: DOMException is NOT an Error subclass in the browser. */
const isAbortLike = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  ABORT_LIKE_NAMES.has((error as { name?: unknown }).name as string);

/**
 * Shared QueryClient retry predicate.
 * Retries 429, 503-with-Retry-After, and TypeError transport failures; never 4xx, parse, or abort-like.
 */
export const shouldRetryRequest = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= RETRY_MAX_ATTEMPTS) {
    return false;
  }
  if (error instanceof HTTPError) {
    return error.status === 429 || (error.status === 503 && error.retryAfterSeconds !== undefined);
  }
  if (error instanceof ResponseParseError) {
    return false;
  }
  if (isAbortLike(error)) {
    return false;
  }
  // Genuine network transport failure only (Fetch spec rejects with TypeError).
  return error instanceof TypeError;
};

/**
 * Shared retry delay: honor Retry-After when present, else bounded exponential backoff.
 * Both branches clamped at MAX_RETRY_DELAY_MS to avoid hour freezes and setTimeout overflow.
 */
export const getRetryDelay = (attemptIndex: number, error: unknown): number => {
  if (error instanceof HTTPError && error.retryAfterSeconds !== undefined) {
    return Math.min(error.retryAfterSeconds * 1000, MAX_RETRY_DELAY_MS);
  }
  return Math.min(1000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
};
