import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import type { JobStatusResponse } from '../../../../api/recognition';
import * as recognitionApi from '../../../../api/recognition';
import { useClusterActionMutations } from '../useClusterActionMutations';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', () => ({
  acceptSuggestion: vi.fn(),
  createClusterForIdentity: vi.fn(),
  fetchScanStatus: vi.fn(),
  pinRepresentative: vi.fn(),
  reassignClusterIdentity: vi.fn(),
  rejectSuggestion: vi.fn(),
  splitCluster: vi.fn(),
}));

let offline = false;

vi.mock('../../../../hooks/useSyncOffline', () => ({
  useSyncOffline: () => offline,
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
    offline = false;
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

  it('exposes splitGate offline and split fails fast with a visible error (RES-03)', async () => {
    offline = true;
    const { result, onError } = renderSplit();

    expect(result.current.splitGate.disabled).toBe(true);
    expect(result.current.splitGate.title).toBe('Unavailable while the recognition service is offline');
    expect(result.current.splitGate['aria-disabled']).toBe(true);

    result.current.split('c1', 2);
    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith('Unavailable while the recognition service is offline'),
    );
    expect(recognitionApi.splitCluster).not.toHaveBeenCalled();
  });

  it('exposes enabled splitGate online', () => {
    const { result } = renderSplit();
    expect(result.current.splitGate.disabled).toBe(false);
    expect(result.current.splitGate.title).toBeUndefined();
  });
});

describe('useClusterActionMutations assign accept-by-id (L1R-07 / BR-16)', () => {
  const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);

  const renderAssign = () => {
    const onError = vi.fn();
    const invalidateQueries = vi.fn();
    const onRenameSuccess = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: null,
          onError,
          onRenameSuccess,
          invalidateQueries,
        }),
      { wrapper },
    );
    return { result, onError, invalidateQueries, onRenameSuccess, queryClient };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    offline = false;
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sug-assign-1',
      resolution: 'accepted',
      identity_id: 'id-1',
      cluster_id: 'target-c',
      message: 'ok',
    });
    vi.mocked(recognitionApi.reassignClusterIdentity).mockResolvedValue(undefined);
  });

  it('calls acceptSuggestion with the threaded id and skips reassign (L1R-07)', async () => {
    // Predicted first failure if accept-by-id branch is removed: reassignClusterIdentity
    // fires instead (or neither), and acceptSuggestion is never called with the id.
    const { result, invalidateQueries } = renderAssign();

    result.current.assignToCluster('id-1', 'target-c', undefined, 'sug-assign-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sug-assign-1');
    expect(recognitionApi.reassignClusterIdentity).not.toHaveBeenCalled();
  });

  it('uses reassignClusterIdentity when assign has no suggestionId', async () => {
    const { result, invalidateQueries } = renderAssign();

    result.current.assignToCluster('id-1', 'target-c');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.reassignClusterIdentity).toHaveBeenCalledWith(
      { identityId: 'id-1', targetClusterId: 'target-c' },
      undefined,
    );
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();
  });

  it('removes accepted suggestion from pending review cache on assign success (L1V-03)', async () => {
    // Predicted first failure: sug-assign-1 remains in review page until refetch.
    const { result, invalidateQueries, queryClient } = renderAssign();
    const page: SuggestionReviewPage = {
      items: [
        {
          suggestionId: 'sug-assign-1',
          identityId: 'id-1',
          clusterId: 'target-c',
          label: 'Target',
          similarity: 0.9,
        },
        {
          suggestionId: 'sug-keep',
          identityId: 'id-2',
          clusterId: 'other',
          label: 'Other',
          similarity: 0.8,
        },
      ],
      dataSource: undefined,
    };
    queryClient.setQueryData(reviewPageKey, page);

    result.current.assignToCluster('id-1', 'target-c', undefined, 'sug-assign-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    const next = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
    expect(next?.items.map((item) => item.suggestionId)).toEqual(['sug-keep']);
  });
});

describe('useClusterActionMutations create-for-identity roster bind (UXW2-3-R7B-01)', () => {
  const renderCreate = () => {
    const onError = vi.fn();
    const invalidateQueries = vi.fn();
    const onRenameSuccess = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterActionMutations({
          clusterId: null,
          onError,
          onRenameSuccess,
          invalidateQueries,
        }),
      { wrapper },
    );
    return { result, onError, invalidateQueries, onRenameSuccess };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    offline = false;
  });

  it('passes rosterEntryId through to createClusterForIdentity', async () => {
    vi.mocked(recognitionApi.createClusterForIdentity).mockResolvedValue({
      cluster_id: 'c-new',
      label: 'Alex',
      identity_id: 'anchor-1',
      message: 'ok',
    });
    const { result, invalidateQueries } = renderCreate();

    result.current.createClusterForIdentity('anchor-1', 'Alex', undefined, 7);

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.createClusterForIdentity).toHaveBeenCalledTimes(1);
    expect(recognitionApi.createClusterForIdentity).toHaveBeenCalledWith(
      { identityId: 'anchor-1', label: 'Alex', rosterEntryId: 7 },
      undefined,
    );
  });

  it('on acx_cluster_created_bind_failed surfaces bind error and still invalidates', async () => {
    vi.mocked(recognitionApi.createClusterForIdentity).mockRejectedValue(
      new Error(
        'Request to /create-for-identity failed (409): {"code":"acx_cluster_created_bind_failed","data":{"cluster_id":"c-new"}}',
      ),
    );
    const { result, onError, invalidateQueries } = renderCreate();

    result.current.createClusterForIdentity('anchor-1', 'Alex', undefined, 7);

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onError).toHaveBeenCalledWith('The group was created but the person was not bound.');
    expect(invalidateQueries).toHaveBeenCalled();
  });
});
