import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPortalKeyClient, type PortalKeyPageResponse } from '../api/portalKeys';
import { createPortalRequest } from '../api/portalRequest';
import { createPortalUsageClient, type PortalUsageResponse } from '../api/portalUsage';

const OWNER_A = { userId: 'user_a', sessionId: 'sess_a' };
const OWNER_B = { userId: 'user_b', sessionId: 'sess_b' };
const TENANT_A = '11111111-1111-4111-8111-111111111111';
const KEY_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const STALL_WAIT_MS = 250;

afterEach(() => {
  vi.useRealTimers();
});

function usage(overrides: Partial<PortalUsageResponse> = {}): PortalUsageResponse {
  return {
    tenant_id: TENANT_A,
    used: 3,
    reserved: 1,
    remaining: 6,
    allowance: 10,
    period_start: '2026-09-01T00:00:00Z',
    period_end: '2026-10-01T00:00:00Z',
    period: { start: '2026-09-01T00:00:00Z', end: '2026-10-01T00:00:00Z' },
    as_of: '2026-09-22T12:00:00Z',
    status: 'beta_active',
    data_source: 'authoritative',
    ...overrides,
  };
}

function keyPage(): PortalKeyPageResponse {
  return {
    data: [
      {
        id: KEY_A,
        tenant_id: TENANT_A,
        created_at: '2026-09-01T00:00:00Z',
        expires_at: '2026-12-01T00:00:00Z',
        revoked_at: null,
        rate_limit_tier: 'standard',
        lifetime_seconds: 3600,
      },
    ],
    next_cursor: null,
    cursor: null,
    limit: 25,
    total: 1,
  };
}

function streamedJsonResponse(body: unknown): Response {
  const bytes = new TextEncoder().encode(JSON.stringify(body));
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes);
        controller.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function stalledJsonResponse(onCancel?: () => void): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start() {
        /* headers resolved; body never enqueued */
      },
      cancel() {
        onCancel?.();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

function gatedJsonResponse(body: unknown, gate: { release?: () => void }): Response {
  const bytes = new TextEncoder().encode(JSON.stringify(body));
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        gate.release = () => {
          controller.enqueue(bytes);
          controller.close();
        };
      },
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  );
}

async function expectDidNotHang(pending: Promise<unknown>, message: string): Promise<void> {
  const hung = await Promise.race([
    pending.then(
      () => false,
      () => false,
    ),
    new Promise<boolean>((resolve) => {
      window.setTimeout(() => resolve(true), STALL_WAIT_MS);
    }),
  ]);
  if (hung) {
    throw new Error(message);
  }
}

describe('APP-1 integration transport fix wave [RES-02][RLSE-04][DATA-03]', () => {
  it('bounds a headers-resolved body-stalled stream with the total deadline [RES-02]', async () => {
    const fetchImpl = vi.fn(async () => stalledJsonResponse());
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });
    const pending = createPortalUsageClient(request).read();

    await expectDidNotHang(pending, 'headers-resolved body-stalled stream was not deadline-bounded');
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('parses a successful streamed body through the usage client after headers resolve [RES-02]', async () => {
    const gate: { release?: () => void } = {};
    const fetchImpl = vi.fn(async () => gatedJsonResponse(usage(), gate));
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 8_000,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });
    const pending = createPortalUsageClient(request).read();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    expect(gate.release).toEqual(expect.any(Function));
    gate.release?.();
    await expect(pending).resolves.toEqual(usage());
  });

  it('cancels a streamed response when accumulated bytes exceed the limit [RES-05]', async () => {
    let cancelled = 0;
    const fetchImpl = vi.fn(async () =>
      new Response(
        new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(new Uint8Array(2 * 1024 * 1024));
            controller.enqueue(new Uint8Array(1));
          },
          cancel() {
            cancelled += 1;
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 8_000,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });

    await expect(request('/portal/usage')).rejects.toThrow('portal response exceeds maximum size');
    expect(cancelled).toBeGreaterThan(0);
  });

  it('cancels a stalled body when the owner abort signal fires [RES-02]', async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(async () => stalledJsonResponse());
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 8_000,
      signal: controller.signal,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });
    const pending = createPortalUsageClient(request).read();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    controller.abort();

    await expectDidNotHang(pending, 'stalled body was not cancelled by owner abort');
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('drops a streamed body after session replacement [DDIA][DATA-03]', async () => {
    let current = OWNER_A;
    const gate: { release?: () => void } = {};
    const fetchImpl = vi.fn(async () => gatedJsonResponse(usage(), gate));
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 8_000,
      owner: OWNER_A,
      currentOwner: () => current,
    });
    const pending = createPortalUsageClient(request).read();
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    current = OWNER_B;
    gate.release?.();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('cancels the stalled body reader and clears the deadline [RES-02][RLSE-04]', async () => {
    let cancelled = 0;
    const clearTimeoutSpy = vi.spyOn(window, 'clearTimeout');
    const fetchImpl = vi.fn(async () =>
      stalledJsonResponse(() => {
        cancelled += 1;
      }),
    );
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });
    const pending = createPortalUsageClient(request).read();

    await expectDidNotHang(pending, 'stalled body reader was not cancelled by the total deadline');
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(cancelled).toBeGreaterThan(0);
    expect(clearTimeoutSpy).toHaveBeenCalled();
  });

  it('isolates a stalled usage read from a successful streamed keys list [RES-02][DATA-03]', async () => {
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.startsWith('/portal/usage')) {
        return stalledJsonResponse();
      }
      if (path.startsWith('/portal/keys')) {
        return streamedJsonResponse(keyPage());
      }
      throw new Error(`unexpected path ${path}`);
    });
    const request = createPortalRequest({
      getToken: async () => 'session-jwt',
      fetchImpl: fetchImpl as unknown as typeof fetch,
      timeoutMs: 40,
      owner: OWNER_A,
      currentOwner: () => OWNER_A,
    });
    const usagePending = createPortalUsageClient(request).read();
    const keysPending = createPortalKeyClient(request).list();

    await expect(keysPending).resolves.toEqual(keyPage());
    await expectDidNotHang(usagePending, 'stalled usage read leaked into sibling isolation');
    await expect(usagePending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
