import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getNonce,
  NonceRefreshFailedError,
  refreshRestNonce,
  registerConfig,
  resetConfigCache,
  setNonce,
} from '../config';

const AJAX_URL = 'https://example.test/wp-admin/admin-ajax.php';

const seedConfig = (nonce = 'stale-nonce-abcdef'): void => {
  registerConfig({
    nonce,
    ajaxUrl: AJAX_URL,
    endpoints: {},
  });
};

describe('refreshRestNonce (UXP-NET-2 slice 1)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    resetConfigCache();
  });

  it('raw-string success sets live nonce via setNonce/getNonce [TEST-15]', async () => {
    const fresh = 'a1b2c3d4e5';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(fresh, { status: 200 }));

    const result = await refreshRestNonce();

    expect(result).toBe(fresh);
    expect(getNonce()).toBe(fresh);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`${AJAX_URL}?action=rest-nonce`);
    expect(init.method).toBe('GET');
    expect(init.credentials).toBe('same-origin');
  });

  it('N concurrent callers share one network call (single-flight) [RES-06]', async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const p1 = refreshRestNonce();
    const p2 = refreshRestNonce();
    const p3 = refreshRestNonce();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveFetch(new Response('f00ba12abc', { status: 200 }));
    await expect(Promise.all([p1, p2, p3])).resolves.toEqual([
      'f00ba12abc',
      'f00ba12abc',
      'f00ba12abc',
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(getNonce()).toBe('f00ba12abc');
  });

  it("logged-out '0'/400 fixture → NonceRefreshFailedError", async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('0', { status: 400 }));

    await expect(refreshRestNonce()).rejects.toBeInstanceOf(NonceRefreshFailedError);
    expect(getNonce()).toBe('stale-nonce-abcdef');
  });

  it('malformed HTML body → NonceRefreshFailedError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('<html>login</html>', { status: 200 }),
    );

    await expect(refreshRestNonce()).rejects.toBeInstanceOf(NonceRefreshFailedError);
  });

  it('empty body → NonceRefreshFailedError', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 200 }));

    await expect(refreshRestNonce()).rejects.toBeInstanceOf(NonceRefreshFailedError);
  });

  it('reject-then-retry issues a second ajax call (no poisoned slot) [RES-06]', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('0', { status: 400 }))
      .mockResolvedValueOnce(new Response('deadbeef01', { status: 200 }));

    await expect(refreshRestNonce()).rejects.toBeInstanceOf(NonceRefreshFailedError);
    await expect(refreshRestNonce()).resolves.toBe('deadbeef01');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(getNonce()).toBe('deadbeef01');
  });

  it('setNonce mutates cached config so getConfig().nonce stays live', () => {
    setNonce('mutated1234');
    expect(getNonce()).toBe('mutated1234');
  });

  it('normalizeConfig rejects missing/empty ajaxUrl (sr-005)', () => {
    resetConfigCache();
    expect(() =>
      registerConfig({
        nonce: 'abc',
        ajaxUrl: '',
        endpoints: {},
      }),
    ).toThrow(/ajaxUrl/);
    expect(() =>
      registerConfig({
        nonce: 'abc',
        endpoints: {},
      } as { nonce: string; endpoints: Record<string, string> } as Parameters<typeof registerConfig>[0]),
    ).toThrow(/ajaxUrl/);
  });
});
