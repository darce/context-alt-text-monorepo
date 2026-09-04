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
import { AuthExpiredError, HTTPError } from '../../../../utils/http';
import { SPA_SESSION_EXPIRED_COPY } from '../../../../utils/sessionExpiredCopy';
import { createClusterMutationTimeoutError } from '../clusterMutationUtils';
import { useClusterLabelMutations } from '../useClusterLabelMutations';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (text: string, ...values: (string | number)[]) => {
    let index = 0;
    return text
      .replace(/%(\d+)\$[sd]/g, (_match, group: string) => String(values[Number(group) - 1] ?? ''))
      .replace(/%[sd]/g, () => String(values[index++] ?? ''));
  },
}));

vi.mock('../../../../api/recognition', () => ({
  acceptMergeSuggestion: vi.fn(),
  mergeCluster: vi.fn(),
  revertMergeCluster: vi.fn(),
  updateClusterLabel: vi.fn(),
}));

const mergeResponse = {
  source_id: 'retired-source-id',
  source_label: 'Source',
  target_id: 'target-c',
  target_label: 'Target',
  identities_moved: 1,
  moved_identity_ids: ['id-1'],
  target_identity_count: 2,
};

/**
 * Atomic accept envelope (lane F contract). `source_cluster_id`/`target_cluster_id`
 * are the authoritative topology; `moved_identity_ids` is the revert set.
 */
const acceptedMergeSuggestion = {
  id: 'sug-merge-1',
  cluster_a_id: 'panel-c',
  cluster_b_id: 'target-c',
  cluster_a_label: 'Source',
  cluster_b_label: 'Target',
  similarity: 0.9,
  status: 'accepted',
  source_cluster_id: 'retired-source-id',
  target_cluster_id: 'target-c',
  moved_identity_ids: ['id-1'],
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
        clusterId: 'panel-c',
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
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue({
      ...acceptedMergeSuggestion,
      // The accept envelope reports the retired side as a cluster of the pair.
      cluster_a_id: 'retired-source-id',
      cluster_a_label: 'Source',
    });
  });

  it('rg-002: a suggestion merge is ONE request — no separate structural merge hop', async () => {
    // Predicted first failure if the two-hop sequence returns: mergeCluster is
    // called and the assertion below sees 1 instead of 0.
    const { result, invalidateQueries, onMergeSuccess } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.mergeCluster).not.toHaveBeenCalled();
    expect(recognitionApi.acceptMergeSuggestion).toHaveBeenCalledTimes(1);
    expect(recognitionApi.acceptMergeSuggestion).toHaveBeenCalledWith({
      suggestionId: 'sug-merge-1',
      targetClusterId: 'target-c',
    });
    expect(onMergeSuccess).toHaveBeenCalledWith({
      source_id: 'retired-source-id',
      source_label: 'Source',
      target_id: 'target-c',
      target_label: 'Target',
      identities_moved: 1,
      moved_identity_ids: ['id-1'],
      target_identity_count: 0,
    });
  });

  it('the revert set comes from the server, not from a client guess', async () => {
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue({
      ...acceptedMergeSuggestion,
      cluster_a_id: 'retired-source-id',
      moved_identity_ids: [],
    });
    const { result, onMergeSuccess, invalidateQueries } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    // An empty revert set is a valid outcome (already-accepted replay), not an error.
    const applied = vi.mocked(onMergeSuccess).mock.calls[0][0];
    expect(applied.moved_identity_ids).toEqual([]);
    expect(applied.identities_moved).toBe(0);
  });

  it('a response whose topology matches neither cluster fails loudly (rg-015)', async () => {
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockResolvedValue({
      ...acceptedMergeSuggestion,
      source_cluster_id: 'a-third-cluster',
    });
    const { result, onError, onMergeSuccess } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(onMergeSuccess).not.toHaveBeenCalled();
  });

  it('uses the plain merge endpoint when no suggestion is threaded', async () => {
    const { result, invalidateQueries } = renderLabelMutations();

    result.current.merge('target-c', 'Target');

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(recognitionApi.mergeCluster).toHaveBeenCalledWith('panel-c', 'target-c', 'Target', undefined);
    expect(recognitionApi.acceptMergeSuggestion).not.toHaveBeenCalled();
  });

  it('an atomic accept failure applies nothing and claims nothing (rg-002)', async () => {
    // Pre-atomic, this path reported "Merged, but the suggestion could not be
    // cleared" and applied hop-1 state. With one transaction there is no such
    // half-state: nothing is applied and no partial-success copy exists.
    vi.mocked(recognitionApi.acceptMergeSuggestion).mockRejectedValue(new Error('accept failed'));
    const { result, invalidateQueries, onError, onMergeSuccess } = renderLabelMutations();

    result.current.merge('target-c', 'Target', undefined, 'sug-merge-1');

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(vi.mocked(onError).mock.calls[0][0]).not.toContain('Merged, but');
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
      cluster_id: 'panel-c',
      label: 'Renamed',
    } as never);
    const { result, invalidateQueries, queryClient } = renderLabelMutations();
    const nameKey = queryKeys.suggestions.namePending();
    const topKey = queryKeys.clusters.topUnlabeled('t');
    queryClient.setQueryData<PendingNameSuggestionsResponse>(nameKey, {
      suggestions: [
        {
          id: 'name-1',
          cluster_id: 'panel-c',
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
          id: 'panel-c',
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
          id: 'retired-source-id',
          tenant_id: 't',
          label: null,
          is_labeled: false,
          is_auto_label: true,
          identity_count: 2,
          user_confirmed: false,
          representatives: [],
        },
        {
          id: 'panel-c',
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
    ).toEqual(['panel-c', 'target-c']);
  });
});

describe('revertMerge error path (FEBT1-LD-04)', () => {
  const renderRevert = () => {
    const onError = vi.fn();
    const onAbort = vi.fn();
    const invalidateQueries = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useClusterLabelMutations({
          clusterId: 'panel-c',
          currentLabel: 'Source',
          derivedLabel: null,
          onError,
          onAbort,
          cancelIdentityQueries: vi.fn().mockResolvedValue(undefined),
          invalidateQueries,
          updateCachedClusterLabel: vi.fn(),
        }),
      { wrapper },
    );
    return { result, onError, onAbort };
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('never renders the raw wire message — the body preview must not reach the UI', async () => {
    const secret = 'stack-trace: /var/www/wp-content/plugins/secret.php line 42';
    vi.mocked(recognitionApi.revertMergeCluster).mockRejectedValue(
      new HTTPError({
        status: 500,
        retryAfterSeconds: undefined,
        endpoint: '/acx/v1/recognition/clusters/panel-c/revert',
        bodyPreview: secret,
        message: `Request to /acx/v1/recognition/clusters/panel-c/revert failed (500): ${secret}`,
      }),
    );
    const { result, onError } = renderRevert();

    result.current.revertMerge(mergeResponse);

    await waitFor(() => expect(onError).toHaveBeenCalled());
    const message = vi.mocked(onError).mock.calls[0][0];
    expect(message).toBe('An unexpected error occurred. Please try again.');
    expect(message).not.toContain(secret);
    expect(message).not.toContain('/acx/v1/');
  });

  it('maps auth expiry to the session-recovery copy, not a generic failure', async () => {
    vi.mocked(recognitionApi.revertMergeCluster).mockRejectedValue(
      new AuthExpiredError({ endpoint: '/revert', status: 403 }),
    );
    const { result, onError } = renderRevert();

    result.current.revertMerge(mergeResponse);

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(vi.mocked(onError).mock.calls[0][0]).toBe(SPA_SESSION_EXPIRED_COPY.sessionExpired);
  });

  it('maps the typed interactive-budget timeout to the timeout copy', async () => {
    vi.mocked(recognitionApi.revertMergeCluster).mockRejectedValue(
      createClusterMutationTimeoutError('revert'),
    );
    const { result, onError } = renderRevert();

    result.current.revertMerge(mergeResponse);

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(vi.mocked(onError).mock.calls[0][0]).toBe('Save is taking too long. Please try again.');
  });

  it('a user cancel is silent: onAbort fires and no error copy is surfaced', async () => {
    vi.mocked(recognitionApi.revertMergeCluster).mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError'),
    );
    const { result, onError, onAbort } = renderRevert();

    result.current.revertMerge(mergeResponse);

    await waitFor(() => expect(onAbort).toHaveBeenCalledTimes(1));
    expect(onError).not.toHaveBeenCalled();
  });

  it('a non-Error throw does not reach the UI as text', async () => {
    vi.mocked(recognitionApi.revertMergeCluster).mockRejectedValue('boom');
    const { result, onError } = renderRevert();

    result.current.revertMerge(mergeResponse);

    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect(vi.mocked(onError).mock.calls[0][0]).toBe('An unexpected error occurred. Please try again.');
  });
});
