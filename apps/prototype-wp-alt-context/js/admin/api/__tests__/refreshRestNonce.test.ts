import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getNonce,
  NONCE_REFRESH_TIMEOUT_MS,
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

  it('hung refresh aborts after NONCE_REFRESH_TIMEOUT_MS and releases the single-flight slot [RES-02][TEST-15]', async () => {
    vi.useFakeTimers();
    try {
      let aborted = false;
      const fetchMock = vi
        .spyOn(globalThis, 'fetch')
        .mockImplementationOnce(
          (_url, init?: RequestInit) =>
            new Promise<Response>((_resolve, reject) => {
              (init?.signal as AbortSignal | undefined)?.addEventListener('abort', () => {
                aborted = true;
                reject(new DOMException('The operation was aborted.', 'AbortError'));
              });
            }),
        )
        .mockResolvedValue(new Response('cafebabe01', { status: 200 }));

      const hung = refreshRestNonce();
      const rejection = expect(hung).rejects.toBeInstanceOf(NonceRefreshFailedError);
      // Discrimination: before the timeout fires the promise is still pending.
      await vi.advanceTimersByTimeAsync(NONCE_REFRESH_TIMEOUT_MS - 1);
      expect(aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      expect(aborted).toBe(true);
      await rejection;
      expect(getNonce()).toBe('stale-nonce-abcdef');

      // Slot released → a subsequent call issues a fresh fetch and succeeds.
      await expect(refreshRestNonce()).resolves.toBe('cafebabe01');
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(getNonce()).toBe('cafebabe01');
    } finally {
      vi.useRealTimers();
    }
  });

  it('setNonce mutates cached config so getConfig().nonce stays live', () => {
    setNonce('mutated1234');
    expect(getNonce()).toBe('mutated1234');
  });

  it('missing ajaxUrl fails SOFT: config stays usable, only refresh degrades (UXPNET2-BR-02) [TEST-15]', async () => {
    resetConfigCache();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const config = registerConfig({
      nonce: 'abc',
      ajaxUrl: '',
      endpoints: {},
    });
    expect(config.nonce).toBe('abc');
    expect(config.ajaxUrl).toBe('');
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('ajaxUrl'),
      expect.objectContaining({ requestId: expect.any(String) }),
    );
    expect(getNonce()).toBe('abc');

    const fetchMock = vi.spyOn(globalThis, 'fetch');
    await expect(refreshRestNonce()).rejects.toBeInstanceOf(NonceRefreshFailedError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('setNonce wpApiSettings mirror (UXP-NET-2 slice 4)', () => {
  beforeEach(() => {
    resetConfigCache();
    seedConfig();
  });

  afterEach(() => {
    delete window.wpApiSettings;
    resetConfigCache();
  });

  it('mirrors refreshed nonce into window.wpApiSettings when present [TEST-15]', () => {
    window.wpApiSettings = { root: 'https://example.test/wp-json/', nonce: 'stale-wp-api-nonce' };
    setNonce('deadbeef01');
    expect(window.wpApiSettings.nonce).toBe('deadbeef01');
    expect(getNonce()).toBe('deadbeef01');
  });

  it('mirrors into a present wpApiSettings even when its nonce is empty (UXPNET2-BR-06) [TEST-15]', () => {
    window.wpApiSettings = { root: 'https://example.test/wp-json/', nonce: '' };
    setNonce('deadbeef03');
    expect(window.wpApiSettings.nonce).toBe('deadbeef03');
  });

  it('does not create wpApiSettings when absent', () => {
    delete window.wpApiSettings;
    setNonce('deadbeef02');
    expect(window.wpApiSettings).toBeUndefined();
    expect(getNonce()).toBe('deadbeef02');
  });
});
