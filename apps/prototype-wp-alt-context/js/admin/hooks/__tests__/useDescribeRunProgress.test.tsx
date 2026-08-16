import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DESCRIBE_RUN_POLL_INTERVAL_MS,
  FROZEN_POLL_ESCALATION_THRESHOLD,
  getDescribeRunRefetchInterval,
  useDescribeRunProgress,
} from '../useDescribeRunProgress';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunResponse } from '../../api/describeApi';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return { ...actual, fetchBulkDescribeRun: vi.fn() };
});

const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);

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
    expect(result.current.progressFraction).toBeNull();
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
