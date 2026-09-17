import { createElement, type ReactElement, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GPU_STATE, type GpuState } from '../../../api/describeApi';
import { GPU_INTENT_ACTION, GPU_INTENT_STATUS, type GpuStatusResponse } from '../../../api/gpuApi';
import * as gpuApi from '../../../api/gpuApi';
import {
  getGpuServiceStatusPollInterval,
  GPU_SERVICE_STATUS_ERROR_BACKOFF_MS,
  GPU_SERVICE_STATUS_POLL_INTERVAL_MS,
  GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
  useGpuServiceStatus,
} from '../../../hooks/useGpuServiceStatus';
import { GpuTierStatus, gpuWaitFromOperationDetail } from '../GpuTierStatus';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (format: string, ...args: (string | number)[]): string => {
    let sequentialIndex = 0;
    return format.replace(/%((\d+)\$)?[sd]/g, (_match, _positional, explicitIndex) => {
      if (explicitIndex) {
        return String(args[Number(explicitIndex) - 1] ?? '');
      }
      return String(args[sequentialIndex++] ?? '');
    });
  },
}));

vi.mock('../../../api/gpuApi', async (importOriginal) => {
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

const ALL_GPU_STATES = [
  GPU_STATE.UNKNOWN,
  GPU_STATE.STOPPED,
  GPU_STATE.STARTING,
  GPU_STATE.WARMING,
  GPU_STATE.READY,
  GPU_STATE.DEGRADED,
] as const satisfies readonly GpuState[];

let queryClient: QueryClient;

const createWrapper = () => {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children);
  return wrapper;
};

const renderGpu = (ui: ReactElement) => render(ui, { wrapper: createWrapper() });

describe('GpuTierStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchGpuStatusMock.mockResolvedValue(statusResponse());
  });

  afterEach(async () => {
    await queryClient?.cancelQueries();
    queryClient?.clear();
    cleanup();
  });

  it.each([
    [GPU_STATE.STOPPED, 'Description Service is off — it starts when you describe'],
    [GPU_STATE.STARTING, 'Description Service is starting…'],
    [GPU_STATE.WARMING, 'Description Service is starting…'],
    [GPU_STATE.READY, 'Description Service is ready'],
    [GPU_STATE.DEGRADED, 'Description Service is unavailable'],
    [GPU_STATE.UNKNOWN, 'Description Service status is out of date'],
  ] as const)('renders GPU_STATE %s with data-gpu-state and idle copy', async (gpuState, copy) => {
    fetchGpuStatusMock.mockResolvedValue(statusResponse({ gpu_state: { state: gpuState } }));
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', { name: copy });
    expect(status).toHaveAttribute('data-gpu-state', gpuState);
    expect(status).toHaveTextContent(copy);
    expect(status.textContent).not.toContain('GPU tier: not reported');
    expect(status.querySelector('svg')).toBeInTheDocument();
  });

  it('covers every canonical GPU_STATE value in the idle table', () => {
    expect(ALL_GPU_STATES).toHaveLength(6);
    expect(new Set(ALL_GPU_STATES)).toEqual(new Set(Object.values(GPU_STATE)));
  });

  it('always renders while idle with no run pending', async () => {
    renderGpu(createElement(GpuTierStatus, { isRunPending: false }));

    expect(
      await screen.findByRole('status', {
        name: 'Description Service is off — it starts when you describe',
      }),
    ).toBeInTheDocument();
  });

  it('omits a numeric wait when starting/warming and the service supplies none', async () => {
    renderGpu(
      createElement(GpuTierStatus, {
        isRunPending: true,
        gpuState: GPU_STATE.WARMING,
      }),
    );

    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent('Description Service is starting…');
    expect(status.textContent).not.toMatch(/\d+s/);
  });

  it('renders the service-advertised startup budget while warming', async () => {
    renderGpu(
      createElement(GpuTierStatus, {
        isRunPending: true,
        gpuState: GPU_STATE.STARTING,
        startupBudgetSeconds: 90,
      }),
    );

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Description Service is starting… up to 90s',
    );
  });

  it('prefers warmup_eta_seconds over startup_budget_seconds when both are supplied', async () => {
    renderGpu(
      createElement(GpuTierStatus, {
        isRunPending: true,
        gpuState: GPU_STATE.WARMING,
        warmupEtaSeconds: 12,
        startupBudgetSeconds: 90,
      }),
    );

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Description Service is starting… about 12s',
    );
  });

  it('renders a zero warmup ETA instead of falling through to the startup budget', async () => {
    renderGpu(
      createElement(GpuTierStatus, {
        isRunPending: true,
        gpuState: GPU_STATE.STARTING,
        warmupEtaSeconds: 0,
        startupBudgetSeconds: 120,
      }),
    );

    const status = await screen.findByRole('status');
    expect(status).toHaveTextContent('Description Service is starting… about 0s');
    expect(status.textContent).not.toContain('up to 120s');
  });

  it('names the deferred Describe effect with a service wait while stopped', async () => {
    renderGpu(createElement(GpuTierStatus, { startupBudgetSeconds: 90 }));

    expect(
      await screen.findByRole('status', {
        name: 'Description Service is off — it starts when you describe (up to 2 min)',
      }),
    ).toBeInTheDocument();
  });

  it('keeps a sub-minute stopped wait in seconds instead of inventing 0 min', async () => {
    renderGpu(createElement(GpuTierStatus, { warmupEtaSeconds: 12 }));

    expect(
      await screen.findByRole('status', {
        name: 'Description Service is off — it starts when you describe (about 12s)',
      }),
    ).toBeInTheDocument();
  });

  it('renders ready tier and model only when the service supplies them', async () => {
    renderGpu(
      createElement(GpuTierStatus, {
        isRunPending: true,
        gpuState: GPU_STATE.READY,
        computeTier: 'final_gpu',
        modelId: 'microsoft/Florence-2-base-ft',
      }),
    );

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Description Service: ready · final_gpu · microsoft/Florence-2-base-ft',
    );
  });

  it('never renders GPU tier: not reported while a status payload exists', async () => {
    fetchGpuStatusMock.mockResolvedValue(
      statusResponse({ gpu_state: { state: GPU_STATE.UNKNOWN }, snapshot_fresh: true }),
    );
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', { name: 'Description Service status is out of date' });
    expect(status).toHaveAttribute('data-gpu-state', GPU_STATE.UNKNOWN);
    expect(status).toHaveTextContent('Description Service status is out of date');
    expect(status.textContent).not.toContain('GPU tier: not reported');
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('renders explicit stale copy with Refresh when the snapshot is stale', async () => {
    fetchGpuStatusMock.mockResolvedValue(
      statusResponse({
        gpu_state: { state: GPU_STATE.READY },
        snapshot_fresh: false,
        snapshot_age_seconds: 240,
      }),
    );
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', { name: 'Description Service status is out of date' });
    expect(status).toHaveAttribute('data-gpu-state', GPU_STATE.UNKNOWN);
    expect(status).toHaveAttribute('data-gpu-terminal', 'false');
    expect(status).not.toHaveClass('acx-sync-status--success');
    expect(status).toHaveTextContent('Description Service status is out of date');
    expect(status.textContent).not.toContain('GPU tier: not reported');
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
  });

  it('renders fetch-failure copy with Retry and refetches on click', async () => {
    fetchGpuStatusMock.mockRejectedValue(new Error('network down'));
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', { name: 'Description Service status unavailable' });
    expect(status).toHaveAttribute('data-gpu-state', GPU_STATE.UNKNOWN);
    expect(status).toHaveTextContent('Description Service status unavailable');
    expect(status.textContent).not.toContain('GPU tier: not reported');

    fetchGpuStatusMock.mockResolvedValue(statusResponse());
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(
      await screen.findByRole('status', {
        name: 'Description Service is off — it starts when you describe',
      }),
    ).toBeInTheDocument();
  });

  it('does not render a raw degraded lifecycle reason from the status payload', async () => {
    fetchGpuStatusMock.mockResolvedValue(
      statusResponse({ gpu_state: { state: GPU_STATE.DEGRADED, reason: 'readiness_timeout' } }),
    );
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', { name: 'Description Service is unavailable' });
    expect(status).toHaveTextContent('Description Service is unavailable');
    expect(status.textContent).not.toContain('readiness_timeout');
  });

  it('announces politely only after a GPU state change', async () => {
    const { rerender } = renderGpu(
      createElement(GpuTierStatus, { isRunPending: true, gpuState: GPU_STATE.STOPPED }),
    );

    const live = await screen.findByTestId('gpu-tier-status-live');
    expect(live).toHaveAttribute('aria-live', 'polite');
    expect(live).toHaveTextContent('');

    rerender(createElement(GpuTierStatus, { isRunPending: true, gpuState: GPU_STATE.READY }));

    await waitFor(() => expect(live).toHaveTextContent('Description Service is ready'));
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'off');
  });

  it('pairs the stopped idle copy with a tokenized tone class and icon', async () => {
    renderGpu(createElement(GpuTierStatus));

    const status = await screen.findByRole('status', {
      name: 'Description Service is off — it starts when you describe',
    });
    expect(status).toHaveClass('acx-sync-status');
    expect(status).toHaveClass('acx-sync-status--info');
    expect(status.querySelector('svg')).toBeInTheDocument();
  });
});

describe('useGpuServiceStatus (owned GpuTierStatus proof)', () => {
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
    expect(getGpuServiceStatusPollInterval(statusResponse({ gpu_state: { state: GPU_STATE.STARTING } }))).toBe(
      GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
    );
    expect(getGpuServiceStatusPollInterval(statusResponse({ gpu_state: { state: GPU_STATE.WARMING } }))).toBe(
      GPU_SERVICE_STATUS_WARMUP_POLL_INTERVAL_MS,
    );
    expect(getGpuServiceStatusPollInterval(statusResponse(), true)).toBe(GPU_SERVICE_STATUS_ERROR_BACKOFF_MS);
  });

  it('pauses polling while a run is pending and resumes after terminal status', async () => {
    const wrapper = createWrapper();
    const { rerender, result } = renderHook(
      ({ isRunPending }: { isRunPending: boolean }) => useGpuServiceStatus({ isRunPending }),
      { wrapper, initialProps: { isRunPending: false } },
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
});

describe('gpuWaitFromOperationDetail', () => {
  const startingDetail = {
    code: 'description_service_starting',
    message: 'Description service is starting.',
    operation_id: 'op-lease-1',
    startup_id: null,
    warmup_eta_seconds: 12,
    startup_budget_seconds: 120,
    timing: {
      queue_ms: 0,
      ramp_up_ms: null,
      processing_ms: null,
      startup_ms: null,
      server_elapsed_ms: 1,
    },
  };

  it('reads warmup_eta_seconds and startup_budget_seconds from a schema-shaped detail', () => {
    expect(gpuWaitFromOperationDetail(startingDetail)).toEqual({
      warmupEtaSeconds: 12,
      startupBudgetSeconds: 120,
    });
    expect(gpuWaitFromOperationDetail(startingDetail)).not.toHaveProperty('modelId');
  });

  it('accepts warmup_eta_seconds of 0 without dropping the budget', () => {
    expect(gpuWaitFromOperationDetail({ ...startingDetail, warmup_eta_seconds: 0 })).toEqual({
      warmupEtaSeconds: 0,
      startupBudgetSeconds: 120,
    });
  });

  it('returns undefined when wait fields are absent', () => {
    expect(
      gpuWaitFromOperationDetail({
        code: startingDetail.code,
        message: startingDetail.message,
        operation_id: startingDetail.operation_id,
        startup_id: startingDetail.startup_id,
        timing: startingDetail.timing,
      }),
    ).toBeUndefined();
  });

  it('returns undefined for non-objects and invalid wait fields', () => {
    expect(gpuWaitFromOperationDetail(null)).toBeUndefined();
    expect(gpuWaitFromOperationDetail(undefined)).toBeUndefined();
    expect(gpuWaitFromOperationDetail('starting')).toBeUndefined();
    expect(
      gpuWaitFromOperationDetail({
        ...startingDetail,
        warmup_eta_seconds: -1,
        startup_budget_seconds: 0,
      }),
    ).toBeUndefined();
  });

  it('omits a single invalid field while keeping the valid one', () => {
    expect(
      gpuWaitFromOperationDetail({
        ...startingDetail,
        warmup_eta_seconds: Number.NaN,
      }),
    ).toEqual({ startupBudgetSeconds: 120 });
    expect(
      gpuWaitFromOperationDetail({
        ...startingDetail,
        startup_budget_seconds: Number.POSITIVE_INFINITY,
      }),
    ).toEqual({ warmupEtaSeconds: 12 });
  });
});
