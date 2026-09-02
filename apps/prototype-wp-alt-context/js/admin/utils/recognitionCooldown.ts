/**
 * Shared recognition cooldown (UXP-2 slice 2; RES-06, RES-15, API-08).
 *
 * Module-level single source of truth (sr-007): one "ask again later" from a
 * recognition-backed request quiets every gated poller for the server-stated
 * window. Membership is the explicit poller set in the task plan —
 * useScanStatus, useMultiScanStatus, useBatchRunStatus, useDescribeRunProgress,
 * useMediaIdentities, useRecognitionClusters, and useExportJobStatus (the 7th,
 * added by the slice-2 review fix — its 2s poll reaches recognition via the
 * retention export-status proxy). useSyncHealth / useSyncStatus read local
 * state only and are deliberately not gated.
 */

import { classifyError } from './appError';
import { HTTPError } from './http';
import { clampRetryAfterMs } from './retryAfter';
import { isCooldownSignal } from './retryPolicy';

/** Window applied when the server sends 429 without a usable Retry-After. */
export const DEFAULT_COOLDOWN_SECONDS = 30;

/**
 * Floor for the gated interval near expiry. React Query clears the timer
 * entirely when refetchInterval is false and only re-evaluates on query
 * events (never fired on idle pages), so the gate must always return a real
 * delay to guarantee polling resumes — never false during cooldown.
 */
const MIN_GATED_INTERVAL_MS = 1_000;

let expiresAtMs = 0;

const listeners = new Set<() => void>();

const notify = (): void => {
  listeners.forEach((listener) => listener());
};

/**
 * Open (or extend) the cooldown window. A longer already-armed deadline wins —
 * the cooldown never shortens.
 */
export const openCooldown = (seconds: number): void => {
  const candidate = Date.now() + Math.max(0, seconds) * 1000;
  if (candidate > expiresAtMs) {
    expiresAtMs = candidate;
    notify();
  }
};

const cooldownSecondsFromError = (error: unknown): number => {
  let seconds: number | undefined;
  if (error instanceof HTTPError) {
    seconds = error.retryAfterSeconds;
  } else {
    const classified = classifyError(error);
    if (classified._tag === 'http' && classified.retryAfterMs !== undefined) {
      seconds = classified.retryAfterMs / 1000;
    }
  }
  return clampRetryAfterMs(seconds, DEFAULT_COOLDOWN_SECONDS * 1000) / 1000;
};

/**
 * Arm the cooldown from a request error when — and only when — it is the
 * server's explicit "ask again later" (429, or 503 with Retry-After).
 */
export const openCooldownFromError = (error: unknown): void => {
  if (isCooldownSignal(error)) {
    openCooldown(cooldownSecondsFromError(error));
  }
};

/**
 * Computed from expiresAt at call time (REF-09) — never a flag flipped by a
 * setTimeout callback, which background-tab throttling would leave stale.
 */
export const isCoolingDown = (): boolean => Date.now() < expiresAtMs;

/** Remaining window in ms (0 when idle). Observable for UI surfaces (RES-15/OBS-05). */
export const cooldownRemainingMs = (): number => Math.max(0, expiresAtMs - Date.now());

/** Remaining window in whole seconds, rounded up for human announcement. */
export const cooldownRemainingSeconds = (): number => Math.ceil(cooldownRemainingMs() / 1000);

/** Stable snapshot for useSyncExternalStore consumers. */
export const getCooldownExpiresAt = (): number => expiresAtMs;

/** Subscribe to window changes; returns the unsubscribe function. */
export const subscribeToCooldown = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/**
 * Wrap a poller's refetchInterval so it waits out the cooldown, then resumes
 * its own cadence. During cooldown it returns the remaining window (floored at
 * 1s), never false — a false interval is cleared permanently on idle pages.
 */
export function gateRefetchInterval(baseMs: number): () => number | false;

/**
 * Compose the cooldown gate with a conditional refetchInterval callback
 * (cooldown check first, then the site's own logic).
 */
export function gateRefetchInterval<TQuery>(
  baseFn: (query: TQuery) => number | false,
): (query: TQuery) => number | false;

export function gateRefetchInterval<TQuery>(
  baseMsOrFn: number | ((query: TQuery) => number | false),
): (query: TQuery) => number | false {
  return (query: TQuery) => {
    if (isCoolingDown()) {
      return Math.max(MIN_GATED_INTERVAL_MS, cooldownRemainingMs());
    }
    if (typeof baseMsOrFn === 'function') {
      return baseMsOrFn(query);
    }
    return baseMsOrFn;
  };
}

/**
 * Run `fn` immediately when no cooldown is active, otherwise defer it until
 * the window expires. Invalidation-triggered refetch bursts bypass
 * refetchInterval gating, so job-completion handlers use this to hold them
 * out of an active window (ported from UXP-NET-1's rateLimitCooldown).
 */
export const runAfterCooldown = (fn: () => void): void => {
  if (!isCoolingDown()) {
    fn();
    return;
  }
  setTimeout(fn, cooldownRemainingMs());
};

/** Test-only: clear module state between tests. */
export const _resetCooldownForTests = (): void => {
  expiresAtMs = 0;
  notify();
};
