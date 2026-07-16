/**
 * Shared client-side 429 cooldown (RES-06, RES-15, API-08, AGT-10).
 * Module-level singleton: any 429 starts a cooldown that gates participating pollers.
 */

export const DEFAULT_COOLDOWN_SECONDS = 30;

let cooldownUntilMs = 0;

/**
 * Start or extend the global cooldown from a 429.
 * Uses Retry-After when present; otherwise DEFAULT_COOLDOWN_SECONDS.
 */
export const noteRateLimited = (retryAfterSeconds: number | null): void => {
  const seconds = retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS;
  cooldownUntilMs = Date.now() + seconds * 1000;
};

/** True while Date.now() is before the cooldown deadline. */
export const isCoolingDown = (): boolean => Date.now() < cooldownUntilMs;

/** Remaining cooldown in ms (0 when not cooling down). Observable for future UI (AGT-10). */
export const cooldownRemainingMs = (): number => Math.max(0, cooldownUntilMs - Date.now());

/**
 * React Query refetchInterval function that yields false during cooldown,
 * otherwise the fixed base interval.
 */
export function gateRefetchInterval(baseMs: number): () => number | false;

/**
 * Compose cooldown gate with a conditional refetchInterval callback
 * (cooldown check first, then existing site logic).
 */
export function gateRefetchInterval<TQuery>(
  baseFn: (query: TQuery) => number | false,
): (query: TQuery) => number | false;

export function gateRefetchInterval<TQuery>(
  baseMsOrFn: number | ((query: TQuery) => number | false),
): (query: TQuery) => number | false {
  return (query: TQuery) => {
    if (isCoolingDown()) {
      return false;
    }
    if (typeof baseMsOrFn === 'function') {
      return baseMsOrFn(query);
    }
    return baseMsOrFn;
  };
}

/** Test-only: clear module cooldown between tests. */
export const _resetForTests = (): void => {
  cooldownUntilMs = 0;
};
