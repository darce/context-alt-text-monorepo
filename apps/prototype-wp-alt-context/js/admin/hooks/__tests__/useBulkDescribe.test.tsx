import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useBulkDescribe } from '../useBulkDescribe';
import * as describeApi from '../../api/describeApi';

vi.mock('../../api/describeApi', () => ({
  cancelBulkDescribeRun: vi.fn(),
  submitBulkDescribeRun: vi.fn(),
}));

const submitBulkDescribeRunMock = vi.mocked(describeApi.submitBulkDescribeRun);
const cancelBulkDescribeRunMock = vi.mocked(describeApi.cancelBulkDescribeRun);

const wrapper = ({ children }: React.PropsWithChildren): React.JSX.Element => {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('useBulkDescribe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits media ids and exposes the run response', async () => {
    submitBulkDescribeRunMock.mockResolvedValue({
      tenant_id: 'tenant',
      run_id: 'run-1',
      status: 'pending',
      phase: 'queued',
      completed: 0,
      failed: 0,
      skipped: 0,
      total: 2,
      cancel_requested: false,
      gpu_state: null,
    });

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.submit.mutate([101, 202]);

    await waitFor(() => expect(result.current.submit.isSuccess).toBe(true));
    expect(submitBulkDescribeRunMock).toHaveBeenCalledWith([101, 202]);
    expect(result.current.submit.data?.run_id).toBe('run-1');
  });

  it('cancels the active run id', async () => {
    cancelBulkDescribeRunMock.mockResolvedValue({
      tenant_id: 'tenant',
      run_id: 'run-2',
      status: 'cancelled',
      phase: 'cancelled',
      completed: 0,
      failed: 0,
      skipped: 2,
      total: 2,
      cancel_requested: true,
      gpu_state: null,
    });

    const { result } = renderHook(() => useBulkDescribe(), { wrapper });
    result.current.cancel.mutate('run-2');

    await waitFor(() => expect(result.current.cancel.isSuccess).toBe(true));
    expect(cancelBulkDescribeRunMock).toHaveBeenCalledWith('run-2');
  });
});
