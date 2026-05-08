import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';

import {
  fetchRecentBatchRuns,
  fetchScanStatus,
  type RecentBatchRunsResponse,
} from '../../api/recognition';
import { useRecognitionJobHistory } from '../useRecognitionJobHistory';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/recognition', () => ({
  fetchRecentBatchRuns: vi.fn(),
  fetchScanStatus: vi.fn(),
}));

const createDeferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe('useRecognitionJobHistory', () => {
  const fetchScanStatusMock = vi.mocked(fetchScanStatus);
  const fetchRecentBatchRunsMock = vi.mocked(fetchRecentBatchRuns);

  const createWrapper = () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { wrapper, queryClient };
  };

  beforeEach(() => {
    window.localStorage.clear();
    fetchScanStatusMock.mockReset();
    fetchRecentBatchRunsMock.mockReset();
  });

  it('prefers durable recent batch runs and fetches their latest job statuses', async () => {
    const { wrapper, queryClient } = createWrapper();
    const recentBatchRunsDeferred = createDeferred<RecentBatchRunsResponse>();
    const statusDeferred = createDeferred<{
      id: string;
      type: 'analyze' | 'clustering' | 'curation' | 'split';
      status: 'pending' | 'running' | 'completed' | 'failed';
      progress: { completed: number; total: number };
      started_at: string;
      finished_at: string;
    }>();
    fetchScanStatusMock.mockReturnValue(statusDeferred.promise);
    const recentBatchRunsResponse: RecentBatchRunsResponse = {
      items: [
        {
          run_id: 'run-1',
          latest_job_id: 'job-1',
          latest_job_status: 'completed',
          child_job_ids: ['job-1'],
          submitted_total: 1,
          accepted_total: 1,
          completed_total: 1,
          failed_total: 0,
          cancelled_total: 0,
          terminal_state: true,
          failed_batches: [],
          created_at: '2025-01-01 00:00:00',
          updated_at: '2025-01-01 00:00:01',
        },
      ],
    };
    const statusResponse = {
      id: 'job-1',
      type: 'analyze' as const,
      status: 'completed' as const,
      progress: { completed: 1, total: 1 },
      started_at: '2025-01-01T00:00:00Z',
      finished_at: '2025-01-01T00:00:01Z',
    };
    fetchRecentBatchRunsMock.mockReturnValue(recentBatchRunsDeferred.promise);
    const { result } = renderHook(() => useRecognitionJobHistory(), { wrapper });

    await waitFor(() => expect(fetchRecentBatchRunsMock).toHaveBeenCalledWith(5));

    await act(async () => {
      recentBatchRunsDeferred.resolve(recentBatchRunsResponse);
      await recentBatchRunsDeferred.promise;
    });

    await waitFor(() => {
      expect(result.current.historySource).toBe('durable');
      expect(result.current.jobHistory).toEqual(['job-1']);
      expect(result.current.recentActivity[0]).toMatchObject({
        runId: 'run-1',
        jobId: 'job-1',
        provenance: 'durable_batch_run',
      });
    });

    await waitFor(() => expect(fetchScanStatusMock).toHaveBeenCalledWith('job-1'));

    await act(async () => {
      statusDeferred.resolve(statusResponse);
      await statusDeferred.promise;
    });

    await waitFor(() => {
      expect(result.current.jobStatuses['job-1']).toBe('completed');
    });

    queryClient.clear();
  });

  it('falls back to browser-local history when durable activity is unavailable', async () => {
    const { wrapper, queryClient } = createWrapper();
    window.localStorage.setItem('acx-recognition-jobs', JSON.stringify(['stored-job']));
    const recentBatchRunsDeferred = createDeferred<never>();
    fetchRecentBatchRunsMock.mockReturnValue(recentBatchRunsDeferred.promise);
    const statusDeferred = createDeferred<{
      id: string;
      type: 'analyze' | 'clustering' | 'curation' | 'split';
      status: 'pending' | 'running' | 'completed' | 'failed';
      progress: { completed: number; total: number };
      started_at: string;
      finished_at: string;
    }>();
    fetchScanStatusMock.mockReturnValue(statusDeferred.promise);
    const { result } = renderHook(() => useRecognitionJobHistory(), { wrapper });

    await waitFor(() => expect(fetchRecentBatchRunsMock).toHaveBeenCalledWith(5));

    await act(async () => {
      recentBatchRunsDeferred.reject(new Error('offline'));
      await expect(recentBatchRunsDeferred.promise).rejects.toThrow('offline');
    });

    await waitFor(() => {
      expect(result.current.historySource).toBe('browser_local_fallback');
      expect(result.current.recentActivity[0]).toMatchObject({
        jobId: 'stored-job',
        provenance: 'browser_local_fallback',
      });
      expect(result.current.jobHistory).toEqual(['stored-job']);
      expect(result.current.jobId).toBe('stored-job');
    });

    await waitFor(() => expect(fetchScanStatusMock).toHaveBeenCalledWith('stored-job'));

    await act(async () => {
      statusDeferred.resolve({
        id: 'stored-job',
        type: 'analyze',
        status: 'completed',
        progress: { completed: 1, total: 1 },
        started_at: '2025-01-01T00:00:00Z',
        finished_at: '2025-01-01T00:00:01Z',
      });
      await statusDeferred.promise;
    });

    act(() => {
      result.current.selectJob('another-job');
    });

    expect(result.current.jobId).toBe('another-job');

    queryClient.clear();
  });

  it('reports unavailable when durable activity cannot load and no local history exists', async () => {
    const { wrapper, queryClient } = createWrapper();
    const recentBatchRunsDeferred = createDeferred<never>();
    fetchRecentBatchRunsMock.mockReturnValue(recentBatchRunsDeferred.promise);

    const { result } = renderHook(() => useRecognitionJobHistory(), { wrapper });

    await waitFor(() => expect(fetchRecentBatchRunsMock).toHaveBeenCalledWith(5));

    await act(async () => {
      recentBatchRunsDeferred.reject(new Error('offline'));
      await expect(recentBatchRunsDeferred.promise).rejects.toThrow('offline');
    });

    await waitFor(() => {
      expect(result.current.historySource).toBe('unavailable');
      expect(result.current.jobHistory).toEqual([]);
      expect(result.current.recentActivity).toEqual([]);
    });

    expect(fetchScanStatusMock).not.toHaveBeenCalled();
    queryClient.clear();
  });
});
