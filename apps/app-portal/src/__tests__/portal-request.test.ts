import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPortalRequest } from '../api/portalRequest';

const OWNER_A = { userId: 'user_a', sessionId: 'sess_a' };
const OWNER_B = { userId: 'user_b', sessionId: 'sess_b' };

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe('createPortalRequest bounded bearer transport [RES-02][RLSE-04][DATA-03]', () => {
  it('bounds a hanging getToken with the total deadline and never calls fetch [RES-02]', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn();
    const request = createPortalRequest({
      getToken: () => new Promise<string | null>(() => undefined),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    const pending = expect(request('/portal/usage')).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(40);
    await pending;
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('bounds a hanging fetch with the same total deadline [RES-02]', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(() => new Promise<Response>(() => undefined));
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    const pending = expect(request('/portal/usage')).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(40);
    await pending;
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('aborts during getToken without sending a bearer request [RES-02]', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn();
    const request = createPortalRequest({
      getToken: () => new Promise<string | null>(() => undefined),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 8_000,
      signal: controller.signal,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    const pending = expect(request('/portal/me')).rejects.toMatchObject({ name: 'AbortError' });
    controller.abort();
    await pending;
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('does not fetch when getToken rejects [RLSE-04]', async () => {
    const fetchImpl = vi.fn();
    const request = createPortalRequest({
      getToken: async () => {
        throw new Error('token refresh failed');
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 1_000,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    await expect(request('/portal/me')).rejects.toThrow(/token refresh failed|portal identity/i);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('forces cache no-store, omits credentials, and never sets Origin [DATA-03]', async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe('/portal/usage');
      expect(init?.cache).toBe('no-store');
      expect(init?.credentials).toBe('omit');
      const headers = new Headers(init?.headers);
      expect(headers.get('Authorization')).toBe('Bearer session-jwt');
      expect([...headers.keys()].some((key) => key.toLowerCase() === 'origin')).toBe(false);
      return jsonResponse(200, { ok: true });
    });

    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    await expect(
      request('/portal/usage', { method: 'GET', headers: { Origin: 'https://evil.example' } }),
    ).resolves.toBeInstanceOf(Response);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('rejects external, protocol-relative, and non-allowlisted paths before getToken [DATA-03]', async () => {
    const getToken = vi.fn(async () => 'session-jwt');
    const fetchImpl = vi.fn();
    const request = createPortalRequest({
      getToken,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    const rejected = [
      'https://evil.example/portal/me',
      'http://app.altcontext.com/portal/me',
      '//evil.example/portal/me',
      '/api/portal/me',
      '/portal',
      'portal/me',
      '/portal/../keys',
      '/portal/%2e%2e/keys',
      'https://app.altcontext.com/portal/me',
    ];

    for (const path of rejected) {
      await expect(request(path)).rejects.toThrow(/not allowed|portal request/i);
    }
    expect(getToken).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('allows same-origin relative /portal/ paths including key list query [DATA-03]', async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe('/portal/keys?limit=25');
      expect(String(input)).not.toMatch(/^https?:/i);
      return jsonResponse(200, { data: [] });
    });
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    await request('/portal/keys?limit=25');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('does not send when the captured owner is no longer current [DDIA][DATA-03]', async () => {
    const getToken = vi.fn(async () => 'session-jwt');
    const fetchImpl = vi.fn();
    const request = createPortalRequest({
      getToken,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      owner: OWNER_A,
      currentOwner: () => OWNER_B,
    });

    await expect(request('/portal/usage')).rejects.toMatchObject({ name: 'AbortError' });
    expect(getToken).not.toHaveBeenCalled();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('drops a completed response after a session replacement [DDIA][DATA-03]', async () => {
    let current = OWNER_A;
    const fetchImpl = vi.fn(async () => {
      current = OWNER_B;
      return jsonResponse(200, { tenant_id: '11111111-1111-4111-8111-111111111111' });
    });
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      owner: OWNER_A,
      currentOwner: () => current,
    });

    await expect(request('/portal/me')).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
