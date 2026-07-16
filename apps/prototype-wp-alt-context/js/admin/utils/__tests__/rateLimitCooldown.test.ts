import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  _resetForTests,
  cooldownRemainingMs,
  DEFAULT_COOLDOWN_SECONDS,
  gateRefetchInterval,
  isCoolingDown,
  noteRateLimited,
  runAfterCooldown,
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

  it('gateRefetchInterval returns remaining cooldown ms during cooldown, baseMs after expiry', () => {
    const interval = gateRefetchInterval(15_000);

    expect(interval()).toBe(15_000);

    // Never false during cooldown: RQ clears a false interval permanently on idle pages.
    noteRateLimited(5);
    expect(interval()).toBe(5000);

    vi.advanceTimersByTime(3000);
    expect(interval()).toBe(2000);

    vi.advanceTimersByTime(2000);
    expect(interval()).toBe(15_000);
  });

  it('gateRefetchInterval clamps a nearly-expired cooldown to a 1s floor', () => {
    const interval = gateRefetchInterval(15_000);

    noteRateLimited(5);
    vi.advanceTimersByTime(4800);
    expect(interval()).toBe(1000);
  });

  it('noteRateLimited never shortens an armed cooldown', () => {
    noteRateLimited(60);
    noteRateLimited(null); // headerless default 30s must not shrink the 60s deadline

    expect(cooldownRemainingMs()).toBe(60_000);

    noteRateLimited(90);
    expect(cooldownRemainingMs()).toBe(90_000);
  });

  it('runAfterCooldown executes immediately when idle and defers during cooldown', () => {
    const fn = vi.fn();

    runAfterCooldown(fn);
    expect(fn).toHaveBeenCalledTimes(1);

    noteRateLimited(5);
    runAfterCooldown(fn);
    expect(fn).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(4999);
    expect(fn).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('gateRefetchInterval composes with conditional interval functions', () => {
    const interval = gateRefetchInterval<{ active: boolean }>((query) =>
      query.active ? 2000 : false,
    );

    expect(interval({ active: true })).toBe(2000);
    expect(interval({ active: false })).toBe(false);

    noteRateLimited(3);
    expect(interval({ active: true })).toBe(3000);
    expect(interval({ active: false })).toBe(3000);

    vi.advanceTimersByTime(3000);
    expect(interval({ active: true })).toBe(2000);
  });
});
