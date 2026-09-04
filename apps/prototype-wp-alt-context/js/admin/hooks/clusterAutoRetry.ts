/**
 * Bounded post-batch cluster auto-retry on cooldown signals (RES-06, API-08, RES-01, AGT-10, E-07).
 * Mutations never blind-retry: only isCooldown (429, or 503 with Retry-After) is retried, with a hard ceiling.
 * Shared poller cooldown is armed globally via MutationCache — do not open the cooldown here.
 */

import { __, sprintf } from '@wordpress/i18n';

import { classifyError, isCooldown } from '../utils/appError';
import { createLogger } from '../utils/logger';
import { DEFAULT_COOLDOWN_SECONDS } from '../utils/recognitionCooldown';
import { clampRetryAfterMs } from '../utils/retryAfter';

/** Total attempts including the first (first + 2 auto-retries). */
export const CLUSTER_RETRY_MAX_ATTEMPTS = 3;

const log = createLogger('hooks.clusterAutoRetry');

const retryDecisionFields = (error: unknown): { tag: string; status?: number } => {
  const classified = classifyError(error);
  return classified._tag === 'http'
    ? { tag: classified._tag, status: classified.status }
    : { tag: classified._tag };
};

export const isRetryableClusterError = (error: unknown): boolean => isCooldown(error);

export const resolveClusterRetryDelaySeconds = (error: unknown): number => {
  const classified = classifyError(error);
  const retryAfterSeconds =
    classified._tag === 'http' && classified.retryAfterMs !== undefined
      ? classified.retryAfterMs / 1000
      : undefined;
  return clampRetryAfterMs(retryAfterSeconds, DEFAULT_COOLDOWN_SECONDS * 1000) / 1000;
};

/** True when another auto-retry is still allowed after this failed attempt. */
export const canAutoRetryCluster = (attemptCount: number, error: unknown): boolean =>
  isRetryableClusterError(error) && attemptCount < CLUSTER_RETRY_MAX_ATTEMPTS;

export const formatClusterQueuedStatus = (seconds: number): string =>
  sprintf(__('Clustering queued — starting in %ds', 'alt-context'), seconds);

export const formatClusterRetryExhaustedMessage = (): string =>
  __('Clustering failed after rate-limit retries. Use Retry clustering to try again.', 'alt-context');

export interface ClusterAutoRetryListener {
  /** Fire one cluster mutation attempt (should not itself schedule retries). */
  mutate: () => void;
  /** Queued wait between auto-retries; null clears the queued status surface. */
  onQueued: (seconds: number | null) => void;
  /** Ceiling hit after cooldown retries — show manual Retry clustering affordance. */
  onExhausted: () => void;
  /** Terminal failure (non-cooldown or cooldown after ceiling). */
  onTerminalError: (message: string) => void;
  /** Fallback when error is not an Error instance. */
  fallbackErrorMessage: string;
}

/**
 * Imperative controller for cluster cooldown auto-retry. Owns attempt count + delay timer.
 * Compatible with vi.useFakeTimers (uses global setTimeout/clearTimeout).
 */
export const createClusterAutoRetry = (listener: ClusterAutoRetryListener) => {
  let attempts = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  // Mutation callbacks fire from Mutation.execute() even after unmount; the
  // latch stops a late cooldown from arming a zombie timer that POSTs in the background.
  let disposed = false;

  const clearTimer = (): void => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const fire = (): void => {
    if (disposed) {
      return;
    }
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
      if (disposed) {
        return;
      }
      reset();
      fire();
    },

    /** Manual Retry clustering after ceiling (or any terminal cluster error). */
    manualRetry: (): void => {
      if (disposed) {
        return;
      }
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
      if (disposed) {
        return false;
      }
      if (canAutoRetryCluster(attempts, error)) {
        const seconds = resolveClusterRetryDelaySeconds(error);
        // One line per retry decision (OBS-01): two invisible retries previously looked
        // identical to one successful try in the operator log.
        log.info('cluster.retry_scheduled', {
          ...retryDecisionFields(error),
          attempt: attempts,
          maxAttempts: CLUSTER_RETRY_MAX_ATTEMPTS,
          delayMs: seconds * 1000,
        });
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
        log.warn('cluster.retry_exhausted', {
          ...retryDecisionFields(error),
          attempt: attempts,
          maxAttempts: CLUSTER_RETRY_MAX_ATTEMPTS,
        });
        listener.onExhausted();
        listener.onTerminalError(formatClusterRetryExhaustedMessage());
        return false;
      }

      const message = error instanceof Error ? error.message : listener.fallbackErrorMessage;
      log.warn('cluster.retry_declined', { ...retryDecisionFields(error), attempt: attempts });
      listener.onTerminalError(message);
      return false;
    },

    /** Test/diagnostics: current attempt count (0 before first fire). */
    getAttemptCount: (): number => attempts,

    dispose: (): void => {
      disposed = true;
      clearTimer();
    },
  };
};

export type ClusterAutoRetryController = ReturnType<typeof createClusterAutoRetry>;
