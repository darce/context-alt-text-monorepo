/**
 * Shared client-side 429 cooldown (RES-06, RES-15, API-08, AGT-10).
 * Module-level singleton: any 429 starts a cooldown that gates participating pollers.
 */

export const DEFAULT_COOLDOWN_SECONDS = 30;

/**
 * Floor for the gated interval during cooldown. React Query clears the timer
 * entirely when refetchInterval is false and only re-evaluates on query events,
 * so the gate must return a real delay to guarantee polling resumes at expiry.
 */
const MIN_GATED_INTERVAL_MS = 1_000;

let cooldownUntilMs = 0;

/**
 * Start or extend the global cooldown from a 429.
 * Uses Retry-After when present; otherwise DEFAULT_COOLDOWN_SECONDS.
 * Never shortens an already-armed cooldown (a longer server-stated deadline wins).
 */
export const noteRateLimited = (retryAfterSeconds: number | null): void => {
  const seconds = retryAfterSeconds ?? DEFAULT_COOLDOWN_SECONDS;
  cooldownUntilMs = Math.max(cooldownUntilMs, Date.now() + seconds * 1000);
};

/** True while Date.now() is before the cooldown deadline. */
export const isCoolingDown = (): boolean => Date.now() < cooldownUntilMs;

/** Remaining cooldown in ms (0 when not cooling down). Observable for future UI (AGT-10). */
export const cooldownRemainingMs = (): number => Math.max(0, cooldownUntilMs - Date.now());

/**
 * React Query refetchInterval function that waits out the cooldown, then the
 * fixed base interval. During cooldown it returns the remaining cooldown time
 * (never false: a false interval is cleared and only re-evaluated on query
 * events, which never fire on idle pages — polling would freeze permanently).
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
 * the cooldown expires. Used to hold invalidation-triggered refetch bursts
 * (they bypass refetchInterval) out of an active rate-limit window.
 */
export const runAfterCooldown = (fn: () => void): void => {
  if (!isCoolingDown()) {
    fn();
    return;
  }
  setTimeout(fn, cooldownRemainingMs());
};

/** Test-only: clear module cooldown between tests. */
export const _resetForTests = (): void => {
  cooldownUntilMs = 0;
};
