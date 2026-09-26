import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { DescribeRunItemsResponse, DescribeRunResponse } from '../api/describeApi';
import { AuthExpiredError, HTTPError } from '../utils/errorTaxonomy';
import { GUIDED_LIVE_STATUS } from './liveDescription';
import { useGuidedLiveDescription } from './useGuidedLiveDescription';
import type { GuidedLiveDescriptionClient } from './useGuidedLiveDescription';

const MEDIA_ID = 4211;

const runResponse = (over: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'demo',
  run_id: 'run-1',
  status: 'running',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 1,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: 'stopped',
  recognition_enabled: true,
  ...over,
});

const itemsResponse: DescribeRunItemsResponse = {
  run_id: 'run-1',
  items: [],
};

const stubClient = (
  over: Partial<GuidedLiveDescriptionClient> = {},
): GuidedLiveDescriptionClient => ({
  submit: vi.fn(() => Promise.resolve(runResponse())),
  poll: vi.fn(() => Promise.resolve(runResponse({ phase: 'warming' }))),
  items: vi.fn(() => Promise.resolve(itemsResponse)),
  cancel: vi.fn(() => Promise.resolve(undefined)),
  ...over,
});

const mount = (client: GuidedLiveDescriptionClient) =>
  renderHook(() => useGuidedLiveDescription({ mediaId: MEDIA_ID, client }));

const press = async (gesture: () => void) => {
  await act(async () => {
    gesture();
    await vi.advanceTimersByTimeAsync(0);
  });
};

const settle = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

const httpError = (status: number, retryAfterSeconds?: number) =>
  new HTTPError({
    status,
    retryAfterSeconds,
    endpoint: '/runs/run-1',
    bodyPreview: '',
    message: `HTTP ${status}`,
  });

describe('DEFWAVE-2 deferred findings', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('recomputes the deadline when the first poll discloses a server budget', async () => {
    const client = stubClient({
      poll: vi.fn(() =>
        Promise.resolve(
          runResponse({ phase: 'warming', gpu_state: 'stopped', deadline_seconds: 900 }),
        ),
      ),
    });
    const { result } = mount(client);

    await press(() => result.current.request());
    await settle(1000);

    expect(result.current.state.disclosedDeadlineSeconds).toBe(900);
    expect(result.current.state.deadlineMs).toBe(1_425_000);
  });

  it('starts only one submit when request is called twice before a render', async () => {
    const client = stubClient();
    const { result } = mount(client);

    await act(async () => {
      result.current.request();
      await Promise.resolve();
      result.current.request();
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(client.submit).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['transport loss', new TypeError('Failed to fetch')],
    ['auth expiry', new AuthExpiredError({ endpoint: '/runs/run-1', status: 403 })],
    ['429 cooldown', httpError(429)],
    ['503 cooldown', httpError(503, 30)],
    ['proxy 5xx', httpError(502)],
  ])('keeps the run while polling fails with %s', async (_label, error) => {
    const client = stubClient({ poll: vi.fn(() => Promise.reject(error)) });
    const { result } = mount(client);

    await press(() => result.current.request());
    await settle(1000);

    expect(client.poll).toHaveBeenCalled();
    expect(client.cancel).not.toHaveBeenCalled();
    expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.QUEUED);
  });

  it('cancels the run id disclosed in an ambiguous submit error', async () => {
    const error = Object.assign(new Error('Timed out: {"run_id":"run-stranded"}'), {
      name: 'TimeoutError',
    });
    const client = stubClient({ submit: vi.fn(() => Promise.reject(error)) });
    const { result } = mount(client);

    await press(() => result.current.request());

    expect(client.cancel).toHaveBeenCalledWith('run-stranded');
    expect(result.current.state.status).toBe(GUIDED_LIVE_STATUS.UNAVAILABLE);
  });
});
