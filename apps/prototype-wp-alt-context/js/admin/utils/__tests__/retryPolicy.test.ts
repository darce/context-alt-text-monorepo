import { describe, expect, it } from 'vitest';

import { HTTPError, ResponseParseError } from '../http';
import { getRetryDelay, RETRY_MAX_ATTEMPTS, shouldRetryRequest } from '../retryPolicy';

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

  it('retries a transport failure (native fetch rejection, no response)', () => {
    expect(shouldRetryRequest(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetryRequest(0, new Error('NetworkError when attempting to fetch resource'))).toBe(true);
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

  it('does not retry an aborted request (timeout signal / unmount)', () => {
    const abort = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });
    expect(shouldRetryRequest(0, abort)).toBe(false);
    // DOMException-shaped abort (not an Error subclass in the browser).
    const domAbort = { name: 'AbortError', message: 'aborted' };
    expect(shouldRetryRequest(0, domAbort)).toBe(false);
  });

  it('is bounded: stops once RETRY_MAX_ATTEMPTS is reached even for a retryable class', () => {
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS - 1, httpError(429))).toBe(true);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, httpError(429))).toBe(false);
    expect(shouldRetryRequest(RETRY_MAX_ATTEMPTS, new TypeError('Failed to fetch'))).toBe(false);
  });
});

describe('getRetryDelay', () => {
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
});
