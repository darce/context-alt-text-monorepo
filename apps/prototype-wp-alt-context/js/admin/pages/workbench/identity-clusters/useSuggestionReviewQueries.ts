import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

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
import {
  applyAssignmentTombstones,
  applyMergeTombstones,
  applyNameTombstones,
  applyTopUnlabeledTombstones,
  projectReviewQueue,
  pruneReviewDropTombstones,
  REVIEW_DROP_SCOPE,
  type ProjectedSuggestion,
} from './suggestionProjection';

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
  const queryClient = useQueryClient();

  const selectAssignment = useCallback(
    (page: SuggestionReviewPage) => applyAssignmentTombstones(queryClient, page),
    [queryClient],
  );
  const selectMerge = useCallback(
    (page: Awaited<ReturnType<typeof fetchPendingMergeSuggestions>>) =>
      applyMergeTombstones(queryClient, page),
    [queryClient],
  );
  const selectName = useCallback(
    (page: Awaited<ReturnType<typeof fetchPendingNameSuggestions>>) => applyNameTombstones(queryClient, page),
    [queryClient],
  );
  const selectTopUnlabeled = useCallback(
    (page: Awaited<ReturnType<typeof fetchTopUnlabeledClusters>>) =>
      applyTopUnlabeledTombstones(queryClient, page),
    [queryClient],
  );

  // QueryClient owns tombstones; it is not a fetch input (R1-15).
  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- tombstone prune reads QueryClient, not a fetch key
  const assignmentQuery = useQuery({
    queryKey: queryKeys.suggestions.projection.reviewPage(0),
    queryFn: async (): Promise<SuggestionReviewPage> => {
      const response = await fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0);
      const page = {
        // BR-23: single projection def — same adapt/filter/sort as projectReviewQueue tests.
        items: projectReviewQueue(response.suggestions),
        dataSource: response.data_source,
      };
      // Prune against the raw fetch only — never against already-dropped cache
      // (that would clear the tombstone before the lagged row is gone server-side).
      pruneReviewDropTombstones(
        queryClient,
        REVIEW_DROP_SCOPE.ASSIGNMENT,
        page.items.flatMap((item) => (item.sourceClusterId ? [item.sourceClusterId] : [])),
      );
      return page;
    },
    select: selectAssignment,
    refetchInterval: false,
    retry: false,
  });

  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- tombstone prune reads QueryClient, not a fetch key
  const mergeQuery = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: async () => {
      const page = await fetchPendingMergeSuggestions(10, 0);
      pruneReviewDropTombstones(
        queryClient,
        REVIEW_DROP_SCOPE.MERGE,
        page.suggestions.flatMap((item) => [item.cluster_a_id, item.cluster_b_id]),
      );
      return page;
    },
    select: selectMerge,
    refetchInterval: false,
    retry: false,
  });

  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- tombstone prune reads QueryClient, not a fetch key
  const nameQuery = useQuery({
    queryKey: queryKeys.suggestions.namePending(),
    queryFn: async () => {
      const page = await fetchPendingNameSuggestions(0, SUGGESTION_PAGE_SIZE, 0);
      pruneReviewDropTombstones(
        queryClient,
        REVIEW_DROP_SCOPE.NAME,
        page.suggestions.map((item) => item.cluster_id),
      );
      return page;
    },
    select: selectName,
    refetchInterval: false,
    retry: false,
  });

  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- tombstone prune reads QueryClient, not a fetch key
  const topUnlabeledQuery = useQuery({
    queryKey: queryKeys.clusters.topUnlabeled(tenantId),
    queryFn: async () => {
      const page = await fetchTopUnlabeledClusters(tenantId, TOP_UNLABELED_LIMIT);
      pruneReviewDropTombstones(
        queryClient,
        REVIEW_DROP_SCOPE.TOP_UNLABELED,
        page.clusters.map((cluster) => cluster.id),
      );
      return page;
    },
    select: selectTopUnlabeled,
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
