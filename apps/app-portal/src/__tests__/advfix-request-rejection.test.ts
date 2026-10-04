import { afterEach, describe, expect, it, vi } from 'vitest';
import { createPortalKeyClient } from '../api/portalKeys';
import { createPortalRequest } from '../api/portalRequest';
import { createPortalUsageClient } from '../api/portalUsage';

const OWNER = { userId: 'user_a', sessionId: 'sess_a' };

function makeRequest(
  options: Partial<Parameters<typeof createPortalRequest>[0]> = {},
): ReturnType<typeof createPortalRequest> {
  return createPortalRequest({
    getToken: async () => 'session-jwt',
    fetchImpl: vi.fn(async () => new Response('{}')) as unknown as typeof fetch,
    timeoutMs: 8_000,
    owner: OWNER,
    currentOwner: () => OWNER,
    ...options,
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe('portal client request rejection normalization', () => {
  it('normalizes transport rejections for key listing and usage reads', async () => {
    const request = makeRequest({
      fetchImpl: vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }) as unknown as typeof fetch,
    });

    await expect(createPortalKeyClient(request).list()).rejects.toMatchObject({
      status: 0,
      code: 'portal_transport_error',
      detail: null,
      attemptId: null,
      retryAfterSeconds: null,
      message: 'portal_request_failed',
    });
    await expect(createPortalUsageClient(request).read()).rejects.toMatchObject({
      status: 0,
      code: 'portal_transport_error',
      detail: null,
      attemptId: null,
      retryAfterSeconds: null,
      message: 'portal_request_failed',
    });
  });

  it('normalizes token and oversized response rejections', async () => {
    const tokenFailure = makeRequest({
      getToken: async () => {
        throw new TypeError('token provider failed');
      },
    });
    await expect(createPortalUsageClient(tokenFailure).read()).rejects.toMatchObject({
      status: 0,
      code: 'portal_transport_error',
      attemptId: null,
      retryAfterSeconds: null,
    });

    const oversizedResponse = makeRequest({
      fetchImpl: vi.fn(async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new Uint8Array(2 * 1024 * 1024 + 1));
              controller.close();
            },
          }),
        ),
      ) as unknown as typeof fetch,
    });
    await expect(createPortalKeyClient(oversizedResponse).list()).rejects.toMatchObject({
      status: 0,
      code: 'portal_transport_error',
      attemptId: null,
      retryAfterSeconds: null,
    });
  });

  it('keeps cancellation identifiable while adding the client error fields', async () => {
    vi.useFakeTimers();
    const request = makeRequest({
      timeoutMs: 1,
      fetchImpl: vi.fn(() => new Promise<Response>(() => undefined)) as unknown as typeof fetch,
    });

    const pending = createPortalUsageClient(request).read();
    await vi.advanceTimersByTimeAsync(1);
    await expect(pending).rejects.toMatchObject({
      name: 'AbortError',
      status: 0,
      code: 'request_aborted',
      detail: null,
      attemptId: null,
      retryAfterSeconds: null,
    });
  });
});
