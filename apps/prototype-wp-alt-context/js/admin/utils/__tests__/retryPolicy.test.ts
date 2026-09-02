import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { classifyError } from '../appError';
import { AuthExpiredError, HTTPError, ResponseParseError } from '../http';
import { clampRetryAfterMs, RETRY_AFTER_MAX_MS } from '../retryAfter';
import {
  getRetryDelay,
  isAbortLike,
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

  it('retries every TypeError (F5 parity: previously instanceof TypeError)', () => {
    expect(classifyError(new TypeError('Failed to fetch'))._tag).toBe('transport');
    expect(classifyError(new TypeError('x is not a function'))._tag).toBe('transport');
    expect(shouldRetryRequest(0, new TypeError('x is not a function'))).toBe(true);
    expect(shouldRetryRequest(0, new TypeError('boom: Failed to fetch'))).toBe(true);
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

  it('does not retry an aborted OR timed-out request', () => {
    const abort = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });
    expect(shouldRetryRequest(0, abort)).toBe(false);
    // createRecognitionTimeoutSignal uses AbortSignal.timeout(), which aborts with a
    // 'TimeoutError' DOMException — NOT 'AbortError'. This is the real recognition timeout
    // path; retrying it here would reopen the storm the poller interval already covers.
    const timeout = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
    expect(shouldRetryRequest(0, timeout)).toBe(false);
    // DOMException-shaped (not an Error subclass in the browser).
    expect(shouldRetryRequest(0, { name: 'AbortError', message: 'aborted' })).toBe(false);
    expect(shouldRetryRequest(0, { name: 'TimeoutError', message: 'timed out' })).toBe(false);
  });

  it('is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class', () => {
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

  it('honors Retry-After: 0 (retry immediately)', () => {
    expect(getRetryDelay(0, httpError(429, 0))).toBe(0);
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

  it('applies full jitter: rng 0 → 0, rng ~1 → full computed exponential [E-06]', () => {
    const transport = new TypeError('Failed to fetch');
    expect(getRetryDelay(0, transport, () => 0)).toBe(0);
    expect(getRetryDelay(1, transport, () => 0)).toBe(0);
    expect(getRetryDelay(0, transport, () => 1)).toBe(1_000);
    expect(getRetryDelay(1, transport, () => 1)).toBe(2_000);
    expect(getRetryDelay(2, transport, () => 1)).toBe(4_000);
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
    expect(shouldRetryRequest(0, { name: 'TimeoutError', message: 'timed out' })).toBe(false);
  });

  it('pre-classified transport AppError is retried (M15)', () => {
    const classified = classifyError(new TypeError('Failed to fetch'));
    expect(classified._tag).toBe('transport');
    expect(shouldRetryRequest(0, classified)).toBe(true);
  });

  it('isCooldownSignal: 429/503-with-Retry-After only, including pre-classified (M17)', () => {
    expect(isCooldownSignal(httpError(429))).toBe(true);
    expect(isCooldownSignal(httpError(503, 0))).toBe(true);
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
