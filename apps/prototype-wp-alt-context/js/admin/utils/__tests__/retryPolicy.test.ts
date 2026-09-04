import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NonceRefreshFailedError } from '../../api/config';
import { classifyError } from '../appError';
import { AuthExpiredError, HTTPError, ResponseParseError } from '../http';
import { clampRetryAfterMs, RETRY_AFTER_MAX_MS, RETRY_AFTER_MIN_MS } from '../retryAfter';
import {
  AMBIGUOUS_RETRY_MAX_ATTEMPTS,
  getRetryDelay,
  isAbortLike,
  isDeliberateAbort,
  isCooldownSignal,
  MAX_RETRY_DELAY_MS,
  RETRY_MAX_ATTEMPTS,
  shouldRetryRequest,
} from '../retryPolicy';

const httpError = (status: number, retryAfterSeconds?: number): HTTPError =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: 'http://example.test/e',
    bodyPreview: 'body',
    message: `Request to http://example.test/e failed (${status}): body`,
  });

describe('shouldRetryRequest', () => {
  it('retries a 429 (rate limited)', () => {
    expect(shouldRetryRequest(0, httpError(429, 5))).toBe(true);
    expect(shouldRetryRequest(0, httpError(429))).toBe(true);
  });

  it('retries a 503 only when it carries Retry-After (breaker open, ask again later)', () => {
    expect(shouldRetryRequest(0, httpError(503, 10))).toBe(true);
    expect(shouldRetryRequest(0, httpError(503))).toBe(false);
  });

  it('never retries other 5xx — the proxy already exhausted its 5xx budget (RES-06)', () => {
    expect(shouldRetryRequest(0, httpError(500))).toBe(false);
    expect(shouldRetryRequest(0, httpError(502))).toBe(false);
    expect(shouldRetryRequest(0, httpError(504))).toBe(false);
  });

  it('never retries a 4xx other than 429 (API-08)', () => {
    expect(shouldRetryRequest(0, httpError(400))).toBe(false);
    expect(shouldRetryRequest(0, httpError(401))).toBe(false);
    expect(shouldRetryRequest(0, httpError(403))).toBe(false);
    expect(shouldRetryRequest(0, httpError(404))).toBe(false);
    expect(shouldRetryRequest(0, httpError(409))).toBe(false);
  });

  it('never retries AuthExpiredError (UXP-NET-2 regression pin) [TEST-15]', () => {
    const authExpired = new AuthExpiredError({
      endpoint: 'http://example.test/e',
      status: 403,
    });
    expect(shouldRetryRequest(0, authExpired)).toBe(false);
    expect(shouldRetryRequest(1, authExpired)).toBe(false);
    // Cooldown paths stay retryable (byte-unchanged classification).
    expect(shouldRetryRequest(0, httpError(429, 5))).toBe(true);
    expect(shouldRetryRequest(0, httpError(503, 10))).toBe(true);
  });

  it('retries a genuine network transport failure (fetch rejects with a TypeError)', () => {
    // Per the Fetch spec a network failure rejects with a TypeError in every browser
    // (Chrome "Failed to fetch", Firefox "NetworkError when attempting to fetch resource").
    expect(shouldRetryRequest(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetryRequest(0, new TypeError('NetworkError when attempting to fetch resource'))).toBe(true);
  });

  // FEBT-1-W1-E-05: strengthened, not relaxed. The old pin required *every*
  // TypeError to retry, so `x is not a function` — a deterministic programming
  // bug that will fail identically three times — burned the whole budget. The
  // network-failure half of the claim is kept verbatim; the bug half is
  // inverted to a non-retry, which is the stronger assertion.
  it('retries a fetch network-failure TypeError, never a programming-bug TypeError [F5]', () => {
    expect(classifyError(new TypeError('Failed to fetch'))._tag).toBe('transport');
    expect(shouldRetryRequest(0, new TypeError('boom: Failed to fetch'))).toBe(true);

    expect(classifyError(new TypeError('x is not a function'))._tag).toBe('unknown');
    expect(shouldRetryRequest(0, new TypeError('x is not a function'))).toBe(false);
  });

  it('does not retry a deterministic non-transport error (a response was received)', () => {
    // e.g. fetchRequiredApi's empty-body Error or a queryFn invariant — retrying just wastes
    // requests. Only genuine transport failures (TypeError) and explicit ask-again-later retry.
    expect(shouldRetryRequest(0, new Error('Request to X succeeded but returned an empty response body.'))).toBe(false);
  });

  it('does not retry a parse failure (a response was received)', () => {
    const err = new ResponseParseError({
      status: 200,
      endpoint: 'http://example.test/e',
      bodyPreview: 'oops',
      message: 'Request to http://example.test/e returned malformed JSON (200): x',
    });
    expect(shouldRetryRequest(0, err)).toBe(false);
  });

  it('never retries an aborted request, at any failure count', () => {
    const abort = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });
    expect(shouldRetryRequest(0, abort)).toBe(false);
    expect(shouldRetryRequest(1, abort)).toBe(false);
    // DOMException-shaped (not an Error subclass in the browser).
    expect(shouldRetryRequest(0, { name: 'AbortError', message: 'aborted' })).toBe(false);
  });

  // FEBT1-W2A-05 + FEBT1-LB-02. A timeout and a nonce refresh that never
  // reached a verdict are AMBIGUOUS outcomes (DDIA ch-8): the request may have
  // reached the server. shouldRetryRequest is wired only to React Query
  // queries — idempotent GETs — so exactly one repeat is safe, and the budget
  // is deliberately smaller than RETRY_MAX_ATTEMPTS. Expressed on literals so
  // widening AMBIGUOUS_RETRY_MAX_ATTEMPTS to 2 fails here.
  it('retries an ambiguous outcome exactly once, not RETRY_MAX_ATTEMPTS times', () => {
    expect(AMBIGUOUS_RETRY_MAX_ATTEMPTS).toBe(1);
    expect(AMBIGUOUS_RETRY_MAX_ATTEMPTS).toBeLessThan(RETRY_MAX_ATTEMPTS);

    const timeout = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
    expect(shouldRetryRequest(0, timeout)).toBe(true);
    expect(shouldRetryRequest(1, timeout)).toBe(false);
    expect(shouldRetryRequest(2, timeout)).toBe(false);
    expect(shouldRetryRequest(0, { name: 'TimeoutError', message: 'timed out' })).toBe(true);

    const nonceRefresh = new NonceRefreshFailedError({
      message: 'Nonce refresh did not reach a verdict.',
      causeStatus: 0,
      bodyPreview: '',
    });
    expect(classifyError(nonceRefresh)._tag).toBe('nonce_refresh');
    expect(shouldRetryRequest(0, nonceRefresh)).toBe(true);
    expect(shouldRetryRequest(1, nonceRefresh)).toBe(false);
  });

  it('an abort and a timeout are not the same decision [FEBT1-W2A-05]', () => {
    const abort = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });
    const timeout = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
    expect(shouldRetryRequest(0, abort)).not.toBe(shouldRetryRequest(0, timeout));
  });

  it('[FEBT1-W2C-13] pins the product bounds to literals so a constant change cannot pass silently', () => {
    expect(RETRY_MAX_ATTEMPTS).toBe(3);
    expect(MAX_RETRY_DELAY_MS).toBe(30_000);
  });

  it('is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class', () => {
    // Expressed on literals, not on the constant: raising RETRY_MAX_ATTEMPTS to 4 must fail here.
    expect(shouldRetryRequest(2, httpError(429))).toBe(true);
    expect(shouldRetryRequest(3, httpError(429))).toBe(false);
    expect(shouldRetryRequest(3, new TypeError('Failed to fetch'))).toBe(false);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS - 1, httpError(429))).toBe(true);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, httpError(429))).toBe(false);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, new TypeError('Failed to fetch'))).toBe(false);
  });
});

describe('getRetryDelay', () => {
  beforeEach(() => {
    vi.spyOn(Math, 'random').mockReturnValue(1);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('honors Retry-After (delta-seconds) for 429/503', () => {
    expect(getRetryDelay(0, httpError(429, 5))).toBe(5_000);
    expect(getRetryDelay(2, httpError(503, 10))).toBe(10_000);
  });

  // FEBT1-LB-01 + FEBT1-LE-03: strengthened, not relaxed. The old pin asserted
  // that `Retry-After: 0` retries immediately — that is exactly the aggressive
  // retry Release It! ch-5 names as an outage amplifier, and every client in
  // the fleet does it at the same instant. `Retry-After: 0` now carries no wait
  // instruction, so the caller falls through to its own *jittered* backoff.
  it('a Retry-After of 0 yields a non-zero, jittered delay — never an immediate retry', () => {
    const zeroWait = httpError(429, 0);

    expect(getRetryDelay(0, zeroWait)).toBeGreaterThanOrEqual(RETRY_AFTER_MIN_MS);

    // Jittered, not a fixed constant: two different rng draws must differ, so a
    // fix that merely returned RETRY_AFTER_MIN_MS unconditionally fails here.
    const low = getRetryDelay(3, zeroWait, () => 0.25);
    const high = getRetryDelay(3, zeroWait, () => 0.9);
    expect(low).not.toBe(high);
    expect(low).toBeGreaterThanOrEqual(RETRY_AFTER_MIN_MS);
    expect(high).toBeLessThanOrEqual(8_000);
  });

  it('falls back to bounded exponential backoff for transport failures', () => {
    expect(getRetryDelay(0, new TypeError('Failed to fetch'))).toBe(1_000);
    expect(getRetryDelay(1, new TypeError('Failed to fetch'))).toBe(2_000);
    expect(getRetryDelay(2, new TypeError('Failed to fetch'))).toBe(4_000);
  });

  it('caps exponential backoff at 30s', () => {
    expect(getRetryDelay(10, new TypeError('Failed to fetch'))).toBe(30_000);
  });

  it('uses backoff for a 429 without Retry-After', () => {
    expect(getRetryDelay(1, httpError(429))).toBe(2_000);
  });

  it('clamps a large Retry-After to the bounded ceiling (no hour-long freeze)', () => {
    // A misbehaving intermediary emitting Retry-After: 3600 must not freeze a poller for 1h.
    expect(getRetryDelay(0, httpError(429, 3600))).toBe(30_000);
  });

  it('clamps an overflow-scale Retry-After (guards the 32-bit setTimeout overflow → immediate retry)', () => {
    // delay > 2,147,483,647 ms overflows setTimeout and fires immediately → a hot loop.
    expect(getRetryDelay(0, httpError(503, 2_678_400))).toBe(30_000);
  });

  it('caps the exponential backoff branch at the same ceiling', () => {
    expect(getRetryDelay(20, new TypeError('Failed to fetch'))).toBe(30_000);
  });

  it('clamps Retry-After: 3600 through the shared ceiling at the retry-delay call site [E-01]', () => {
    expect(clampRetryAfterMs(3600, 1_000)).toBe(RETRY_AFTER_MAX_MS);
    expect(getRetryDelay(0, httpError(429, 3600))).toBe(MAX_RETRY_DELAY_MS);
    expect(getRetryDelay(0, httpError(429, 3600))).toBeLessThan(2 ** 31 - 1);
  });

  it('falls back off the Retry-After branch for negative/NaN/Infinity [E-01]', () => {
    expect(getRetryDelay(0, httpError(429, Number.NaN))).toBe(1_000);
    expect(getRetryDelay(0, httpError(429, Number.POSITIVE_INFINITY))).toBe(1_000);
    expect(getRetryDelay(0, httpError(429, -5))).toBe(1_000);
  });

  // FEBT1-LB-01: strengthened, not relaxed. `rng 0 → 0` was a *bug* pinned as a
  // property: full jitter over [0,1) reaches zero, and a zero-delay "backoff"
  // is an immediate retry against a fault that is still present. The upper half
  // of the jitter window is kept verbatim; the lower half now pins the floor.
  it('applies full jitter, floored: rng 0 → the floor, rng ~1 → full computed exponential [E-06]', () => {
    const transport = new TypeError('Failed to fetch');
    expect(getRetryDelay(0, transport, () => 0)).toBe(RETRY_AFTER_MIN_MS);
    expect(getRetryDelay(1, transport, () => 0)).toBe(RETRY_AFTER_MIN_MS);
    // Literal, not the constant: zeroing RETRY_AFTER_MIN_MS must fail here.
    expect(getRetryDelay(4, transport, () => 0)).toBe(1_000);
    expect(getRetryDelay(0, transport, () => 1)).toBe(1_000);
    expect(getRetryDelay(1, transport, () => 1)).toBe(2_000);
    expect(getRetryDelay(2, transport, () => 1)).toBe(4_000);
    // Still jitter, not a constant: the window between floor and ceiling is real.
    expect(getRetryDelay(4, transport, () => 0.5)).toBe(8_000);
  });

  it('no retry delay is ever zero, for any tag or rng draw [FEBT1-LB-01]', () => {
    const cases: unknown[] = [
      new TypeError('Failed to fetch'),
      httpError(429, 0),
      httpError(503, 0),
      httpError(429),
      Object.assign(new Error('timed out'), { name: 'TimeoutError' }),
    ];
    for (const error of cases) {
      for (const draw of [0, 0.0001, 0.5, 1]) {
        expect(getRetryDelay(0, error, () => draw)).toBeGreaterThanOrEqual(RETRY_AFTER_MIN_MS);
      }
    }
  });

  it('keeps the Retry-After branch byte-identical regardless of rng [E-06]', () => {
    const error = httpError(429, 5);
    expect(getRetryDelay(0, error, () => 0)).toBe(5_000);
    expect(getRetryDelay(0, error, () => 1)).toBe(5_000);
    expect(getRetryDelay(7, error, () => 0.25)).toBe(5_000);
  });
});

describe('classifier clauses after F3/F5 [TEST-15]', () => {
  it('plain-object abort is not retried (M14)', () => {
    expect(isAbortLike({ name: 'AbortError', message: 'aborted' })).toBe(true);
    expect(shouldRetryRequest(0, { name: 'AbortError', message: 'aborted' })).toBe(false);
    // FEBT1-W2A-05: `isAbortLike` keeps its published contract — cancellation-
    // shaped, abort *or* elapsed deadline — because useDescribeRunProgress
    // freezes the UI on both. The retry split lives in `isDeliberateAbort`, so
    // the ambiguous-outcome budget stays reachable for a timeout.
    expect(isAbortLike({ name: 'TimeoutError', message: 'timed out' })).toBe(true);
    expect(isDeliberateAbort({ name: 'AbortError', message: 'aborted' })).toBe(true);
    expect(isDeliberateAbort({ name: 'TimeoutError', message: 'timed out' })).toBe(false);
  });

  it('pre-classified transport AppError is retried (M15)', () => {
    const classified = classifyError(new TypeError('Failed to fetch'));
    expect(classified._tag).toBe('transport');
    expect(shouldRetryRequest(0, classified)).toBe(true);
  });

  it('isCooldownSignal: 429/503-with-Retry-After only, including pre-classified (M17)', () => {
    expect(isCooldownSignal(httpError(429))).toBe(true);
    // FEBT1-LE-03: strengthened. A 503 whose Retry-After names no wait is not
    // an "ask again later" — it carries no window to arm a cooldown with, and
    // treating it as one produced a zero-length cooldown that gated nothing.
    expect(isCooldownSignal(httpError(503, 0))).toBe(false);
    expect(isCooldownSignal(httpError(503, 5))).toBe(true);
    expect(isCooldownSignal(httpError(503))).toBe(false);
    expect(isCooldownSignal(httpError(500))).toBe(false);
    const classified = classifyError(httpError(429, 5));
    expect(classified._tag).toBe('http');
    if (classified._tag === 'http') {
      expect(classified.retryAfterMs).toBe(5_000);
    }
    expect(isCooldownSignal(classified)).toBe(true);
  });

  it('isCooldownSignal means "should open a cooldown", not instanceof HTTPError [W1-L1-09]', () => {
    const serverError = httpError(500, 9);
    expect(serverError).toBeInstanceOf(HTTPError);
    expect(isCooldownSignal(serverError)).toBe(false);

    const classified = classifyError(httpError(429, 5));
    expect(classified).not.toBeInstanceOf(HTTPError);
    expect(isCooldownSignal(classified)).toBe(true);

    const timeout = new DOMException('The operation timed out.', 'TimeoutError');
    expect(isCooldownSignal(timeout)).toBe(false);
  });
});
