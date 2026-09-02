/** Inclusive floor. Retry-After: 0 means retry immediately. */
export const RETRY_AFTER_MIN_MS = 0;

/**
 * Operational ceiling: 5 minutes.
 * Well below the 32-bit setTimeout bound (2^31-1 = 2_147_483_647) so a hostile
 * Retry-After cannot overflow into a 1ms hot loop, and well below an hour so a
 * misbehaving intermediary cannot freeze recognition pollers with no escape.
 */
export const RETRY_AFTER_MAX_MS = 300_000;

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
