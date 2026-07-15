import { HTTPError, ResponseParseError } from './http';

export const RETRY_MAX_ATTEMPTS = 3;

/**
 * Shared QueryClient retry predicate.
 * Retries 429, 503-with-Retry-After, and transport failures; never 4xx or parse errors.
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
  // DOMException is NOT instanceof Error — duck-type by name
  if (typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError') {
    return false;
  }
  // transport failure
  return true;
};

/**
 * Shared retry delay: honor Retry-After when present, else bounded exponential backoff.
 */
export const getRetryDelay = (attemptIndex: number, error: unknown): number => {
  if (error instanceof HTTPError && error.retryAfterSeconds !== undefined) {
    return error.retryAfterSeconds * 1000;
  }
  return Math.min(1000 * 2 ** attemptIndex, 30_000);
};
