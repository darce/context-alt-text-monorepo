import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useBulkRetryOperations } from '../useBulkRetryOperations';
import * as recognitionApi from '../../api/recognition';
import { buildTestQueryClient, createQueryWrapper } from '../../test-utils/queryClient';

vi.mock('../../api/recognition', () => ({
  bulkRetryFailedOperations: vi.fn(),
}));

describe('useBulkRetryOperations', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls the bulk retry endpoint and invalidates outbox and sync queries on success', async () => {
    const bulkRetryMock = vi.mocked(recognitionApi.bulkRetryFailedOperations);
    bulkRetryMock.mockResolvedValue({ requeued: 3, failed_remaining: 0 });

    const queryClient = buildTestQueryClient();
    const wrapper = createQueryWrapper(queryClient);
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

    const queryClient = buildTestQueryClient();
    const wrapper = createQueryWrapper(queryClient);
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries');

    const { result } = renderHook(() => useBulkRetryOperations(), { wrapper });

    await act(async () => {
      await expect(result.current.mutateAsync()).rejects.toThrow('boom');
    });

    expect(invalidateSpy).not.toHaveBeenCalled();
    queryClient.clear();
  });
});
