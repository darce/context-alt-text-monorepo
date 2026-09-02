import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { formatBulkDescribeErrorMessage, useBulkDescribe } from '../useBulkDescribe';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunResponse } from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';

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

const createWrapper = (): { wrapper: typeof wrapper; queryClient: QueryClient } => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const scopedWrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper: scopedWrapper, queryClient };
};

const workbenchInvalidateCount = (spy: ReturnType<typeof vi.spyOn>): number =>
  spy.mock.calls.filter(
    (call) => JSON.stringify(call[0]) === JSON.stringify({ queryKey: queryKeys.media.workbench() }),
  ).length;

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

  it('surfaces a stranded run id in the error notice without starting a progress poll (BR-143)', async () => {
    // Membership write failed after the upstream run was accepted — 500 with
    // code describe_run_media_ids_store_failed and data.run_id populated. The
    // paid run is burning compute; the operator must see the id, and we must
    // NOT pretend submit succeeded by polling ([RLSE-04]).
    const strandedRunId = 'run-stranded-42';
    const payload = {
      code: 'describe_run_media_ids_store_failed',
      message: 'Failed to store describe run media membership.',
      data: { status: 500, run_id: strandedRunId },
    };
    submitBulkDescribeRunMock.mockRejectedValue(
      new Error(`Request to /acx/v1/describe/runs failed (500): ${JSON.stringify(payload)}`),
    );

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isError).toBe(true));
    // runId stays null — no progress poll, no review link as if success.
    expect(result.current.runId).toBeNull();
    expect(result.current.progress.isPolling).toBe(false);
    expect(fetchBulkDescribeRunMock).not.toHaveBeenCalled();
    // Notice carries the resolved server message AND the stranded run id.
    expect(result.current.errorMessage).toContain('Failed to store describe run media membership.');
    expect(result.current.errorMessage).toContain(strandedRunId);
    expect(result.current.errorMessage).toContain('already running upstream');
    // Never the raw HTTPError envelope.
    expect(result.current.errorMessage).not.toContain('Request to /acx/v1/describe/runs failed');
  });

  it('does not invalidate workbench rows while the run is still describing', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-live', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-live',
        status: 'running',
        phase: 'describing',
        completed: 1,
        total: 4,
        eta_seconds: 42,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expect(result.current.progress.isTerminal).toBe(false);
    expect(workbenchInvalidateCount(invalidateSpy)).toBe(0);
    queryClient.clear();
  });

  it('invalidates workbench rows exactly once when the run reaches a terminal phase', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-term', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-term',
        status: 'running',
        phase: 'describing',
        completed: 1,
        total: 4,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');
    const { result, rerender } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expect(workbenchInvalidateCount(invalidateSpy)).toBe(0);

    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-term',
        status: 'completed',
        phase: 'complete',
        completed: 4,
        total: 4,
        eta_seconds: 0,
      }),
    );
    result.current.progress.retry();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(result.current.progress.isTerminal).toBe(true);
    expect(workbenchInvalidateCount(invalidateSpy)).toBe(1);

    // Subsequent polls / renders at the same terminal phase must not refetch again.
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(workbenchInvalidateCount(invalidateSpy)).toBe(1);
    queryClient.clear();
  });
});

describe('formatBulkDescribeErrorMessage', () => {
  it('includes data.run_id when the membership store fails after upstream accept', () => {
    const error = new Error(
      'Request to /acx/v1/describe/runs failed (500): {"code":"describe_run_media_ids_store_failed","message":"Failed to store describe run media membership.","data":{"status":500,"run_id":"run-99"}}',
    );
    const notice = formatBulkDescribeErrorMessage(error);
    expect(notice).toContain('run-99');
    expect(notice).toContain('Failed to store describe run media membership.');
    expect(notice).toContain('already running upstream');
  });

  it('falls back without inventing a run id when the payload has none', () => {
    const error = new Error(
      'Request to /acx/v1/describe/runs failed (500): {"code":"internal","message":"boom","data":{"status":500}}',
    );
    expect(formatBulkDescribeErrorMessage(error)).toBe('boom');
  });
});
