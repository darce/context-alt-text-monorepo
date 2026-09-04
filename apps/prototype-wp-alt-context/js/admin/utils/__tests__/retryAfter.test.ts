import { describe, expect, it } from 'vitest';

import { clampRetryAfterMs, RETRY_AFTER_MAX_MS, RETRY_AFTER_MIN_MS } from '../retryAfter';

const FALLBACK_MS = 30_000;

describe('clampRetryAfterMs [E-01]', () => {
  it('clamps Retry-After: 3600 to the operational ceiling', () => {
    expect(clampRetryAfterMs(3600, FALLBACK_MS)).toBe(RETRY_AFTER_MAX_MS);
  });

  it('clamps overflow-scale Retry-After: 2_678_400 below the 32-bit setTimeout bound', () => {
    const clamped = clampRetryAfterMs(2_678_400, FALLBACK_MS);
    expect(clamped).toBe(RETRY_AFTER_MAX_MS);
    expect(clamped).toBeLessThan(2 ** 31 - 1);
  });

  it('rejects negative, NaN, Infinity, and undefined and falls back', () => {
    expect(clampRetryAfterMs(undefined, FALLBACK_MS)).toBe(FALLBACK_MS);
    expect(clampRetryAfterMs(Number.NaN, FALLBACK_MS)).toBe(FALLBACK_MS);
    expect(clampRetryAfterMs(Number.POSITIVE_INFINITY, FALLBACK_MS)).toBe(FALLBACK_MS);
    expect(clampRetryAfterMs(Number.NEGATIVE_INFINITY, FALLBACK_MS)).toBe(FALLBACK_MS);
    expect(clampRetryAfterMs(-1, FALLBACK_MS)).toBe(FALLBACK_MS);
  });

  it('preserves Retry-After: 0 (retry immediately) and in-range values', () => {
    expect(clampRetryAfterMs(0, FALLBACK_MS)).toBe(RETRY_AFTER_MIN_MS);
    expect(clampRetryAfterMs(12, FALLBACK_MS)).toBe(12_000);
  });
});
