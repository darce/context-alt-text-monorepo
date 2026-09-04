import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as describeApi from '../../api/describeApi';
import { GPU_STATE, type DescribeRunResponse, type GpuState } from '../../api/describeApi';
import type { ToastOptions } from '../../context/ToastContext';
import { GPU_STATE_VOCABULARY } from '../../pages/workbench/gpuStatePresentation';
import { setActiveDescribeRunId, setDescribeProgressMounted } from '../activeDescribeRun';
import { DESCRIBE_RUN_POLL_INTERVAL_MS, useDescribeRunProgress } from '../useDescribeRunProgress';
import { useGpuStateToasts } from '../useGpuStateToasts';

const infoMock = vi.fn<(message: string, options?: ToastOptions) => void>();
const errorMock = vi.fn<(message: string, options?: ToastOptions) => void>();

vi.mock('../../context/ToastContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../context/ToastContext')>();
  return {
    ...actual,
    useToast: () => ({
      toast: vi.fn(),
      success: vi.fn(),
      info: infoMock,
      error: errorMock,
    }),
  };
});

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return { ...actual, fetchBulkDescribeRun: vi.fn() };
});

const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);

const runResponse = (runId: string, gpuState: GpuState): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: runId,
  status: 'running',
  phase: 'describing',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 4,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: gpuState,
});

const LocationProbe = (): React.JSX.Element => {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
};

const ToastHarness = ({ secondObserver = false }: { secondObserver?: boolean }): React.JSX.Element => {
  useGpuStateToasts();
  if (secondObserver) {
    return <SecondObserver />;
  }
  return <LocationProbe />;
};

const SecondObserver = (): React.JSX.Element => {
  useDescribeRunProgress('run-1');
  return <LocationProbe />;
};

const createClient = (): QueryClient =>
  new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

const renderHarness = (secondObserver = false) => {
  const client = createClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/people']}>
        <ToastHarness secondObserver={secondObserver} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

const observeSequence = async (
  states: readonly GpuState[],
  options: { mounted?: boolean; runId?: string } = {},
): Promise<void> => {
  const runId = options.runId ?? 'run-1';
  setDescribeProgressMounted(options.mounted ?? false);
  setActiveDescribeRunId(runId);
  fetchBulkDescribeRunMock.mockImplementation(() => {
    const state = states[Math.min(fetchBulkDescribeRunMock.mock.calls.length - 1, states.length - 1)];
    if (state === undefined) {
      throw new Error('Scripted GPU state sequence must not be empty');
    }
    return Promise.resolve(runResponse(runId, state));
  });
  renderHarness();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  for (let index = 1; index < states.length; index += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DESCRIBE_RUN_POLL_INTERVAL_MS);
    });
  }
};

const expectOnlyInfoToast = (message: string): ToastOptions | undefined => {
  expect(infoMock).toHaveBeenCalledOnce();
  expect(infoMock.mock.calls[0]?.[0]).toBe(message);
  expect(errorMock).not.toHaveBeenCalled();
  return infoMock.mock.calls[0]?.[1];
};

const requireToastOptions = (options: ToastOptions | undefined): ToastOptions => {
  if (!options) {
    throw new Error('Expected the toast to include options');
  }
  return options;
};

const expectOnlyErrorToast = (): ToastOptions => {
  expect(errorMock).toHaveBeenCalledOnce();
  expect(errorMock).toHaveBeenCalledWith(GPU_STATE_VOCABULARY.degradedToast, expect.any(Object));
  expect(infoMock).not.toHaveBeenCalled();
  const options = errorMock.mock.calls[0]?.[1];
  if (!options) {
    throw new Error('Expected the error toast to include options');
  }
  return options;
};

describe('useGpuStateToasts edge policy', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    act(() => {
      setActiveDescribeRunId(null);
      setDescribeProgressMounted(false);
    });
  });

  afterEach(() => {
    act(() => {
      setActiveDescribeRunId(null);
      setDescribeProgressMounted(false);
    });
    vi.useRealTimers();
  });

  it.each([GPU_STATE.STOPPED, GPU_STATE.STARTING])(
    'toasts when %s transitions to warming away from progress',
    async (previous) => {
      await observeSequence([previous, GPU_STATE.WARMING]);
      expectOnlyInfoToast(GPU_STATE_VOCABULARY.warmingToast);
    },
  );

  it('toasts warming to ready away from progress with Back to run', async () => {
    await observeSequence([GPU_STATE.WARMING, GPU_STATE.READY]);

    const options = requireToastOptions(expectOnlyInfoToast(GPU_STATE_VOCABULARY.readyToast));
    expect(options.action).toMatchObject({
      label: GPU_STATE_VOCABULARY.backToRun,
      altText: GPU_STATE_VOCABULARY.backToRunAltText,
    });
    expect(options.durationMs).toBeNull();
    act(() => options.action?.onClick());
    expect(document.querySelector('[data-testid="location"]')).toHaveTextContent('/workbench');
  });

  it.each([GPU_STATE.STOPPED, GPU_STATE.STARTING, GPU_STATE.WARMING, GPU_STATE.READY])(
    'always toasts %s to degraded with Review results',
    async (previous) => {
      await observeSequence([previous, GPU_STATE.DEGRADED], { mounted: true });
      const options = expectOnlyErrorToast();
      expect(options.action).toMatchObject({
        label: GPU_STATE_VOCABULARY.reviewResults,
        altText: GPU_STATE_VOCABULARY.reviewResultsAltText,
      });
      expect(options.durationMs).toBeNull();
    },
  );

  it.each([GPU_STATE.STOPPED, GPU_STATE.STARTING, GPU_STATE.WARMING, GPU_STATE.READY, GPU_STATE.DEGRADED])(
    'never toasts an unknown to %s transition',
    async (next) => {
      await observeSequence([GPU_STATE.UNKNOWN, next]);
      expect(infoMock).not.toHaveBeenCalled();
      expect(errorMock).not.toHaveBeenCalled();
    },
  );

  it.each([GPU_STATE.STOPPED, GPU_STATE.STARTING, GPU_STATE.WARMING, GPU_STATE.READY, GPU_STATE.DEGRADED])(
    'never toasts a %s to unknown transition',
    async (previous) => {
      await observeSequence([previous, GPU_STATE.UNKNOWN]);
      expect(infoMock).not.toHaveBeenCalled();
      expect(errorMock).not.toHaveBeenCalled();
    },
  );

  it('never toasts repeated ready polls', async () => {
    await observeSequence([GPU_STATE.READY, GPU_STATE.READY]);
    expect(infoMock).not.toHaveBeenCalled();
    expect(errorMock).not.toHaveBeenCalled();
  });

  it.each([
    [GPU_STATE.STOPPED, GPU_STATE.WARMING],
    [GPU_STATE.STARTING, GPU_STATE.WARMING],
    [GPU_STATE.WARMING, GPU_STATE.READY],
  ] as const)('suppresses %s to %s while progress is mounted', async (previous, next) => {
    await observeSequence([previous, next], { mounted: true });
    expect(infoMock).not.toHaveBeenCalled();
    expect(errorMock).not.toHaveBeenCalled();
  });

  it.each(Object.values(GPU_STATE))('does not toast first observation %s', async (state) => {
    await observeSequence([state]);
    expect(infoMock).not.toHaveBeenCalled();
    expect(errorMock).not.toHaveBeenCalled();
  });

  it('emits the same edge at most once for a run id', async () => {
    await observeSequence([GPU_STATE.WARMING, GPU_STATE.READY, GPU_STATE.WARMING, GPU_STATE.READY]);
    expect(infoMock).toHaveBeenCalledOnce();
  });

  it('re-arms edge memory for a new run id', async () => {
    fetchBulkDescribeRunMock.mockImplementation((runId) => {
      const callCountForRun = fetchBulkDescribeRunMock.mock.calls.filter(([id]) => id === runId).length;
      return Promise.resolve(runResponse(runId, callCountForRun === 1 ? GPU_STATE.WARMING : GPU_STATE.READY));
    });
    setActiveDescribeRunId('run-1');
    renderHarness();
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () => vi.advanceTimersByTimeAsync(DESCRIBE_RUN_POLL_INTERVAL_MS));
    expect(infoMock).toHaveBeenCalledOnce();

    act(() => setActiveDescribeRunId('run-2'));
    await act(async () => vi.advanceTimersByTimeAsync(0));
    await act(async () => vi.advanceTimersByTimeAsync(DESCRIBE_RUN_POLL_INTERVAL_MS));

    expect(infoMock).toHaveBeenCalledTimes(2);
  });

  it('shares one fetch loop with a second progress observer', async () => {
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse('run-1', GPU_STATE.WARMING));
    setActiveDescribeRunId('run-1');
    renderHarness(true);
    await act(async () => vi.advanceTimersByTimeAsync(0));
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledOnce();

    await act(async () => vi.advanceTimersByTimeAsync(DESCRIBE_RUN_POLL_INTERVAL_MS));
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledTimes(2);
  });
});
