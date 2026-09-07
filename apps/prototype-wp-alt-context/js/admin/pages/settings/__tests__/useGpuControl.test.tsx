import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  GPU_INTENT_ACTION,
  GPU_INTENT_STATUS,
  type GpuStatusResponse,
} from '../../../api/gpuApi';
import * as gpuApi from '../../../api/gpuApi';
import {
  GPU_WARMUP_POLL_INTERVAL_MS,
  GPU_STATUS_POLL_INTERVAL_MS,
  getGpuControlPollInterval,
  useGpuControl,
} from '../useGpuControl';

vi.mock('../../../api/gpuApi', async (importOriginal) => {
  const actual = await importOriginal<typeof gpuApi>();
  return {
    ...actual,
    fetchGpuStatus: vi.fn(),
    postGpuIntent: vi.fn(),
  };
});

const fetchGpuStatusMock = vi.mocked(gpuApi.fetchGpuStatus);
const postGpuIntentMock = vi.mocked(gpuApi.postGpuIntent);

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
    state: 'stopped',
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

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useGpuControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('uses a 15 second poll normally and a 5 second poll while starting or warming', () => {
    expect(getGpuControlPollInterval(undefined)).toBe(GPU_STATUS_POLL_INTERVAL_MS);
    expect(getGpuControlPollInterval(statusResponse())).toBe(GPU_STATUS_POLL_INTERVAL_MS);
    expect(getGpuControlPollInterval(statusResponse({ state: 'starting' }))).toBe(
      GPU_WARMUP_POLL_INTERVAL_MS,
    );
    expect(getGpuControlPollInterval(statusResponse({ state: 'warming' }))).toBe(
      GPU_WARMUP_POLL_INTERVAL_MS,
    );
  });

  it('derives start from the stopped zero state and keeps stop disabled', async () => {
    fetchGpuStatusMock.mockResolvedValue(statusResponse());

    const { result } = renderHook(() => useGpuControl(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    expect(result.current.canStart).toBe(true);
    expect(result.current.canStop).toBe(false);
    expect(result.current.stopBlockedReason).toBe('already stopped');
    expect(result.current.canReturnToAuto).toBe(false);
  });

  it('blocks stop with an explicit in-flight-work reason', async () => {
    fetchGpuStatusMock.mockResolvedValue(
      statusResponse({
        gpu_state: { state: 'ready', instance_running_since: '2026-09-07T11:00:00Z' },
        load: { has_work: true },
      }),
    );

    const { result } = renderHook(() => useGpuControl(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.canStart).toBe(false);
    expect(result.current.canStop).toBe(false);
    expect(result.current.stopBlockedReason).toContain('describe run is in flight');
  });

  it('optimistically marks an intent pending and restores the snapshot on error', async () => {
    const initial = statusResponse({ state: 'ready' });
    fetchGpuStatusMock.mockResolvedValue(initial);
    let rejectIntent: ((error: Error) => void) | undefined;
    postGpuIntentMock.mockReturnValue(
      new Promise((_, reject) => {
        rejectIntent = reject;
      }),
    );

    const { result } = renderHook(() => useGpuControl(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());

    act(() => {
      result.current.requestIntent(GPU_INTENT_ACTION.STOP);
    });
    await waitFor(() => expect(result.current.data?.gpu_state.intent_status).toBe(GPU_INTENT_STATUS.PENDING));
    expect(result.current.data?.gpu_state.intent).toBe(GPU_INTENT_ACTION.STOP);

    act(() => {
      rejectIntent?.(new Error('502 Bad Gateway'));
    });
    await waitFor(() => expect(result.current.data?.gpu_state.intent).toBe(GPU_INTENT_ACTION.AUTO));
    expect(result.current.data?.gpu_state.intent_status).toBe(GPU_INTENT_STATUS.NONE);
  });

  it('enables Return to automatic only when the effective intent is not automatic', async () => {
    fetchGpuStatusMock.mockResolvedValue(statusResponse({ intent: GPU_INTENT_ACTION.START }));

    const { result } = renderHook(() => useGpuControl(), { wrapper });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.canReturnToAuto).toBe(true);
  });
});
