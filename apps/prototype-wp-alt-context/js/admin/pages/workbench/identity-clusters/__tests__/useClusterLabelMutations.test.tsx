/**
 * L1R-07 / BR-16: merge mutationFn's accept-by-id hop must be red-capable.
 * L1V-02: hop-2 accept failure still invalidates (merge may have committed).
 * L1V-03: onSuccess removes accepted suggestion from pending review cache.
 */

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import * as recognitionApi from '../../../../api/recognition';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type { PendingNameSuggestionsResponse, TopUnlabeledClustersResponse } from '../../../../api/recognition/types';
import { useClusterLabelMutations } from '../useClusterLabelMutations';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';

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

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);

const seedReviewPage = (queryClient: QueryClient, suggestionIds: string[]): void => {
  const page: SuggestionReviewPage = {
    items: suggestionIds.map((suggestionId) => ({
      suggestionId,
      identityId: `id-${suggestionId}`,
      clusterId: 'target-c',
      label: 'Target',
      similarity: 0.9,
    })),
    dataSource: undefined,
  };
  queryClient.setQueryData(reviewPageKey, page);
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

  return { result, invalidateQueries, onMergeSuccess, onError, queryClient };
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

  it('invalidates queries when acceptSuggestion rejects after merge landed (L1V-02)', async () => {
    // Predicted first failure: onError only surfaces message — invalidateQueries never called
    // while hop-1 merge already committed, leaving pre-merge cluster UI.
    vi.mocked(recognitionApi.acceptSuggestion).mockRejectedValue(new Error('accept hop failed'));
    const { result, invalidateQueries, onError, onMergeSuccess } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(recognitionApi.mergeCluster).toHaveBeenCalled();
    expect(recognitionApi.acceptSuggestion).toHaveBeenCalledWith('sug-merge-1');
    expect(invalidateQueries).toHaveBeenCalled();
    expect(onMergeSuccess).not.toHaveBeenCalled();
  });

  it('removes accepted suggestion from pending review cache on merge success (L1V-03)', async () => {
    // Predicted first failure: review page still contains sug-merge-1 until refetch.
    const { result, invalidateQueries, queryClient } = renderLabelMutations();
    seedReviewPage(queryClient, ['sug-merge-1', 'sug-other']);

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    const page = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
    expect(page?.items.map((item) => item.suggestionId)).toEqual(['sug-other']);
  });

  it('R1-25: rename drops the labelled group from namePending and topUnlabeled', async () => {
    vi.mocked(recognitionApi.updateClusterLabel).mockResolvedValue({
      cluster_id: 'source-c',
      label: 'Renamed',
    } as never);
    const { result, invalidateQueries, queryClient } = renderLabelMutations();
    const nameKey = queryKeys.suggestions.namePending();
    const topKey = queryKeys.clusters.topUnlabeled('t');
    queryClient.setQueryData<PendingNameSuggestionsResponse>(nameKey, {
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'source-c',
          suggested_name: 'Alex',
          confidence_score: 0.9,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
        {
          id: 'name-2',
          cluster_id: 'other',
          suggested_name: 'Other',
          confidence_score: 0.8,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });
    queryClient.setQueryData<TopUnlabeledClustersResponse>(topKey, {
      clusters: [
        {
          id: 'source-c',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
        {
          id: 'other',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
      ],
      limit: 20,
      total: 2,
      truncated: false,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    result.current.rename('Renamed');
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(
      queryClient.getQueryData<PendingNameSuggestionsResponse>(nameKey)?.suggestions.map((row) => row.id),
    ).toEqual(['name-2']);
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topKey)?.clusters.map((row) => row.id),
    ).toEqual(['other']);
  });

  it('R1-25: merge drops result.source_id from topUnlabeled', async () => {
    const { result, invalidateQueries, queryClient } = renderLabelMutations();
    const topKey = queryKeys.clusters.topUnlabeled('t');
    queryClient.setQueryData<TopUnlabeledClustersResponse>(topKey, {
      clusters: [
        {
          id: 'source-c',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
        {
          id: 'target-c',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
      ],
      limit: 20,
      total: 2,
      truncated: false,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    });

    result.current.merge('target-c', 'Target');
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(
      queryClient.getQueryData<TopUnlabeledClustersResponse>(topKey)?.clusters.map((row) => row.id),
    ).toEqual(['target-c']);
  });
});
