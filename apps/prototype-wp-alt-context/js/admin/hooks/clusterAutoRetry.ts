/**
 * Bounded post-batch cluster auto-retry on 429 (RES-06, API-08, RES-01, AGT-10).
 * Mutations never blind-retry: only HTTP 429 is retried, with a hard ceiling.
 * Shared poller cooldown is armed globally via MutationCache — do not noteRateLimited here.
 */

import { __, sprintf } from '@wordpress/i18n';

import { HTTPError } from '../utils/http';
import { DEFAULT_COOLDOWN_SECONDS } from '../utils/rateLimitCooldown';

/** Total attempts including the first (first + 2 auto-retries). */
export const CLUSTER_RETRY_MAX_ATTEMPTS = 3;

export const isRetryableClusterError = (error: unknown): error is HTTPError =>
  error instanceof HTTPError && error.status === 429;

export const resolveClusterRetryDelaySeconds = (error: HTTPError): number =>
  error.retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS;

/** True when another auto-retry is still allowed after this failed attempt. */
export const canAutoRetryCluster = (attemptCount: number, error: unknown): boolean =>
  isRetryableClusterError(error) && attemptCount < CLUSTER_RETRY_MAX_ATTEMPTS;

export const formatClusterQueuedStatus = (seconds: number): string =>
  sprintf(__('Clustering queued — starting in %ds', 'alt-context'), seconds);

export const formatClusterRetryExhaustedMessage = (): string =>
  __('Clustering failed after rate-limit retries. Use Retry clustering to try again.', 'alt-context');

export type ClusterAutoRetryListener = {
  /** Fire one cluster mutation attempt (should not itself schedule retries). */
  mutate: () => void;
  /** Queued wait between auto-retries; null clears the queued status surface. */
  onQueued: (seconds: number | null) => void;
  /** Ceiling hit after 429s — show manual Retry clustering affordance. */
  onExhausted: () => void;
  /** Terminal failure (non-429 or 429 after ceiling). */
  onTerminalError: (message: string) => void;
  /** Fallback when error is not an Error instance. */
  fallbackErrorMessage: string;
};

/**
 * Imperative controller for cluster 429 auto-retry. Owns attempt count + delay timer.
 * Compatible with vi.useFakeTimers (uses global setTimeout/clearTimeout).
 */
export const createClusterAutoRetry = (listener: ClusterAutoRetryListener) => {
  let attempts = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const clearTimer = (): void => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const fire = (): void => {
    attempts += 1;
    listener.mutate();
  };

  const reset = (): void => {
    clearTimer();
    attempts = 0;
    listener.onQueued(null);
  };

  return {
    /** Begin a new auto-retry sequence (post-batch or fresh manual cluster). */
    start: (): void => {
      reset();
      fire();
    },

    /** Manual Retry clustering after ceiling (or any terminal cluster error). */
    manualRetry: (): void => {
      reset();
      fire();
    },

    /** Call on mutation success — clears queue + attempt state. */
    noteSuccess: (): void => {
      reset();
    },

    /**
     * Call on mutation error.
     * @returns true when a retry was scheduled (caller must not surface error yet).
     */
    noteError: (error: unknown): boolean => {
      if (canAutoRetryCluster(attempts, error)) {
        const httpError = error as HTTPError;
        const seconds = resolveClusterRetryDelaySeconds(httpError);
        listener.onQueued(seconds);
        timer = setTimeout(() => {
          timer = null;
          listener.onQueued(null);
          fire();
        }, seconds * 1000);
        return true;
      }

      clearTimer();
      listener.onQueued(null);

      if (isRetryableClusterError(error)) {
        listener.onExhausted();
        listener.onTerminalError(formatClusterRetryExhaustedMessage());
        return false;
      }

      const message =
        error instanceof Error ? error.message : listener.fallbackErrorMessage;
      listener.onTerminalError(message);
      return false;
    },

    /** Test/diagnostics: current attempt count (0 before first fire). */
    getAttemptCount: (): number => attempts,

    dispose: (): void => {
      clearTimer();
    },
  };
};

export type ClusterAutoRetryController = ReturnType<typeof createClusterAutoRetry>;
