import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchApi, fetchRequiredApi } from '../http';

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
