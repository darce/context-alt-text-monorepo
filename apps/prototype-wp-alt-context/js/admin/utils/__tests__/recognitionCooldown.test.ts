import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { classifyError } from '../appError';
import { HTTPError } from '../http';
import { RETRY_AFTER_MAX_MS } from '../retryAfter';
import {
  _resetCooldownForTests,
  cooldownRemainingMs,
  cooldownRemainingSeconds,
  DEFAULT_COOLDOWN_SECONDS,
  gateRefetchInterval,
  getCooldownExpiresAt,
  isCoolingDown,
  openCooldown,
  openCooldownFromError,
  runAfterCooldown,
  subscribeToCooldown,
} from '../recognitionCooldown';

const httpError = (status: number, retryAfterSeconds?: number): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: '/acx/v1/recognition/jobs/1',
    bodyPreview: '',
    message: `failed (${status})`,
  });

describe('recognitionCooldown', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-07-16T12:00:00.000Z'));
    _resetCooldownForTests();
  });

  afterEach(() => {
    _resetCooldownForTests();
    vi.useRealTimers();
  });

  it('openCooldown arms the window; isCoolingDown flips exactly at expiry', () => {
    expect(isCoolingDown()).toBe(false);

    openCooldown(7);
    expect(isCoolingDown()).toBe(true);
    expect(cooldownRemainingMs()).toBe(7000);
    expect(cooldownRemainingSeconds()).toBe(7);

    vi.advanceTimersByTime(6999);
    expect(isCoolingDown()).toBe(true);

    vi.advanceTimersByTime(1);
    expect(isCoolingDown()).toBe(false);
    expect(cooldownRemainingMs()).toBe(0);
  });

  it('isCoolingDown computes from expiresAt at call time, never a timer-flipped flag [REF-09]', () => {
    openCooldown(5);
    expect(isCoolingDown()).toBe(true);

    // Jump wall-clock past expiry WITHOUT running any timer callbacks — a
    // cached setTimeout flag would still read true (throttled background tab).
    vi.setSystemTime(new Date('2026-07-16T12:00:06.000Z'));
    expect(isCoolingDown()).toBe(false);
    expect(cooldownRemainingMs()).toBe(0);
  });

  it('never shortens an armed cooldown', () => {
    openCooldown(60);
    openCooldown(10);
    expect(cooldownRemainingMs()).toBe(60_000);

    openCooldown(90);
    expect(cooldownRemainingMs()).toBe(90_000);
  });

  describe('openCooldownFromError', () => {
    it('arms from 429 honoring Retry-After', () => {
      openCooldownFromError(httpError(429, 12));
      expect(cooldownRemainingMs()).toBe(12_000);
    });

    it('arms from headerless 429 with the default window', () => {
      openCooldownFromError(httpError(429));
      expect(cooldownRemainingMs()).toBe(DEFAULT_COOLDOWN_SECONDS * 1000);
    });

    it('arms from 503 with Retry-After', () => {
      openCooldownFromError(httpError(503, 20));
      expect(cooldownRemainingMs()).toBe(20_000);
    });

    it('ignores bare 503, other statuses, and non-HTTP errors', () => {
      openCooldownFromError(httpError(503));
      openCooldownFromError(httpError(404));
      openCooldownFromError(httpError(500, 9));
      openCooldownFromError(new TypeError('network down'));
      openCooldownFromError(undefined);
      expect(isCoolingDown()).toBe(false);
    });

    it('clamps Retry-After: 3600 to the shared ceiling at the cooldown call site [E-01]', () => {
      openCooldownFromError(httpError(429, 3600));
      expect(cooldownRemainingMs()).toBe(RETRY_AFTER_MAX_MS);
    });

    it('clamps overflow-scale Retry-After below the 32-bit setTimeout bound [E-01]', () => {
      openCooldownFromError(httpError(429, 2_678_400));
      expect(cooldownRemainingMs()).toBe(RETRY_AFTER_MAX_MS);
      expect(cooldownRemainingMs()).toBeLessThan(2 ** 31 - 1);
    });

    it('falls back to DEFAULT_COOLDOWN_SECONDS for negative/NaN/Infinity Retry-After [E-01]', () => {
      openCooldownFromError(httpError(429, Number.NaN));
      expect(cooldownRemainingMs()).toBe(DEFAULT_COOLDOWN_SECONDS * 1000);
      _resetCooldownForTests();

      openCooldownFromError(httpError(429, Number.POSITIVE_INFINITY));
      expect(cooldownRemainingMs()).toBe(DEFAULT_COOLDOWN_SECONDS * 1000);
      _resetCooldownForTests();

      openCooldownFromError(httpError(429, -12));
      expect(cooldownRemainingMs()).toBe(DEFAULT_COOLDOWN_SECONDS * 1000);
    });

    it('honors retryAfterMs on a pre-classified AppError [W1-L1-09]', () => {
      openCooldownFromError(classifyError(httpError(429, 5)));
      expect(cooldownRemainingMs()).toBe(5_000);
    });

    it('never arms from abort-like errors — a local timeout must not freeze all six pollers', () => {
      // The slice-1 HIGH was exactly this class: 'TimeoutError' (AbortSignal.timeout)
      // treated differently from 'AbortError'. A client-side timeout is not a server
      // back-off signal; arming here would turn every 10s status-poll timeout into a
      // 30s global suspension of the whole gated set.
      openCooldownFromError(new DOMException('signal timed out', 'TimeoutError'));
      openCooldownFromError(new DOMException('The user aborted a request.', 'AbortError'));
      expect(isCoolingDown()).toBe(false);
    });
  });

  describe('gateRefetchInterval', () => {
    it('returns remaining cooldown ms while cooling, base interval after expiry — never false during cooldown', () => {
      const interval = gateRefetchInterval(1500);
      expect(interval()).toBe(1500);

      openCooldown(5);
      expect(interval()).toBe(5000);

      vi.advanceTimersByTime(3000);
      expect(interval()).toBe(2000);

      vi.advanceTimersByTime(2000);
      expect(interval()).toBe(1500);
    });

    it('floors a nearly-expired cooldown at 1s', () => {
      const interval = gateRefetchInterval(1500);
      openCooldown(5);
      vi.advanceTimersByTime(4900);
      expect(interval()).toBe(1000);
    });

    it('composes with conditional interval callbacks — cooldown wins even where the site returns false', () => {
      const interval = gateRefetchInterval<{ active: boolean }>((query) => (query.active ? 2000 : false));

      expect(interval({ active: true })).toBe(2000);
      expect(interval({ active: false })).toBe(false);

      openCooldown(4);
      expect(interval({ active: true })).toBe(4000);
      expect(interval({ active: false })).toBe(4000);

      vi.advanceTimersByTime(4000);
      expect(interval({ active: false })).toBe(false);
    });
  });

  describe('subscribe/notify', () => {
    it('notifies subscribers when the window opens or extends, not on shorter re-arms', () => {
      const listener = vi.fn();
      const unsubscribe = subscribeToCooldown(listener);

      openCooldown(30);
      expect(listener).toHaveBeenCalledTimes(1);

      openCooldown(5); // shorter — no state change, no notify
      expect(listener).toHaveBeenCalledTimes(1);

      openCooldown(60);
      expect(listener).toHaveBeenCalledTimes(2);

      unsubscribe();
      openCooldown(90);
      expect(listener).toHaveBeenCalledTimes(2);
    });

    it('exposes the expiry timestamp as a stable snapshot', () => {
      expect(getCooldownExpiresAt()).toBe(0);
      openCooldown(10);
      expect(getCooldownExpiresAt()).toBe(Date.now() + 10_000);
    });
  });

  describe('runAfterCooldown', () => {
    it('executes immediately when idle and defers until expiry during cooldown', () => {
      const fn = vi.fn();

      runAfterCooldown(fn);
      expect(fn).toHaveBeenCalledTimes(1);

      openCooldown(5);
      runAfterCooldown(fn);
      expect(fn).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(4999);
      expect(fn).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(1);
      expect(fn).toHaveBeenCalledTimes(2);
    });
  });
});
