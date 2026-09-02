import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { formatBulkDescribeErrorMessage, useBulkDescribe } from '../useBulkDescribe';
import { mediaStatsMissingQueryKey, mediaStatsTotalQueryKey } from '../useMediaStats';
import * as describeApi from '../../api/describeApi';
import type { DescribeRunResponse } from '../../api/describeApi';
import { queryKeys } from '../../api/queryKeys';
import type { WorkbenchMediaResponse } from '../../api/workbenchMediaApi';

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

const workbenchListPageKey = queryKeys.media.workbenchPage({
  page: 1,
  perPage: 20,
  status: 'all',
});

const emptyPage: WorkbenchMediaResponse = { items: [], total: 0, totalPages: 0 };

const seedWorkbenchCache = (client: QueryClient): void => {
  client.setQueryData(workbenchListPageKey, emptyPage);
  client.setQueryData(mediaStatsTotalQueryKey, { items: [], total: 10, totalPages: 10 });
  client.setQueryData(mediaStatsMissingQueryKey, { items: [], total: 3, totalPages: 3 });
};

const resetCachedQueries = (client: QueryClient): void => {
  client.removeQueries({ queryKey: workbenchListPageKey });
  client.removeQueries({ queryKey: mediaStatsTotalQueryKey });
  client.removeQueries({ queryKey: mediaStatsMissingQueryKey });
  seedWorkbenchCache(client);
};

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
  seedWorkbenchCache(queryClient);
  const scopedWrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper: scopedWrapper, queryClient };
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
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expect(result.current.progress.isTerminal).toBe(false);
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('invalidates workbench list pages exactly once when the run reaches a terminal phase [S6-F1]', async () => {
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
    const { result, rerender } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2, 3, 4]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('describing'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(false);

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
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(mediaStatsMissingQueryKey)?.isInvalidated).toBe(false);

    // Subsequent polls / renders at the same terminal phase must not refetch again.
    resetCachedQueries(queryClient);
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).not.toBe(true);
    result.current.progress.retry();
    rerender();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('invalidates list pages once per successive terminal run id [S6-F2]', async () => {
    const { wrapper: scopedWrapper, queryClient } = createWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });

    submitBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-a', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-a',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.submit.mutate([1, 2]);
    await waitFor(() => expect(result.current.runId).toBe('run-a'));
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);

    resetCachedQueries(queryClient);
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).not.toBe(true);

    submitBulkDescribeRunMock.mockResolvedValueOnce(
      runResponse({ run_id: 'run-b', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-b',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.submit.mutate([3, 4]);
    await waitFor(() => expect(result.current.runId).toBe('run-b'));
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it('does not invalidate again when the same runId changes complete → failed [S6-F2]', async () => {
    submitBulkDescribeRunMock.mockResolvedValue(
      runResponse({ run_id: 'run-same', status: 'pending', phase: 'queued' }),
    );
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-same',
        status: 'completed',
        phase: 'complete',
        completed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );

    const { wrapper: scopedWrapper, queryClient } = createWrapper();
    const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
    result.current.submit.mutate([1, 2]);

    await waitFor(() => expect(result.current.progress.run?.phase).toBe('complete'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(true);

    resetCachedQueries(queryClient);
    fetchBulkDescribeRunMock.mockResolvedValue(
      runResponse({
        run_id: 'run-same',
        status: 'failed',
        phase: 'failed',
        completed: 0,
        failed: 2,
        total: 2,
        eta_seconds: 0,
      }),
    );
    result.current.progress.retry();
    await waitFor(() => expect(result.current.progress.run?.phase).toBe('failed'));
    expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);
    queryClient.clear();
  });

  it.each([
    { status: 'failed', phase: 'failed' },
    { status: 'cancelled', phase: 'cancelled' },
    { status: 'completed_with_errors', phase: 'complete' },
  ] as const)(
    'invalidates workbench list pages once for terminal $status / $phase [S6-F3]',
    async ({ status, phase }) => {
      submitBulkDescribeRunMock.mockResolvedValue(
        runResponse({ run_id: `run-${phase}`, status: 'pending', phase: 'queued' }),
      );
      fetchBulkDescribeRunMock.mockResolvedValue(
        runResponse({
          run_id: `run-${phase}`,
          status,
          phase,
          completed: status === 'failed' ? 0 : 3,
          failed: status === 'completed_with_errors' ? 1 : status === 'failed' ? 2 : 0,
          skipped: status === 'cancelled' ? 2 : 0,
          total: 4,
          eta_seconds: 0,
          cancel_requested: status === 'cancelled',
        }),
      );

      const { wrapper: scopedWrapper, queryClient } = createWrapper();
      const { result } = renderHook(() => useBulkDescribe(), { wrapper: scopedWrapper });
      result.current.submit.mutate([1, 2, 3, 4]);

      await waitFor(() => expect(result.current.progress.run?.phase).toBe(phase));
      expect(result.current.progress.isTerminal).toBe(true);
      expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(true);
      expect(queryClient.getQueryState(mediaStatsTotalQueryKey)?.isInvalidated).toBe(false);

      resetCachedQueries(queryClient);
      result.current.progress.retry();
      await waitFor(() => expect(result.current.progress.run?.phase).toBe(phase));
      expect(queryClient.getQueryState(workbenchListPageKey)?.isInvalidated).toBe(false);
      queryClient.clear();
    },
  );
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
