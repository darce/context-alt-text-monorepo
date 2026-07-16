import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  _resetForTests,
  cooldownRemainingMs,
  DEFAULT_COOLDOWN_SECONDS,
  gateRefetchInterval,
  isCoolingDown,
  noteRateLimited,
} from '../rateLimitCooldown';

describe('rateLimitCooldown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-15T12:00:00.000Z'));
    _resetForTests();
  });

  afterEach(() => {
    _resetForTests();
    vi.useRealTimers();
  });

  it('sets cooldown from Retry-After seconds', () => {
    noteRateLimited(7);

    expect(isCoolingDown()).toBe(true);
    expect(cooldownRemainingMs()).toBe(7000);

    vi.advanceTimersByTime(6999);
    expect(isCoolingDown()).toBe(true);
    expect(cooldownRemainingMs()).toBe(1);

    vi.advanceTimersByTime(1);
    expect(isCoolingDown()).toBe(false);
    expect(cooldownRemainingMs()).toBe(0);
  });

  it('defaults to 30s when retryAfterSeconds is null', () => {
    noteRateLimited(null);

    expect(isCoolingDown()).toBe(true);
    expect(cooldownRemainingMs()).toBe(DEFAULT_COOLDOWN_SECONDS * 1000);

    vi.advanceTimersByTime(DEFAULT_COOLDOWN_SECONDS * 1000 - 1);
    expect(isCoolingDown()).toBe(true);

    vi.advanceTimersByTime(1);
    expect(isCoolingDown()).toBe(false);
  });

  it('gateRefetchInterval returns false during cooldown and baseMs after expiry', () => {
    const interval = gateRefetchInterval(15_000);

    expect(interval()).toBe(15_000);

    noteRateLimited(5);
    expect(interval()).toBe(false);

    vi.advanceTimersByTime(5000);
    expect(interval()).toBe(15_000);
  });

  it('gateRefetchInterval composes with conditional interval functions', () => {
    const interval = gateRefetchInterval<{ active: boolean }>((query) =>
      query.active ? 2000 : false,
    );

    expect(interval({ active: true })).toBe(2000);
    expect(interval({ active: false })).toBe(false);

    noteRateLimited(3);
    expect(interval({ active: true })).toBe(false);
    expect(interval({ active: false })).toBe(false);

    vi.advanceTimersByTime(3000);
    expect(interval({ active: true })).toBe(2000);
  });
});
