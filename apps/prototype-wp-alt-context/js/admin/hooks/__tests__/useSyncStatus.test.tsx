import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useSyncStatus } from '../useSyncStatus';
import * as recognitionApi from '../../api/recognition';

vi.mock('../../api/recognition', () => ({
  fetchSyncStatus: vi.fn(),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

describe('useSyncStatus', () => {
  const createDeferred = <T,>() => {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns sync status data', async () => {
    const fetchSyncStatusMock = vi.mocked(recognitionApi.fetchSyncStatus);
    const statusDeferred = createDeferred<recognitionApi.SyncStatusResponse>();
    fetchSyncStatusMock.mockReturnValue(statusDeferred.promise);

    const { wrapper, queryClient } = createWrapper();
    const { result } = renderHook(() => useSyncStatus(), { wrapper });

    await waitFor(() => expect(fetchSyncStatusMock).toHaveBeenCalled());

    await act(async () => {
      statusDeferred.resolve({
        last_snapshot_version: 3,
        last_synced_at: '2026-02-14 00:00:00',
        is_stale: false,
        sync_health: 'healthy',
        last_sync_result: 'ok',
      });
      await statusDeferred.promise;
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.last_snapshot_version).toBe(3);

    queryClient.clear();
  });

  it('handles error state', async () => {
    const fetchSyncStatusMock = vi.mocked(recognitionApi.fetchSyncStatus);
    const statusDeferred = createDeferred<recognitionApi.SyncStatusResponse>();
    fetchSyncStatusMock.mockReturnValue(statusDeferred.promise);

    const { wrapper, queryClient } = createWrapper();
    const { result } = renderHook(() => useSyncStatus(), { wrapper });

    await waitFor(() => expect(fetchSyncStatusMock).toHaveBeenCalled());

    await act(async () => {
      statusDeferred.reject(new Error('Network error'));
      try {
        await statusDeferred.promise;
      } catch {
        // Expected rejection
      }
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();

    queryClient.clear();
  });
});
