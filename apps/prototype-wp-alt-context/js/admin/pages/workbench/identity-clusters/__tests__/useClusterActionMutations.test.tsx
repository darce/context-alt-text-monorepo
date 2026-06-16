import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { JobStatusResponse } from '../../../../api/recognition';
import * as recognitionApi from '../../../../api/recognition';
import { useClusterActionMutations } from '../useClusterActionMutations';

vi.mock('../../../../api/recognition', () => ({
  createClusterForIdentity: vi.fn(),
  fetchScanStatus: vi.fn(),
  pinRepresentative: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  rejectSuggestion: vi.fn(),
  splitCluster: vi.fn(),
}));

const jobStatus = (status: JobStatusResponse['status'], message?: string): JobStatusResponse => ({
  id: 'split-job-1',
  type: 'split',
  status,
  progress: null,
  started_at: '2026-06-16T00:00:00.000Z',
  finished_at: '2026-06-16T00:00:01.000Z',
  message,
});

describe('useClusterActionMutations pollSplitJob (BND-1-AUDIT-1)', () => {
  const renderSplit = () => {
    const onError = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    // identityCount > 50 selects async mode so splitCluster returns a job_id and pollSplitJob runs.
    const { result } = renderHook(
      () => useClusterActionMutations({ clusterId: 'c1', identityCount: 100, onError, invalidateQueries }),
      { wrapper },
    );
    return { result, onError, invalidateQueries };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(recognitionApi.splitCluster).mockResolvedValue({
      job_id: 'split-job-1',
      status: 'pending',
      message: 'queued',
    });
  });

  it('resolves an async split when the job finishes completed_with_errors (no spurious timeout)', async () => {
    // Before the fix pollSplitJob only returned on 'completed', so a partial-success split spun
    // until the 120s timeout and threw — onSuccess (invalidateQueries) was never reached.
    vi.mocked(recognitionApi.fetchScanStatus).mockResolvedValue(jobStatus('completed_with_errors'));

    const { result, onError, invalidateQueries } = renderSplit();
    result.current.split('c1', 2);

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(onError).not.toHaveBeenCalled();
    expect(recognitionApi.fetchScanStatus).toHaveBeenCalledWith('split-job-1');
  });

  it('resolves an async split when the job finishes completed', async () => {
    vi.mocked(recognitionApi.fetchScanStatus).mockResolvedValue(jobStatus('completed'));

    const { result, onError, invalidateQueries } = renderSplit();
    result.current.split('c1', 2);

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(onError).not.toHaveBeenCalled();
  });

  it('surfaces an error when the async split job finishes failed', async () => {
    vi.mocked(recognitionApi.fetchScanStatus).mockResolvedValue(jobStatus('failed', 'boom'));

    const { result, onError, invalidateQueries } = renderSplit();
    result.current.split('c1', 2);

    await waitFor(() => expect(onError).toHaveBeenCalledWith('boom'));
    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
