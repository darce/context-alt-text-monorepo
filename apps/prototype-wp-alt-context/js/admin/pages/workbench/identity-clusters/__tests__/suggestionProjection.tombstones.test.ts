import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { DATA_SOURCE } from '../../../../api/recognition/types';
import type {
  PendingNameSuggestionsResponse,
  TopUnlabeledClustersResponse,
} from '../../../../api/recognition/types';
import {
  applyAssignmentTombstones,
  applyNameTombstones,
  applyTopUnlabeledTombstones,
  REVIEW_DROP_SCOPE,
  tombstoneReviewGroup,
  type ProjectedSuggestion,
} from '../suggestionProjection';

const item = (
  overrides: Partial<ProjectedSuggestion> & Pick<ProjectedSuggestion, 'suggestionId'>,
): ProjectedSuggestion => ({
  identityId: `identity-${overrides.suggestionId}`,
  clusterId: 'cluster-1',
  label: 'Alice',
  similarity: 0.9,
  ...overrides,
});

const cluster = (id: string) => ({
  id,
  tenant_id: 'test-tenant',
  label: null,
  is_labeled: false,
  is_auto_label: true,
  identity_count: 2,
  user_confirmed: false,
  representatives: [],
});

describe('apply*Tombstones selects (R5-05)', () => {
  it('R5-05: applyTopUnlabeledTombstones decrements total and passes has_clusters through', () => {
    const queryClient = new QueryClient();
    tombstoneReviewGroup(queryClient, 'cluster-1', [REVIEW_DROP_SCOPE.TOP_UNLABELED]);
    const page: TopUnlabeledClustersResponse = {
      clusters: [cluster('cluster-1'), cluster('cluster-2')],
      limit: 20,
      total: 12,
      truncated: true,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    };

    const next = applyTopUnlabeledTombstones(queryClient, page);

    expect(next.clusters.map((row) => row.id)).toEqual(['cluster-2']);
    expect(next.total).toBe(11);
    expect(next.has_clusters).toBe(true);
  });

  it('R5-05: applyTopUnlabeledTombstones keeps has_clusters when the served page is emptied', () => {
    const queryClient = new QueryClient();
    tombstoneReviewGroup(queryClient, 'cluster-1', [REVIEW_DROP_SCOPE.TOP_UNLABELED]);
    tombstoneReviewGroup(queryClient, 'cluster-2', [REVIEW_DROP_SCOPE.TOP_UNLABELED]);
    const page: TopUnlabeledClustersResponse = {
      clusters: [cluster('cluster-1'), cluster('cluster-2')],
      limit: 20,
      total: 12,
      truncated: true,
      has_clusters: true,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    };

    const next = applyTopUnlabeledTombstones(queryClient, page);

    expect(next).toEqual({
      ...page,
      clusters: [],
      total: 10,
      has_clusters: true,
    });
  });

  it('R5-05: applyAssignmentTombstones drops tombstoned targets and leaves siblings', () => {
    const queryClient = new QueryClient();
    tombstoneReviewGroup(queryClient, 'cluster-1', [REVIEW_DROP_SCOPE.ASSIGNMENT]);
    const page = {
      items: [
        item({ suggestionId: 'sugg-1', clusterId: 'cluster-1' }),
        item({ suggestionId: 'sugg-2', clusterId: 'cluster-2' }),
      ],
    };

    const next = applyAssignmentTombstones(queryClient, page);

    expect(next.items.map((row) => row.suggestionId)).toEqual(['sugg-2']);
  });

  it('R5-05: applyNameTombstones drops tombstoned names and leaves siblings', () => {
    const queryClient = new QueryClient();
    tombstoneReviewGroup(queryClient, 'cluster-1', [REVIEW_DROP_SCOPE.NAME]);
    const page: PendingNameSuggestionsResponse = {
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
          id: 'name-2',
          cluster_id: 'cluster-2',
          suggested_name: 'Bea',
          confidence_score: 0.8,
          source: 'test',
          created_at: '2026-01-01T00:00:00Z',
          expires_at: null,
        },
      ],
      limit: 25,
      offset: 0,
      data_source: DATA_SOURCE.LOCAL_PROJECTION,
    };

    const next = applyNameTombstones(queryClient, page);

    expect(next.suggestions.map((row) => row.id)).toEqual(['name-2']);
  });
});
