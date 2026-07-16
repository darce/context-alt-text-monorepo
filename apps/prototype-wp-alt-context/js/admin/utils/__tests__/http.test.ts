import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  getQueryRetryDelay,
  QUERY_MAX_RETRIES,
  shouldRetryQuery,
} from '../../App';
import { fetchApi, fetchRequiredApi, HTTPError, parseRetryAfterSeconds } from '../http';

describe('fetchApi', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('returns undefined for 204 responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));

    const result = await fetchApi<void>('http://example.test/endpoint', { method: 'POST' });

    expect(result).toBeUndefined();
  });

  it('returns undefined for successful empty response bodies', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 200 }));

    const result = await fetchApi<void>('http://example.test/endpoint');

    expect(result).toBeUndefined();
  });

  it('surfaces endpoint and response preview for malformed JSON bodies', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"status":"ok"} trailing-debug-output', { status: 200 }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON request to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(Error);
      expect((error as Error).message).toMatch(
        /Request to http:\/\/example\.test\/endpoint returned malformed JSON \(200\):/,
      );
      expect((error as Error).message).toMatch(/Response preview:/);
    }
  });

  it('truncates long malformed JSON previews to 240 characters', async () => {
    const longTail = `{"status":"ok"} ${'x'.repeat(260)}`;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(longTail, { status: 200 }));

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON request to throw.');
    } catch (error) {
      expect((error as Error).message).toContain('Response preview:');
      expect((error as Error).message).toContain('...');
    }
  });

  it('includes parser syntax details in malformed JSON errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"status"', { status: 200 }));

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow(/Expected ':' after property name/i);
  });

  it('falls back to a generic parse message when parsing throws a non-Error value', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"status":"ok"}', { status: 200 }));
    vi.spyOn(JSON, 'parse').mockImplementation(() => {
      // Exercise the non-Error fallback branch in fetchApi.
      // eslint-disable-next-line @typescript-eslint/only-throw-error
      throw 'boom';
    });

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow('Unknown JSON parse error.');
  });

  it('throws the non-ok response body for fetchRequiredApi requests', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('backend unavailable', { status: 503 }));

    await expect(fetchRequiredApi('http://example.test/endpoint')).rejects.toThrow(
      'Request to http://example.test/endpoint failed (503): backend unavailable',
    );
  });
});

describe('fetchApi HTTPError', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('throws HTTPError with status and retryAfterSeconds', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('slow down', { status: 429, headers: { 'Retry-After': '7' } }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected non-ok response to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect(error).toBeInstanceOf(Error);
      expect((error as HTTPError).status).toBe(429);
      expect((error as HTTPError).retryAfterSeconds).toBe(7);
      expect((error as HTTPError).name).toBe('HTTPError');
    }
  });

  it('preserves the legacy message format for catch sites that read .message', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow(
      'Request to http://example.test/endpoint failed (404): not found',
    );
  });

  it('sets retryAfterSeconds to null when Retry-After is absent', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('overloaded', { status: 503 }));

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected non-ok response to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).status).toBe(503);
      expect((error as HTTPError).retryAfterSeconds).toBeNull();
    }
  });

  it('sets retryAfterSeconds to null when Retry-After is malformed', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('rate limited', { status: 429, headers: { 'Retry-After': 'soon' } }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected non-ok response to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect((error as HTTPError).retryAfterSeconds).toBeNull();
    }
  });

  it('lets AbortError pass through untouched (never wraps as HTTPError)', async () => {
    const abortError = new DOMException('The operation was aborted.', 'AbortError');
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(abortError);

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected AbortError to reject.');
    } catch (error) {
      expect(error).toBe(abortError);
      expect(error).not.toBeInstanceOf(HTTPError);
      expect((error as Error).name).toBe('AbortError');
    }
  });
});

describe('parseRetryAfterSeconds', () => {
  it('parses non-negative integer delta-seconds', () => {
    expect(parseRetryAfterSeconds('5')).toBe(5);
    expect(parseRetryAfterSeconds('0')).toBe(0);
    expect(parseRetryAfterSeconds('120')).toBe(120);
    expect(parseRetryAfterSeconds('  3  ')).toBe(3);
  });

  it('returns null for missing or malformed values', () => {
    expect(parseRetryAfterSeconds(null)).toBeNull();
    expect(parseRetryAfterSeconds('')).toBeNull();
    expect(parseRetryAfterSeconds('  ')).toBeNull();
    expect(parseRetryAfterSeconds('soon')).toBeNull();
    expect(parseRetryAfterSeconds('-3')).toBeNull();
    expect(parseRetryAfterSeconds('5.5')).toBeNull();
  });
});

describe('shouldRetryQuery', () => {
  const httpError = (status: number, retryAfterSeconds: number | null = null): HTTPError =>
    new HTTPError(`failed (${status})`, status, retryAfterSeconds);

  it('never retries unmodified 4xx except 429 (API-08)', () => {
    expect(shouldRetryQuery(0, httpError(400))).toBe(false);
    expect(shouldRetryQuery(0, httpError(401))).toBe(false);
    expect(shouldRetryQuery(0, httpError(403))).toBe(false);
    expect(shouldRetryQuery(0, httpError(404))).toBe(false);
    expect(shouldRetryQuery(0, httpError(409))).toBe(false);
    expect(shouldRetryQuery(0, httpError(429))).toBe(true);
  });

  it('retries 429 up to QUERY_MAX_RETRIES then stops', () => {
    expect(shouldRetryQuery(0, httpError(429, 2))).toBe(true);
    expect(shouldRetryQuery(QUERY_MAX_RETRIES - 1, httpError(429, 2))).toBe(true);
    expect(shouldRetryQuery(QUERY_MAX_RETRIES, httpError(429, 2))).toBe(false);
  });

  it('retries 5xx and network errors within the bound', () => {
    expect(shouldRetryQuery(0, httpError(500))).toBe(true);
    expect(shouldRetryQuery(0, httpError(502))).toBe(true);
    expect(shouldRetryQuery(0, httpError(503))).toBe(true);
    expect(shouldRetryQuery(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetryQuery(QUERY_MAX_RETRIES, httpError(500))).toBe(false);
    expect(shouldRetryQuery(QUERY_MAX_RETRIES, new TypeError('Failed to fetch'))).toBe(false);
  });

  it('never retries AbortError (timeout classification)', () => {
    const abort = new DOMException('aborted', 'AbortError');
    expect(shouldRetryQuery(0, abort)).toBe(false);
    const named = new Error('aborted');
    named.name = 'AbortError';
    expect(shouldRetryQuery(0, named)).toBe(false);
  });
});

describe('getQueryRetryDelay', () => {
  it('uses Retry-After seconds for 429 when present', () => {
    const error = new HTTPError('rate limited', 429, 5);
    expect(getQueryRetryDelay(0, error)).toBe(5000);
  });

  it('falls back to bounded exponential when Retry-After is null', () => {
    const error = new HTTPError('rate limited', 429, null);
    expect(getQueryRetryDelay(0, error)).toBe(1000);
    expect(getQueryRetryDelay(1, error)).toBe(2000);
    expect(getQueryRetryDelay(10, error)).toBe(30000);
  });

  it('uses bounded exponential for 5xx and network errors', () => {
    expect(getQueryRetryDelay(0, new HTTPError('boom', 500, null))).toBe(1000);
    expect(getQueryRetryDelay(2, new TypeError('Failed to fetch'))).toBe(4000);
  });
});
