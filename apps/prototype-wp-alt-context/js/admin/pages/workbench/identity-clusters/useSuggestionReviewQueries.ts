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
import { installTopUnlabeledErrorLatch } from '../../../utils/topUnlabeledErrorLatch';
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
  // Idempotent: the app QueryClient installed it at creation; any other client installs here.
  const settledTopUnlabeledErrors = installTopUnlabeledErrorLatch(queryClient);

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
        page.items.map((item) => item.clusterId),
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

  // UXREC-1-DEMO-02: no per-query `retry` override. The app QueryClient default
  // (appQueryClient.ts) owns it — openCooldownFromError + shouldRetryRequest —
  // so a plain 500 / 4xx / auth expiry is still never retried (E21-14 intent),
  // while one timeout or transport blip no longer flips the queue to role=alert
  // before a bounded, backed-off retry has run (PERC-07, RES-06). REF-19: do
  // not re-declare a local retry function; it would skip the cooldown seam.
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
  });

  // RLSE-04 / REF-19: RQ v5 clears error + status on a no-data refetch.
  // Keep a settled outage through manual and background retries, but leave
  // the first load's automatic retries silent (errorUpdateCount is still 0).
  const cachedTopUnlabeledQuery = queryClient.getQueryCache().get(
    queryClient.defaultQueryOptions({ queryKey: queryKeys.clusters.topUnlabeled(tenantId) }).queryHash,
  );
  // UXREC-1-DEMOQ-G1-F1: offline (networkMode 'online') parks the same reset
  // refetch at fetchStatus 'paused', so the hold spans paused as well as
  // fetching — otherwise the queue reads as drained mid-outage.
  const isTopUnlabeledOutageHeld =
    topUnlabeledQuery.data === undefined &&
    topUnlabeledQuery.errorUpdateCount > 0 &&
    (topUnlabeledQuery.isFetching || topUnlabeledQuery.isPaused);
  const topUnlabeledOutage = {
    // INT-08: busy only while a request is in flight; a paused one is not.
    isRetrying: isTopUnlabeledOutageHeld && topUnlabeledQuery.isFetching,
    isError: topUnlabeledQuery.isError || isTopUnlabeledOutageHeld,
    // Preserve the class (especially auth expiry) while RQ temporarily has no error.
    error:
      topUnlabeledQuery.error ??
      (isTopUnlabeledOutageHeld && cachedTopUnlabeledQuery
        ? settledTopUnlabeledErrors.get(cachedTopUnlabeledQuery) ?? null
        : null),
  };

  const assignmentSuggestions = assignmentQuery.data?.items;

  return {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    topUnlabeledOutage,
    assignmentSuggestions,
    assignmentDataSource: assignmentQuery.data?.dataSource,
    mergeSuggestions: mergeQuery.data?.suggestions ?? [],
    nameSuggestions: nameQuery.data?.suggestions ?? [],
    nameDataSource: nameQuery.data?.data_source,
    topUnlabeledClusters: topUnlabeledQuery.data?.clusters ?? [],
    topUnlabeledTotal: topUnlabeledQuery.data?.total,
    topUnlabeledTruncated: topUnlabeledQuery.data?.truncated === true,
    topUnlabeledRepairPending: topUnlabeledQuery.data?.repair_pending === true,
    topUnlabeledHasClusters: topUnlabeledQuery.data?.has_clusters,
    topUnlabeledDataSource: topUnlabeledQuery.data?.data_source,
    reviewItems: buildSuggestionReviewItems(assignmentSuggestions),
  };
};
