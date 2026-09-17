import { createElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_STATE } from '../../api/describeApi';
import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../api/gpuApi';
import * as gpuApi from '../../api/gpuApi';
import {
  getGpuServiceStatusPollInterval,
  GPU_SERVICE_STATUS_ERROR_BACKOFF_MS,
  GPU_SERVICE_STATUS_POLL_INTERVAL_MS,
  GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
  useGpuServiceStatus,
} from '../useGpuServiceStatus';

vi.mock('../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return { ...actual, fetchGpuStatus: vi.fn() };
});

const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);

type StatusResponseOverrides = Partial<Omit<GpuStatusResponse, 'gpu_state' | 'load'>> & {
  gpu_state?: Partial<GpuStatusResponse['gpu_state']>;
  load?: Partial<GpuStatusResponse['load']>;
};

const statusResponse = ({
  gpu_state: gpuStateOverrides = {},
  load: loadOverrides = {},
  ...overrides
}: StatusResponseOverrides = {}): GpuStatusResponse => ({
  gpu_state: {
    state: GPU_STATE.STOPPED,
    instance_id: null,
    written_at: 1_700_000_000,
    reason: null,
    since: null,
    intent: GPU_INTENT_ACTION.AUTO,
    intent_expires_at: null,
    intent_status: GPU_INTENT_STATUS.NONE,
    honoured_nonce: null,
    lease_expires_at: null,
    instance_running_since: null,
    last_transition_reason: 'unknown',
    ...gpuStateOverrides,
  },
  snapshot_age_seconds: 12,
  snapshot_fresh: true,
  intent: null,
  load: { has_work: false, written_at: 1_700_000_004, fresh: true, ...loadOverrides },
  server_time: '2026-09-07T12:00:00Z',
  ...overrides,
});

let queryClient: QueryClient;

const createWrapper = () => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return wrapper;
};

describe('useGpuServiceStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchGpuStatusMock.mockResolvedValue(statusResponse());
  });

  afterEach(async () => {
    await queryClient?.cancelQueries();
    queryClient?.clear();
    cleanup();
  });

  it('uses the Settings cadence and backs off after a failed poll', () => {
    expect(getGpuServiceStatusPollInterval(undefined)).toBe(GPU_SERVICE_STATUS_POLL_INTERVAL_MS);
    expect(getGpuServiceStatusPollInterval(statusResponse())).toBe(GPU_SERVICE_STATUS_POLL_INTERVAL_MS);
    expect(getGpuServiceStatusPollInterval(statusResponse({ gpu_state: { state: GPU_STATE.STARTING } }))).toBe(
      GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
    );
    expect(getGpuServiceStatusPollInterval(statusResponse({ gpu_state: { state: GPU_STATE.WARMING } }))).toBe(
      GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
    );
    expect(getGpuServiceStatusPollInterval(statusResponse(), true)).toBe(GPU_SERVICE_STATUS_ERROR_BACKOFF_MS);
  });

  it('polls fetchGpuStatus while idle', async () => {
    const { result } = renderHook(() => useGpuServiceStatus({ isRunPending: false }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(result.current.gpuState).toBe(GPU_STATE.STOPPED));
    expect(result.current.isPolling).toBe(true);
    expect(result.current.snapshotFresh).toBe(true);
  });

  it('pauses polling while a run is pending and resumes after terminal status', async () => {
    const { rerender, result } = renderHook(
      ({ isRunPending }: { isRunPending: boolean }) => useGpuServiceStatus({ isRunPending }),
      { wrapper: createWrapper(), initialProps: { isRunPending: false } },
    );

    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1));
    expect(result.current.isPolling).toBe(true);

    rerender({ isRunPending: true });
    await waitFor(() => expect(result.current.isPolling).toBe(false));
    expect(fetchGpuStatusMock).toHaveBeenCalledTimes(1);

    rerender({ isRunPending: false });
    await waitFor(() => expect(fetchGpuStatusMock).toHaveBeenCalledTimes(2));
    expect(result.current.isPolling).toBe(true);
  });

  it('does not start idle polls while a run is already pending', async () => {
    const { result } = renderHook(() => useGpuServiceStatus({ isRunPending: true }), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isPolling).toBe(false));
    expect(fetchGpuStatusMock).not.toHaveBeenCalled();
  });
});
