/**
 * Status-aware React Query retry policy (RES-06, API-08).
 * Shared by the QueryClient defaults (App.tsx) and per-query overrides that
 * need extra classification (e.g. job-status 404 = job gone, stop polling).
 */

import { HTTPError } from './http';
import { noteRateLimited } from './rateLimitCooldown';

/** Max retries after the first failure (API-08: ~3 total attempts). */
export const QUERY_MAX_RETRIES = 2;

export const isAbortLike = (error: unknown): boolean => {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  if (error instanceof Error && error.name === 'AbortError') {
    return true;
  }
  return false;
};

/** Start shared poller cooldown on any 429 (RES-15 client-side breaker). */
export const note429IfPresent = (error: unknown): void => {
  if (error instanceof HTTPError && error.status === 429) {
    noteRateLimited(error.retryAfterSeconds);
  }
};

/**
 * Status-aware query retry (RES-06/API-08).
 * Never retries unmodified 4xx except 429; 429 and 5xx/network are bounded.
 * AbortError is timeout classification — never HTTP-retried.
 */
export const shouldRetryQuery = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= QUERY_MAX_RETRIES) {
    return false;
  }
  if (isAbortLike(error)) {
    return false;
  }
  if (error instanceof HTTPError) {
    if (error.status === 429) {
      noteRateLimited(error.retryAfterSeconds);
      return true;
    }
    if (error.status >= 400 && error.status < 500) {
      return false;
    }
    return true;
  }
  // Network / non-HTTP errors: keep bounded retry.
  return true;
};

/**
 * Job-status poller retry: 404 means the job no longer exists — stop polling;
 * everything else follows the shared status-aware policy.
 */
export const shouldRetryJobStatusQuery = (failureCount: number, error: unknown): boolean => {
  if (error instanceof HTTPError && error.status === 404) {
    return false;
  }
  return shouldRetryQuery(failureCount, error);
};

/**
 * Bounded exponential backoff (RES-06), with 429 + Retry-After honoring the server.
 * Also arms the shared poller cooldown so concurrent pollers pause (RES-15).
 */
export const getQueryRetryDelay = (attemptIndex: number, error: unknown): number => {
  if (error instanceof HTTPError && error.status === 429) {
    noteRateLimited(error.retryAfterSeconds);
    if (error.retryAfterSeconds != null) {
      return error.retryAfterSeconds * 1000;
    }
  }
  return Math.min(1000 * 2 ** attemptIndex, 30000);
};
