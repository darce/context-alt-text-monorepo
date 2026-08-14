/**
 * L1R-07 / BR-16: merge mutationFn's accept-by-id hop must be red-capable.
 * Reverting only `if (suggestionId) await acceptSuggestion(suggestionId)` leaves
 * intermediate confirm-chain tests green while re-breaking end-to-end resolution.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as recognitionApi from '../../../../api/recognition';
import { useClusterLabelMutations } from '../useClusterLabelMutations';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

vi.mock('../../../../api/recognition', () => ({
  acceptSuggestion: vi.fn(),
  mergeCluster: vi.fn(),
  revertMergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
}));

const mergeResponse = {
  source_id: 'source-c',
  source_label: 'Source',
  target_id: 'target-c',
  target_label: 'Target',
  identities_moved: 1,
  moved_identity_ids: ['id-1'],
  target_identity_count: 2,
};

const renderLabelMutations = () => {
  const invalidateQueries = vi.fn();
  const cancelIdentityQueries = vi.fn().mockResolvedValue(undefined);
  const updateCachedClusterLabel = vi.fn();
  const onMergeSuccess = vi.fn();
  const onError = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  const { result } = renderHook(
    () =>
      useClusterLabelMutations({
        clusterId: 'source-c',
        currentLabel: 'Source',
        derivedLabel: null,
        onMergeSuccess,
        onError,
        cancelIdentityQueries,
        invalidateQueries,
        updateCachedClusterLabel,
      }),
    { wrapper },
  );

  return { result, invalidateQueries, onMergeSuccess, onError };
};

describe('useClusterLabelMutations merge accept-by-id (L1R-07 / BR-16)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(recognitionApi.mergeCluster).mockResolvedValue(mergeResponse);
    vi.mocked(recognitionApi.acceptSuggestion).mockResolvedValue({
      suggestion_id: 'sug-merge-1',
      resolution: 'accepted',
      identity_id: 'id-1',
      cluster_id: 'target-c',
      message: 'ok',
    });
  });

  it('calls acceptSuggestion with the threaded id after mergeCluster (L1R-07)', async () => {
    // Predicted first failure if accept hop is removed: mergeCluster still runs,
    // acceptSuggestion never called, invalidateQueries still fires from merge success.
    const { result, invalidateQueries, onMergeSuccess } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.mergeCluster).toHaveBeenCalledWith(
      'source-c',
      'target-c',
      'Target',
      undefined,
    );
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sug-merge-1');
    expect(onMergeSuccess).toHaveBeenCalledWith(mergeResponse);
  });

  it('does not call acceptSuggestion when merge has no suggestionId', async () => {
    const { result, invalidateQueries } = renderLabelMutations();

    result.current.merge('target-c', 'Target');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.mergeCluster).toHaveBeenCalled();
    expect(recognitionApi.acceptSuggestion).not.toHaveBeenCalled();
  });
});
