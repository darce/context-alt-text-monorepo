import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchApi, fetchRequiredApi, HTTPError, parseRetryAfter, ResponseParseError } from '../http';

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

  it('throws a typed HTTPError carrying status and endpoint on a non-ok response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not found', { status: 404 }));

    try {
      await fetchApi('http://example.test/media/40412');
      throw new Error('Expected a non-ok response to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(HTTPError);
      expect(error).toBeInstanceOf(Error);
      expect((error as HTTPError).status).toBe(404);
      expect((error as HTTPError).endpoint).toBe('http://example.test/media/40412');
    }
  });

  it('preserves the legacy message format so downstream (404)/(409) message sniffs keep working', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('missing', { status: 404 }));

    await expect(fetchApi('http://example.test/endpoint')).rejects.toThrow(
      'Request to http://example.test/endpoint failed (404): missing',
    );
  });

  it('parses Retry-After (delta-seconds) into retryAfterSeconds', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('slow down', { status: 429, headers: { 'Retry-After': '5' } }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected a 429 to throw.');
    } catch (error) {
      expect((error as HTTPError).status).toBe(429);
      expect((error as HTTPError).retryAfterSeconds).toBe(5);
    }
  });

  it('leaves retryAfterSeconds undefined for a 503 without a Retry-After header', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('overloaded', { status: 503 }));

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected a 503 to throw.');
    } catch (error) {
      expect((error as HTTPError).status).toBe(503);
      expect((error as HTTPError).retryAfterSeconds).toBeUndefined();
    }
  });

  it('throws a ResponseParseError (not an HTTPError) for malformed JSON on a 2xx', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"status":"ok"} trailing-debug-output', { status: 200 }),
    );

    try {
      await fetchApi('http://example.test/endpoint');
      throw new Error('Expected malformed JSON to throw.');
    } catch (error) {
      expect(error).toBeInstanceOf(ResponseParseError);
      expect(error).toBeInstanceOf(Error);
      expect(error).not.toBeInstanceOf(HTTPError);
    }
  });
});

describe('parseRetryAfter', () => {
  it('parses non-negative delta-seconds', () => {
    expect(parseRetryAfter('5')).toBe(5);
    expect(parseRetryAfter('0')).toBe(0);
    expect(parseRetryAfter('120')).toBe(120);
  });

  it('returns undefined for missing or malformed values (never NaN)', () => {
    expect(parseRetryAfter(null)).toBeUndefined();
    expect(parseRetryAfter('')).toBeUndefined();
    expect(parseRetryAfter('  ')).toBeUndefined();
    expect(parseRetryAfter('soon')).toBeUndefined();
    expect(parseRetryAfter('-3')).toBeUndefined();
    expect(parseRetryAfter('5.5')).toBeUndefined();
  });
});
