import React from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DESCRIBE_RUN_POLL_INTERVAL_MS,
  FROZEN_POLL_ESCALATION_THRESHOLD,
  getDescribeRunRefetchInterval,
  isFrozenPollFailure,
  useDescribeRunProgress,
} from '../useDescribeRunProgress';
import * as describeApi from '../../api/describeApi';
import { GPU_STATE, type DescribeRunResponse } from '../../api/describeApi';
import { GpuTierStatus } from '../../pages/workbench/MediaSelection';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return { ...actual, fetchBulkDescribeRun: vi.fn() };
});

const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);
const adminRoot = join(__dirname, '..', '..');
const appRoot = join(adminRoot, '..', '..');
const mediaSelectionStyles = readFileSync(
  join(adminRoot, 'styles', 'components', '_media-selection.scss'),
  'utf8',
);
const gpuUxMapMarkdown = readFileSync(
  join(appRoot, 'docs', 'ux-maps', 'describe-gpu-tier.uxmap.md'),
  'utf8',
);
const gpuUxMap = JSON.parse(
  readFileSync(join(appRoot, 'docs', 'ux-maps', 'describe-gpu-tier.uxmap.json'), 'utf8'),
) as {
  screens: { id: string; zones: { id: string; states: string[] }[] }[];
};

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'running',
  phase: 'describing',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 4,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  ...overrides,
});

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('isFrozenPollFailure (FEBT2-LA-NEW-02 policy seam)', () => {
  // The UI freeze policy is "the poll did not come back", which is true of BOTH
  // abort-like shapes. The retry policy is narrower on purpose. Narrowing this
  // one to deliberate aborts is exactly the FEBT1-W2A-05 regression, so it has
  // to fail here rather than silently un-freezing the progress bar.
  it('freezes on an elapsed deadline', () => {
    expect(isFrozenPollFailure(Object.assign(new Error('timed out'), { name: 'TimeoutError' }))).toBe(
      true,
    );
  });

  it('freezes on a deliberate cancel', () => {
    expect(isFrozenPollFailure(Object.assign(new Error('aborted'), { name: 'AbortError' }))).toBe(true);
  });

  it('does not freeze on a hard failure', () => {
    expect(isFrozenPollFailure(new Error('boom'))).toBe(false);
    expect(isFrozenPollFailure(null)).toBe(false);
  });
});

describe('getDescribeRunRefetchInterval (UXP-2-BR-07 pure policy)', () => {
  const running = runResponse({ status: 'running', completed: 1, total: 4 });
  const completed = runResponse({ status: 'completed', completed: 4, total: 4 });
  const timeoutError = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
  const abortError = Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' });
  const hardError = new Error('network down');

  // TEST-15: each branch fails if the corresponding condition is inverted.
  it('keeps polling through abort-like (timeout) transient errors', () => {
    expect(
      getDescribeRunRefetchInterval({
        status: 'error',
        error: timeoutError,
        data: running,
        frozenPollStreak: 0,
      }),
    ).toBe(DESCRIBE_RUN_POLL_INTERVAL_MS);
  });

  it('keeps polling through abort-like (AbortError) transient errors', () => {
    expect(
      getDescribeRunRefetchInterval({
        status: 'error',
        error: abortError,
        data: running,
        frozenPollStreak: 1,
      }),
    ).toBe(DESCRIBE_RUN_POLL_INTERVAL_MS);
  });

  it('stops polling on terminal completion', () => {
    expect(
      getDescribeRunRefetchInterval({
        status: 'success',
        error: null,
        data: completed,
        frozenPollStreak: 0,
      }),
    ).toBe(false);
  });

  it('stops polling on hard (non-abort) errors', () => {
    expect(
      getDescribeRunRefetchInterval({
        status: 'error',
        error: hardError,
        data: running,
        frozenPollStreak: 0,
      }),
    ).toBe(false);
  });

  it('stops polling once the frozen-streak bound is reached', () => {
    expect(
      getDescribeRunRefetchInterval({
        status: 'error',
        error: timeoutError,
        data: running,
        frozenPollStreak: FROZEN_POLL_ESCALATION_THRESHOLD,
      }),
    ).toBe(false);
  });
});

describe('useDescribeRunProgress', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('does not poll when runId is null', () => {
    const { result } = renderHook(() => useDescribeRunProgress(null), { wrapper });
    expect(fetchBulkDescribeRunMock).not.toHaveBeenCalled();
    expect(result.current.run).toBeNull();
    expect(result.current.status).toBeNull();
    expect(result.current.isPolling).toBe(false);
    expect(result.current.etaSeconds).toBeNull();
    expect(result.current.gpuState).toBe('unknown');
    expect(result.current.progressFraction).toBeNull();
  });

  it.each([
    ['stopping', 'unknown'],
    ['ready', 'ready'],
    [null, 'unknown'],
  ] as const)('narrows API gpu_state %s to %s', async (gpuState, expected) => {
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse({ status: 'running', gpu_state: gpuState }));

    const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

    // `status` is null before React Query commits the response. Awaiting it first
    // prevents UNKNOWN cases from passing against the hook's initial value.
    await waitFor(() => expect(result.current.status).toBe('running'));
    expect(result.current.gpuState).toBe(expected);
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledOnce();
  });

  it('renders not-reported after a known state receives malformed GPU telemetry', async () => {
    fetchBulkDescribeRunMock
      .mockResolvedValueOnce(runResponse({ status: 'running', gpu_state: GPU_STATE.READY }))
      .mockResolvedValueOnce(runResponse({ status: 'running', gpu_state: 'stopping' }));

    const Harness = (): React.JSX.Element => {
      const progress = useDescribeRunProgress('run-1');
      return (
        <>
          <GpuTierStatus gpuState={progress.gpuState ?? null} cpuDraftCount={0} />
          <button type="button" onClick={progress.retry}>
            Refresh status
          </button>
        </>
      );
    };

    render(<Harness />, { wrapper });

    await screen.findByRole('status', { name: 'GPU tier: ready' });
    act(() => screen.getByRole('button', { name: 'Refresh status' }).click());

    expect(await screen.findByRole('status', { name: 'GPU tier: not reported' })).toHaveTextContent(
      'GPU tier not reported. Describing can still continue on CPU.',
    );
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledTimes(2);
  });

  it('renders not-reported after a known state receives an omitted gpu_state', async () => {
    const responseWithoutGpuState = runResponse({ status: 'running' });
    delete (responseWithoutGpuState as Partial<DescribeRunResponse>).gpu_state;
    fetchBulkDescribeRunMock
      .mockResolvedValueOnce(runResponse({ status: 'running', gpu_state: GPU_STATE.READY }))
      .mockResolvedValueOnce(responseWithoutGpuState);

    const Harness = (): React.JSX.Element => {
      const progress = useDescribeRunProgress('run-1');
      return (
        <>
          <GpuTierStatus gpuState={progress.gpuState ?? null} cpuDraftCount={0} />
          <button type="button" onClick={progress.retry}>
            Refresh status
          </button>
        </>
      );
    };

    render(<Harness />, { wrapper });

    await screen.findByRole('status', { name: 'GPU tier: ready' });
    act(() => screen.getByRole('button', { name: 'Refresh status' }).click());

    expect(await screen.findByRole('status', { name: 'GPU tier: not reported' })).toHaveTextContent(
      'GPU tier not reported. Describing can still continue on CPU.',
    );
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    [GPU_STATE.STOPPED, 'GPU tier: stopped'],
    [GPU_STATE.STARTING, 'GPU tier: starting'],
    [GPU_STATE.WARMING, 'GPU tier: warming'],
    [GPU_STATE.READY, 'GPU tier: ready'],
    [GPU_STATE.DEGRADED, 'GPU tier: degraded'],
  ] as const)('renders valid GPU state %s with accessible name %s', (gpuState, accessibleName) => {
    render(<GpuTierStatus gpuState={gpuState} cpuDraftCount={0} />);

    expect(screen.getByRole('status', { name: accessibleName })).toHaveAttribute('data-gpu-state', gpuState);
  });

  it('renders icon-and-text not-reported status while a run is relevant', () => {
    render(<GpuTierStatus gpuState={GPU_STATE.UNKNOWN} cpuDraftCount={0} />);

    const status = screen.getByRole('status', { name: 'GPU tier: not reported' });
    expect(status).toHaveTextContent('GPU tier not reported. Describing can still continue on CPU.');
    expect(status.querySelector('svg')).toBeInTheDocument();
  });

  it('announces not-reported in the mounted live region when a known state becomes unknown', () => {
    const { rerender } = render(<GpuTierStatus gpuState={GPU_STATE.READY} cpuDraftCount={0} />);

    const liveRegion = screen.getByRole('status', { name: 'GPU tier: ready' });

    rerender(<GpuTierStatus gpuState={GPU_STATE.UNKNOWN} cpuDraftCount={0} />);

    const updatedLiveRegion = screen.getByRole('status', { name: 'GPU tier: not reported' });
    expect(updatedLiveRegion).toBe(liveRegion);
    expect(updatedLiveRegion).toHaveAttribute('aria-atomic', 'true');
    expect(updatedLiveRegion).toHaveTextContent('GPU tier not reported. Describing can still continue on CPU.');
  });

  it('renders the not-reported presentation for a direct legacy null GPU state', () => {
    render(<GpuTierStatus gpuState={null} cpuDraftCount={0} />);

    expect(screen.getByRole('status', { name: 'GPU tier: not reported' })).toHaveAttribute(
      'data-gpu-state',
      GPU_STATE.UNKNOWN,
    );
  });

  it('hides GPU status only when there is no relevant run', () => {
    render(<GpuTierStatus gpuState={GPU_STATE.UNKNOWN} cpuDraftCount={0} isRunRelevant={false} />);

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('reserves a tokenized block-size slot for GPU status changes', () => {
    render(<GpuTierStatus gpuState={GPU_STATE.READY} cpuDraftCount={0} />);

    expect(screen.getByRole('status')).toHaveClass('acx-media-selection__gpu-tier-status');
    expect(mediaSelectionStyles).toMatch(
      /&__gpu-tier-status\s*{[^}]*min-block-size:\s*var\(--acx-space-\d+\)/s,
    );
  });

  it('keeps the GPU UX-map JSON and rendered contract aligned on visible unknown', () => {
    const workbenchScreen = gpuUxMap.screens.find((candidate) => candidate.id === 'workbench-media-selection');
    const gpuZone = workbenchScreen?.zones.find((candidate) => candidate.id === 'z-gpu-tier-chip');

    expect(gpuZone?.states).toEqual(expect.arrayContaining(['hidden-no-run', 'unknown']));
    expect(gpuZone?.states).not.toContain('hidden-unknown');
    expect(gpuUxMapMarkdown).toContain('explicit `unknown` telemetry renders the calm `GPU tier: not reported` state');
    expect(gpuUxMapMarkdown).toContain('the zone is hidden only when there is no relevant run');
  });

  it('consumes backend eta_seconds verbatim and derives progressFraction', async () => {
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ status: 'running', completed: 1, total: 4, eta_seconds: 87 }),
    );

    const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('running'));
    expect(result.current.etaSeconds).toBe(87);
    expect(result.current.progressFraction).toBeCloseTo(0.25);
    expect(result.current.isTerminal).toBe(false);
    expect(result.current.isPolling).toBe(true);
  });

  it('reports null eta while the backend cannot yet estimate it', async () => {
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ status: 'running', completed: 0, total: 4, eta_seconds: null }),
    );

    const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

    await waitFor(() => expect(result.current.status).toBe('running'));
    expect(result.current.etaSeconds).toBeNull();
    expect(result.current.progressFraction).toBe(0);
  });

  it('treats completed_with_errors as terminal and stops polling', async () => {
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ status: 'completed_with_errors', completed: 3, failed: 1, total: 4, eta_seconds: 0 }),
    );

    const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

    await waitFor(() => expect(result.current.isTerminal).toBe(true));
    expect(result.current.status).toBe('completed_with_errors');
    expect(result.current.isPolling).toBe(false);
    expect(result.current.stalledForSeconds).toBeNull();
  });

  describe('with fake timers', () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it('raises a stall once completed stops advancing past the threshold', async () => {
      fetchBulkDescribeRunMock.mockResolvedValue(
        runResponse({ status: 'running', completed: 1, total: 4, eta_seconds: 60 }),
      );

      const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

      // Flush the first status fetch so a progress baseline is recorded.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.status).toBe('running');
      expect(result.current.stalledForSeconds).toBeNull();

      // No further progress for > 30s => stall indicator fires.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(31_000);
      });
      expect(result.current.stalledForSeconds).not.toBeNull();
      expect(result.current.stalledForSeconds ?? 0).toBeGreaterThanOrEqual(30);
    });

    it('keeps polling through a transient timeout and freezes progress instead of dead-ending (BR-07)', async () => {
      const timeoutError = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
      fetchBulkDescribeRunMock
        .mockResolvedValueOnce(runResponse({ status: 'running', completed: 1, total: 4, eta_seconds: 60 }))
        .mockRejectedValueOnce(timeoutError)
        .mockResolvedValue(runResponse({ status: 'running', completed: 2, total: 4, eta_seconds: 40 }));

      const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.status).toBe('running');
      expect(result.current.isFrozen).toBe(false);

      // Poll 2 times out: progress freezes at last-known values, no dead-end.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(result.current.isFrozen).toBe(true);
      expect(result.current.isError).toBe(false);
      expect(result.current.isPolling).toBe(true);
      expect(result.current.progressFraction).toBeCloseTo(0.25); // frozen, not lost
      expect(result.current.stalledForSeconds).toBeNull(); // paused notice supersedes stall banner

      // Poll 3 succeeds without any manual retry: progress thaws and advances.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(fetchBulkDescribeRunMock.mock.calls.length).toBeGreaterThanOrEqual(3);
      expect(result.current.isFrozen).toBe(false);
      expect(result.current.progressFraction).toBeCloseTo(0.5);
    });

    it('escalates a frozen run to a hard error after 5 consecutive abort-like polls', async () => {
      const timeoutError = Object.assign(new Error('The operation timed out.'), { name: 'TimeoutError' });
      fetchBulkDescribeRunMock
        .mockResolvedValueOnce(runResponse({ status: 'running', completed: 1, total: 4, eta_seconds: 60 }))
        .mockRejectedValue(timeoutError);

      const { result } = renderHook(() => useDescribeRunProgress('run-1'), { wrapper });

      // First poll succeeds: a baseline exists, nothing is frozen yet.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(result.current.status).toBe('running');
      expect(result.current.isFrozen).toBe(false);

      // Four consecutive 2s timeouts: still frozen (recoverable), not a hard error.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(8_000);
      });
      expect(result.current.isFrozen).toBe(true);
      expect(result.current.isError).toBe(false);

      // The 5th consecutive timeout (~>10s dead air) escalates: the frozen state
      // flips to a hard error surfacing the Retry affordance, and polling stops.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4_000);
      });
      expect(result.current.isError).toBe(true);
      expect(result.current.isFrozen).toBe(false);
      expect(result.current.isPolling).toBe(false);

      // The escalated run stops hammering the service (no unbounded retry loop).
      const callsAtEscalation = fetchBulkDescribeRunMock.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(fetchBulkDescribeRunMock.mock.calls.length).toBe(callsAtEscalation);
    });

    it('surfaces a poll error after bounded retries and recovers via retry()', async () => {
      fetchBulkDescribeRunMock.mockRejectedValue(new Error('network down'));

      const { result } = renderHook(() => useDescribeRunProgress('run-err'), { wrapper });

      // Advance through the bounded retry backoff until the error surfaces.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(result.current.isError).toBe(true);
      expect(result.current.error?.message).toBe('network down');
      // A frozen poll must not leave the run looking active: polling stops and
      // the stall banner is suppressed (its own Retry affordance takes over).
      expect(result.current.isPolling).toBe(false);
      expect(result.current.stalledForSeconds).toBeNull();

      // Manual retry that succeeds clears the error and resumes live progress.
      fetchBulkDescribeRunMock.mockResolvedValue(
        runResponse({ run_id: 'run-err', status: 'running', completed: 2, total: 4, eta_seconds: 30 }),
      );
      await act(async () => {
        result.current.retry();
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(result.current.isError).toBe(false);
      expect(result.current.status).toBe('running');
      expect(result.current.etaSeconds).toBe(30);
      expect(result.current.isPolling).toBe(true);
    });
  });
});
