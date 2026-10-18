/**
 * Inclusive floor for every retry wait. No retry is ever immediate.
 *
 * Release It! ch-5 / RES-06: "immediate retry against a persistent fault fails
 * again and amplifies the outage". restful-web-api-patterns ch-7 ranks
 * *immediate* retry last and permits it only for LB/gateway blips, and names
 * fleet-synchronised retry schedules as the retry-storm trigger. A zero floor
 * let three separate routes produce a synchronised zero-delay retry:
 * `Retry-After: 0`, a `clampRetryAfterMs` fallback of 0, and full jitter that
 * rolled `rng() === 0`. 1s is the smallest wait that is not "immediate" and
 * matches `MIN_GATED_INTERVAL_MS` in recognitionCooldown.ts, which already
 * refuses to hand a caller a zero-length window.
 */
export const RETRY_AFTER_MIN_MS = 1_000;

/**
 * Operational ceiling: 5 minutes.
 * Well below the 32-bit setTimeout bound (2^31-1 = 2_147_483_647) so a hostile
 * Retry-After cannot overflow into a 1ms hot loop, and well below an hour so a
 * misbehaving intermediary cannot freeze recognition pollers with no escape.
 */
export const RETRY_AFTER_MAX_MS = 300_000;

/**
 * True when a parsed Retry-After actually instructs the client to wait.
 *
 * Single owner (REF-19) for "this Retry-After carries a wait instruction",
 * shared by `isCooldown`, `getRetryDelay` and `cooldownSecondsFromError`.
 * `0` and absent are the same answer: the server named no delay, so the client
 * must fall back to its own jittered backoff rather than retry at once. This is
 * the delta-seconds twin of the rule `parseRetryAfter` already applies to an
 * HTTP-date that is not in the future.
 */
export const hasRetryAfterWait = (retryAfterMs: number | undefined): retryAfterMs is number =>
  retryAfterMs !== undefined && Number.isFinite(retryAfterMs) && retryAfterMs > 0;

const clampMs = (ms: number): number => Math.min(Math.max(ms, RETRY_AFTER_MIN_MS), RETRY_AFTER_MAX_MS);

const clampFallbackMs = (fallbackMs: number): number => {
  if (!Number.isFinite(fallbackMs) || fallbackMs < 0) {
    return RETRY_AFTER_MIN_MS;
  }
  return clampMs(fallbackMs);
};

/**
 * Convert Retry-After seconds into a bounded millisecond delay.
 * Non-finite, negative, and missing values fall back (then clamped).
 */
export const clampRetryAfterMs = (seconds: number | undefined, fallbackMs: number): number => {
  const fallback = clampFallbackMs(fallbackMs);
  if (seconds === undefined || !Number.isFinite(seconds) || seconds < 0) {
    return fallback;
  }
  const ms = seconds * 1000;
  if (!Number.isFinite(ms)) {
    return fallback;
  }
  return clampMs(ms);
};
