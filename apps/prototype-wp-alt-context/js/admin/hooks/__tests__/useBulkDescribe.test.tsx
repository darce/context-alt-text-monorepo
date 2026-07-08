import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useBulkDescribe } from '../useBulkDescribe';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunResponse } from '../../api/describeApi';

vi.mock('../../api/describeApi', async (importOriginal) => {
  const actual = await importOriginal<typeof describeApi>();
  return {
    ...actual,
    cancelBulkDescribeRun: vi.fn(),
    submitBulkDescribeRun: vi.fn(),
    fetchBulkDescribeRun: vi.fn(),
  };
});

const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const cancelBulkDescribeRunMock = vi.mocked(describeApi.cancelBulkDescribeRun);
const fetchBulkDescribeRunMock = vi.mocked(describeApi.fetchBulkDescribeRun);

const runResponse = (overrides: Partial<DescribeRunResponse> = {}): DescribeRunResponse => ({
  tenant_id: 'tenant',
  run_id: 'run-1',
  status: 'pending',
  phase: 'queued',
  completed: 0,
  failed: 0,
  skipped: 0,
  total: 2,
  cancel_requested: false,
  eta_seconds: null,
  gpu_state: null,
  ...overrides,
});

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useBulkDescribe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: a terminal poll response so no test leaves the interval polling.
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse({ status: 'completed' }));
  });

  it('submits media ids and captures the run id', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-1', status: 'pending' }));

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith([101, 202]);
    expect(result.current.submit.data?.run_id).toBe('run-1');
    await waitFor(() => expect(result.current.runId).toBe('run-1'));
  });

  it('polls run status and reflects backend eta_seconds + progress fraction', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-9', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-9', status: 'running', completed: 1, total: 4, eta_seconds: 42 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.status).toBe('running'));
    expect(fetchBulkDescribeRunMock).toHaveBeenCalledWith('run-9');
    // ETA is consumed verbatim from the backend, not recomputed.
    expect(result.current.progress.etaSeconds).toBe(42);
    expect(result.current.progress.progressFraction).toBeCloseTo(0.25);
    expect(result.current.progress.isTerminal).toBe(false);
    expect(result.current.progress.isPolling).toBe(true);
  });

  it('marks the run terminal and stops polling when status is completed', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-done', status: 'pending' }));
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-done', status: 'completed', completed: 4, total: 4, eta_seconds: 0 }),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.isTerminal).toBe(true));
    expect(result.current.progress.status).toBe('completed');
    expect(result.current.progress.progressFraction).toBe(1);
    expect(result.current.progress.isPolling).toBe(false);
  });

  it('cancels the active run id', async () => {
    cancelBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-2', status: 'cancelled', phase: 'cancelled', skipped: 2, cancel_requested: true }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(runResponse({ run_id: 'run-2', status: 'cancelled' }));

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.cancel.mutate('run-2');

    await waitFor(() => expect(result.current.cancel.isSuccess).toBe(true));
    expect(cancelBulkDescribeRunMock).toHaveBeenCalledWith('run-2');
    await waitFor(() => expect(result.current.runId).toBe('run-2'));
  });
});
