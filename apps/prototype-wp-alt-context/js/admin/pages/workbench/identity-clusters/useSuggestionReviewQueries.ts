import { useQuery } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import {
  fetchTopUnlabeledClusters,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
} from '../../../api/recognition';
import type { DataSource } from '../../../api/recognition/types';
import { buildSuggestionReviewItems } from './suggestionReviewItems';
import { projectReviewQueue, type ProjectedSuggestion } from './suggestionProjection';

export const SUGGESTION_PAGE_SIZE = 25;
const TOP_UNLABELED_LIMIT = 20;

/**
 * Cached review-queue page: adapted ProjectedSuggestion rows + honest envelope dataSource.
 * Adapter lives in queryFn so optimistic filters match on suggestionId (PR-20).
 * Live path uses projectReviewQueue (BR-23) — adapt + human-label filter + sort — so
 * unit tests of projectReviewQueue exercise the same composition as production.
 */
export interface SuggestionReviewPage {
  items: ProjectedSuggestion[];
  /** From envelope only — never defaulted (rg-015). */
  dataSource: DataSource | undefined;
}

export const useSuggestionReviewQueries = () => {
  const tenantId = getConfig().tenant_id ?? '';

  const assignmentQuery = useQuery({
    queryKey: queryKeys.suggestions.projection.reviewPage(0),
    queryFn: async (): Promise<SuggestionReviewPage> => {
      const response = await fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0);
      return {
        // BR-23: single projection def — same adapt/filter/sort as projectReviewQueue tests.
        items: projectReviewQueue(response.suggestions),
        dataSource: response.data_source,
      };
    },
    refetchInterval: false,
    retry: false,
  });

  const mergeQuery = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: () => fetchPendingMergeSuggestions(10, 0),
    refetchInterval: false,
    retry: false,
  });

  const nameQuery = useQuery({
    queryKey: queryKeys.suggestions.namePending(),
    queryFn: () => fetchPendingNameSuggestions(0, SUGGESTION_PAGE_SIZE, 0),
    refetchInterval: false,
    retry: false,
  });

  const topUnlabeledQuery = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: () => fetchTopUnlabeledClusters(tenantId, TOP_UNLABELED_LIMIT),
    enabled: tenantId !== '',
    staleTime: 60000,
    refetchOnMount: 'always',
    retry: false,
  });

  const assignmentSuggestions = assignmentQuery.data?.items;

  return {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    assignmentSuggestions,
    assignmentDataSource: assignmentQuery.data?.dataSource,
    mergeSuggestions: mergeQuery.data?.suggestions ?? [],
    nameSuggestions: nameQuery.data?.suggestions ?? [],
    nameDataSource: nameQuery.data?.data_source,
    topUnlabeledClusters: topUnlabeledQuery.data?.clusters ?? [],
    topUnlabeledTotal: topUnlabeledQuery.data?.total,
    topUnlabeledTruncated: topUnlabeledQuery.data?.truncated === true,
    topUnlabeledHasClusters: topUnlabeledQuery.data?.has_clusters,
    topUnlabeledDataSource: topUnlabeledQuery.data?.data_source,
    reviewItems: buildSuggestionReviewItems(assignmentSuggestions),
  };
};
