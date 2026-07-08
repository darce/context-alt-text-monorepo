import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useDescribeRunProgress } from '../useDescribeRunProgress';
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
  });
});
