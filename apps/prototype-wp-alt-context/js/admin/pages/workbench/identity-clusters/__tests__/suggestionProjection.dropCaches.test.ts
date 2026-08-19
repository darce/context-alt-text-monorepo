import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { queryKeys } from '../../../../api/queryKeys';
import { DATA_SOURCE } from '../../../../api/recognition/types';
import type {
  PendingMergeSuggestionsResponse,
  PendingNameSuggestionsResponse,
  TopUnlabeledClustersResponse,
} from '../../../../api/recognition/types';
import {
  dropClusterFromReviewCaches,
  REVIEW_DROP_MODE,
  type ProjectedSuggestion,
} from '../suggestionProjection';
import type { SuggestionReviewPage } from '../useSuggestionReviewQueries';

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);
const namePendingKey = queryKeys.suggestions.namePending();
const mergePendingKey = queryKeys.suggestions.mergePending();
const topUnlabeledKey = queryKeys.clusters.topUnlabeled('test-tenant');

const item = (overrides: Partial<ProjectedSuggestion> & Pick<ProjectedSuggestion, 'suggestionId'>): ProjectedSuggestion => ({
  identityId: `identity-${overrides.suggestionId}`,
  clusterId: 'cluster-1',
  label: 'Alice',
  similarity: 0.9,
  ...overrides,
});

const seed = (queryClient: QueryClient): void => {
  queryClient.setQueryData<SuggestionReviewPage>(reviewPageKey, {
    items: [
      item({ suggestionId: 'sugg-target', clusterId: 'cluster-1' }),
      item({ suggestionId: 'sugg-source', clusterId: 'other' }),
      item({ suggestionId: 'sugg-sibling', clusterId: 'cluster-other' }),
    ],
    dataSource: DATA_SOURCE.LOCAL_PROJECTION,
  });
  queryClient.setQueryData<PendingNameSuggestionsResponse>(namePendingKey, {
    suggestions: [
      {
        id: 'name-1',
        cluster_id: 'cluster-1',
        suggested_name: 'Alex',
        confidence_score: 0.9,
        source: 'test',
        created_at: '2026-01-01T00:00:00Z',
        expires_at: null,
      },
      {
        id: 'name-other',
        cluster_id: 'cluster-other',
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
  queryClient.setQueryData<PendingMergeSuggestionsResponse>(mergePendingKey, {
    suggestions: [
      {
        id: 'merge-live',
        cluster_a_id: 'cluster-1',
        cluster_b_id: 'cluster-other',
        similarity: 0.9,
        status: 'pending',
      },
    ],
    limit: 10,
    offset: 0,
    data_source: DATA_SOURCE.LOCAL_PROJECTION,
  });
  queryClient.setQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey, {
    clusters: [
      {
        id: 'cluster-1',
        tenant_id: 'test-tenant',
        label: null,
        is_labeled: false,
        is_auto_label: true,
        identity_count: 2,
        user_confirmed: false,
        representatives: [],
      },
      {
        id: 'cluster-other',
        tenant_id: 'test-tenant',
        label: null,
        is_labeled: false,
        is_auto_label: true,
        identity_count: 3,
        user_confirmed: false,
        representatives: [],
      },
    ],
    limit: 20,
    total: 12,
    truncated: true,
    has_clusters: true,
    data_source: DATA_SOURCE.LOCAL_PROJECTION,
  });
};

describe('dropClusterFromReviewCaches', () => {
  it('R1-26: label drop removes assignment rows whose suggested target is the labelled group', () => {
    const queryClient = new QueryClient();
    seed(queryClient);

    dropClusterFromReviewCaches(queryClient, 'cluster-1', { mode: REVIEW_DROP_MODE.LABEL });

    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((row) => row.suggestionId),
    ).toEqual(['sugg-source', 'sugg-sibling']);
  });

  it('R1-23: label drop keeps a live merge suggestion that names the labelled group', () => {
    const queryClient = new QueryClient();
    seed(queryClient);

    dropClusterFromReviewCaches(queryClient, 'cluster-1', { mode: REVIEW_DROP_MODE.LABEL });

    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions.map((row) => row.id),
    ).toEqual(['merge-live']);
  });

  it('R1-22: decrements topUnlabeled total by the rows actually removed and recomputes has_clusters', () => {
    const queryClient = new QueryClient();
    seed(queryClient);

    dropClusterFromReviewCaches(queryClient, 'cluster-1', { mode: REVIEW_DROP_MODE.LABEL });

    const top = queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey);
    expect(top?.clusters.map((cluster) => cluster.id)).toEqual(['cluster-other']);
    expect(top?.total).toBe(11);
    expect(top?.has_clusters).toBe(true);

    dropClusterFromReviewCaches(queryClient, 'cluster-other', { mode: REVIEW_DROP_MODE.LABEL });
    const empty = queryClient.getQueryData<TopUnlabeledClustersResponse>(topUnlabeledKey);
    expect(empty?.clusters).toEqual([]);
    expect(empty?.total).toBe(10);
    expect(empty?.has_clusters).toBe(false);
  });

  it('R1-23 merge path: drops mergePending rows on either side of the retired source', () => {
    const queryClient = new QueryClient();
    seed(queryClient);

    dropClusterFromReviewCaches(queryClient, 'cluster-1', { mode: REVIEW_DROP_MODE.MERGE });

    expect(
      queryClient.getQueryData<PendingMergeSuggestionsResponse>(mergePendingKey)?.suggestions,
    ).toEqual([]);
    expect(
      queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey)?.items.map((row) => row.suggestionId),
    ).toEqual(['sugg-source', 'sugg-sibling']);
  });
});
