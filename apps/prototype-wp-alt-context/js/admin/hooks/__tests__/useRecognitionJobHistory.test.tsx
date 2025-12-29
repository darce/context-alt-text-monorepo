import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';

import { fetchScanStatus } from '../../api/recognition';
import { useRecognitionJobHistory } from '../useRecognitionJobHistory';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../api/recognition', () => ({
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
  });

  it('records jobs and fetches their statuses', async () => {
    const { wrapper, queryClient } = createWrapper();
    const statusDeferred = createDeferred<{
      id: string;
      type: string;
      status: string;
      progress: { completed: number; total: number };
      started_at: string;
      finished_at: string;
    }>();
    fetchScanStatusMock.mockReturnValue(statusDeferred.promise);
    const statusResponse = {
      id: 'job-1',
      type: 'analyze',
      status: 'completed',
      progress: { completed: 1, total: 1 },
      started_at: '2025-01-01T00:00:00Z',
      finished_at: '2025-01-01T00:00:01Z',
    };
    const { result } = renderHook(() => useRecognitionJobHistory(), { wrapper });

    act(() => {
      result.current.rememberJob('job-1');
    });

    expect(result.current.jobId).toBe('job-1');
    expect(result.current.jobHistory).toEqual(['job-1']);

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

  it('hydrates from stored history and supports job selection', async () => {
    const { wrapper, queryClient } = createWrapper();
    window.localStorage.setItem('acx-recognition-jobs', JSON.stringify(['stored-job']));
    const statusDeferred = createDeferred<{
      id: string;
      type: string;
      status: string;
      progress: { completed: number; total: number };
      started_at: string;
      finished_at: string;
    }>();
    fetchScanStatusMock.mockReturnValue(statusDeferred.promise);
    const { result } = renderHook(() => useRecognitionJobHistory(), { wrapper });

    await waitFor(() => {
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
});
