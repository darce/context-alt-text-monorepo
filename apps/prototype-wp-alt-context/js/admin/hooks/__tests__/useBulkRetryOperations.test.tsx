import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useBulkRetryOperations } from '../useBulkRetryOperations';
import * as recognitionApi from '../../api/recognition';

vi.mock('../../api/recognition', () => ({
  bulkRetryFailedOperations: vi.fn(),
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { wrapper, queryClient };
};

describe('useBulkRetryOperations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls the bulk retry endpoint and invalidates outbox and sync queries on success', async () => {
    const bulkRetryMock = vi.mocked(recognitionApi.bulkRetryFailedOperations);
    bulkRetryMock.mockResolvedValue({ requeued: 3, failed_remaining: 0 });

    const { wrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useBulkRetryOperations(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync();
    });

    expect(bulkRetryMock).toHaveBeenCalledTimes(1);
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['outbox'] });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['sync'] });
    queryClient.clear();
  });

  it('does not invalidate queries when the bulk retry fails', async () => {
    const bulkRetryMock = vi.mocked(recognitionApi.bulkRetryFailedOperations);
    bulkRetryMock.mockRejectedValue(new Error('boom'));

    const { wrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useBulkRetryOperations(), { wrapper });

    await act(async () => {
      await expect(result.current.mutateAsync()).rejects.toThrow('boom');
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
    queryClient.clear();
  });
});
