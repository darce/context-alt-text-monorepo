import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchPortalMe, PortalMeOutcome, PORTAL_ME_PATH } from '../api/portalMe';

const TENANT_ID = '11111111-1111-4111-8111-111111111111';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe('fetchPortalMe token deadline and cache [RES-02][RLSE-04][DATA-03]', () => {
  it('returns outage when getToken rejects and never calls fetch', async () => {
    const fetchImpl = vi.fn();
    const result = await fetchPortalMe({
      getToken: async () => {
        throw new Error('token refresh failed');
      },
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 1_000,
    });

    expect(result).toEqual({ outcome: PortalMeOutcome.Outage });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('bounds a never-resolving getToken with the same deadline as fetch', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn();
    const pending = fetchPortalMe({
      getToken: () => new Promise<string | null>(() => undefined),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
    });

    await vi.advanceTimersByTimeAsync(40);
    await expect(pending).resolves.toEqual({ outcome: PortalMeOutcome.Outage });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('returns aborted when the caller cancels during getToken', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn();
    const pending = fetchPortalMe({
      getToken: () => new Promise<string | null>(() => undefined),
      fetchImpl: fetchImpl as unknown as typeof fetch,
      signal: controller.signal,
      timeoutMs: 8_000,
    });
    controller.abort();

    await expect(pending).resolves.toEqual({ outcome: PortalMeOutcome.Aborted });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('sends cache no-store on GET /portal/me', async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(String(input)).toBe(PORTAL_ME_PATH);
      expect(init?.cache).toBe('no-store');
      expect(init?.method ?? 'GET').toBe('GET');
      expect(init?.credentials).toBe('omit');
      return jsonResponse(200, {
        tenant_id: TENANT_ID,
        issuer: 'https://clerk.altcontext.com',
        subject: 'user_1',
        email: 'ada@example.test',
      });
    });

    const result = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });

    expect(result).toEqual({ outcome: PortalMeOutcome.Ok, tenantId: TENANT_ID });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('maps 403 to not_admitted and a malformed 200 to outage, never empty', async () => {
    const denied = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: vi.fn(async () => jsonResponse(403, { detail: 'portal access denied' })) as unknown as typeof fetch,
    });
    expect(denied).toEqual({ outcome: PortalMeOutcome.NotAdmitted });

    const malformed = await fetchPortalMe({
      getToken: async () => 'session-jwt',
      fetchImpl: vi.fn(async () =>
        jsonResponse(200, {
          issuer: 'https://clerk.altcontext.com',
          subject: 'user_1',
          email: 'ada@example.test',
        }),
      ) as unknown as typeof fetch,
    });
    expect(malformed).toEqual({ outcome: PortalMeOutcome.Outage });
    expect(malformed.outcome).not.toBe(PortalMeOutcome.Empty);
  });
});
