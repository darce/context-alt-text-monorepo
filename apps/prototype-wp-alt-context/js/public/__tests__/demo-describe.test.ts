import { describe, expect, it, vi } from 'vitest';

import {
  POLL_TIMEOUT_MESSAGE,
  PublicDemoClientError,
  parsePublicDemoEnvelope,
  pollRun,
  statusPresentation,
} from '../demo-describe.js';

const running = (overrides: Record<string, unknown> = {}) => ({
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  gpu_state: 'ready',
  progress: { done: 0, total: 1 },
  ...overrides,
});

const response = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('public demo describe polling', () => {
  it('backs off exponentially and stops polling on a terminal response', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(response(running({ status: 'pending', phase: 'queued' })))
      .mockResolvedValueOnce(response(running()))
      .mockResolvedValueOnce(response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 }, description: 'A lakeside path.' })));
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
    const statuses = Array.from({ length: 7 }, () => response(running()));
    statuses.push(response(running({ status: 'failed', phase: 'failed', error: { code: 'acx_public_demo_pipeline_failed', message: 'The image could not be described.' } })));
    const fetchImpl = vi.fn<typeof fetch>();
    for (const item of statuses) {
      fetchImpl.mockResolvedValueOnce(item);
    }
    const waits: number[] = [];
    let clock = 0;

    await expect(pollRun({
      statusUrl: '/status/run-2',
      nonce: 'nonce',
      fetchImpl,
      now: () => clock,
      sleep: async (milliseconds: number) => {
        waits.push(milliseconds);
        clock += milliseconds;
      },
    })).rejects.toMatchObject({ code: 'acx_public_demo_pipeline_failed' });

    expect(waits).toEqual([500, 1_000, 2_000, 4_000, 5_000, 5_000, 5_000]);
  });

  it('hard-stops after the configured polling deadline with operator-friendly copy', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => response(running()));
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

  it.each([
    [],
    {},
    running({ status: 'surprise' }),
    running({ status: 'pending', phase: 'describing' }),
    running({ progress: { done: -1, total: 1 } }),
    running({ progress: { done: 2, total: 1 } }),
  ])('rejects malformed success envelopes immediately', async (payload) => {
    await expect(
      pollRun({ statusUrl: '/status/malformed', nonce: 'nonce', fetchImpl: vi.fn(async () => response(payload)) }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_invalid_response' });
  });

  it('requires a non-empty description for a completed run', async () => {
    await expect(
      pollRun({
        statusUrl: '/status/no-draft',
        nonce: 'nonce',
        fetchImpl: vi.fn(async () => response(running({ status: 'completed', phase: 'complete', progress: { done: 1, total: 1 } }))),
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_incomplete_result' });
  });

  it('treats completed_with_errors as a typed failure', async () => {
    await expect(
      pollRun({
        statusUrl: '/status/partial',
        nonce: 'nonce',
        fetchImpl: vi.fn(async () => response(running({
          status: 'completed_with_errors',
          phase: 'complete',
          progress: { done: 1, total: 1 },
          error: { code: 'acx_public_demo_partial_failure', message: 'The description did not complete successfully.' },
        }))),
      }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_partial_failure' });
  });

  it('aborts an in-flight fetch at the remaining deadline', async () => {
    const fetchImpl = vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
    }));

    await expect(
      pollRun({ statusUrl: '/status/hung', nonce: 'nonce', fetchImpl, timeoutMs: 10 }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_poll_timeout' });
    expect(fetchImpl.mock.calls[0]?.[1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it('aborts an in-flight fetch when navigation starts', async () => {
    const navigation = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>((_input, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), { once: true });
      navigation.abort();
    }));

    await expect(
      pollRun({ statusUrl: '/status/leaving', nonce: 'nonce', fetchImpl, navigationSignal: navigation.signal }),
    ).rejects.toMatchObject({ code: 'acx_public_demo_request_aborted' });
  });

  it('renders warming and describing phases honestly', () => {
    expect(statusPresentation(parsePublicDemoEnvelope(running({ phase: 'warming', gpu_state: 'starting' }))).message).toContain('warming up');
    expect(statusPresentation(parsePublicDemoEnvelope(running({ phase: 'describing', progress: { done: 1, total: 2 } }))).message).toContain('50%');
  });
});
