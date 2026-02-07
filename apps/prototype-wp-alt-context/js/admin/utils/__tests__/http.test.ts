import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchApi } from '../http';

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
});

