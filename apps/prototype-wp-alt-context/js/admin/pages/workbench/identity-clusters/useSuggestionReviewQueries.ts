import { useQuery } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { queryKeys } from '../../../api/queryKeys';
import {
  fetchTopUnlabeledClusters,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  type PendingSuggestionsResponse,
} from '../../../api/recognition';
import { buildSuggestionReviewItems } from './suggestionReviewItems';

export const SUGGESTION_PAGE_SIZE = 25;
const TOP_UNLABELED_LIMIT = 20;

export const useSuggestionReviewQueries = () => {
  const tenantId = getConfig().tenant_id ?? '';

  const assignmentQuery = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0),
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
  });

  const assignmentSuggestions = assignmentQuery.data?.suggestions;

  return {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
    assignmentSuggestions,
    assignmentDataSource: assignmentQuery.data?.data_source,
    mergeSuggestions: mergeQuery.data?.suggestions ?? [],
    nameSuggestions: nameQuery.data?.suggestions ?? [],
    nameDataSource: nameQuery.data?.data_source,
    topUnlabeledClusters: topUnlabeledQuery.data?.clusters ?? [],
    topUnlabeledTotal: topUnlabeledQuery.data?.total,
    topUnlabeledHasClusters: topUnlabeledQuery.data?.has_clusters,
    topUnlabeledDataSource: topUnlabeledQuery.data?.data_source,
    reviewItems: buildSuggestionReviewItems(assignmentSuggestions),
  };
};

export type { PendingSuggestionsResponse };
