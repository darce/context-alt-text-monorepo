import { describe, expect, it, vi } from 'vitest';

import { POLL_TIMEOUT_MESSAGE, PublicDemoClientError, pollRun } from '../demo-describe.js';

const response = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('public demo describe polling', () => {
  it('backs off exponentially and stops polling on a terminal response', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response({ status: 'pending' }))
      .mockResolvedValueOnce(response({ status: 'running' }))
      .mockResolvedValueOnce(response({ status: 'completed', description: 'A lakeside path.' }));
    const waits: number[] = [];
    let clock = 0;

    const result = await pollRun({
      statusUrl: '/status/run-1',
      nonce: 'nonce',
      fetchImpl,
      now: () => clock,
      sleep: async (milliseconds: number) => {
        waits.push(milliseconds);
        clock += milliseconds;
      },
    });

    expect(waits).toEqual([500, 1_000]);
    expect(result.status).toBe('completed');
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it('caps polling intervals at five seconds', async () => {
    const statuses = Array.from({ length: 7 }, () => response({ status: 'running' }));
    statuses.push(response({ status: 'failed' }));
    const fetchImpl = vi.fn<typeof fetch>();
    for (const item of statuses) {
      fetchImpl.mockResolvedValueOnce(item);
    }
    const waits: number[] = [];
    let clock = 0;

    await pollRun({
      statusUrl: '/status/run-2',
      nonce: 'nonce',
      fetchImpl,
      now: () => clock,
      sleep: async (milliseconds: number) => {
        waits.push(milliseconds);
        clock += milliseconds;
      },
    });

    expect(waits).toEqual([500, 1_000, 2_000, 4_000, 5_000, 5_000, 5_000]);
  });

  it('hard-stops after the configured polling deadline with operator-friendly copy', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => response({ status: 'running' }));
    let clock = 0;

    await expect(
      pollRun({
        statusUrl: '/status/run-3',
        nonce: 'nonce',
        fetchImpl,
        timeoutMs: 1_200,
        now: () => clock,
        sleep: async (milliseconds: number) => {
          clock += milliseconds;
        },
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout', message: POLL_TIMEOUT_MESSAGE });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it('reports a deadline breach before an invalid response that arrives too late', async () => {
    let clock = 0;
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => {
      clock = 1_200;
      return response(null);
    });

    await expect(
      pollRun({
        statusUrl: '/status/run-too-late',
        nonce: 'nonce',
        fetchImpl,
        timeoutMs: 1_200,
        now: () => clock,
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout', message: POLL_TIMEOUT_MESSAGE });
  });

  it('surfaces typed REST errors instead of polling again', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValue(response({ code: 'acx_public_demo_busy', message: 'Another run is active.' }, 429));

    await expect(
      pollRun({ statusUrl: '/status/run-4', nonce: 'nonce', fetchImpl }),
    ).rejects.toEqual(new PublicDemoClientError('acx_public_demo_busy', 'Another run is active.', 429));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
