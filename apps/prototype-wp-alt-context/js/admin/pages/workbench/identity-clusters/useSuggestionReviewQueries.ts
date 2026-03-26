import { useQuery } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  type PendingSuggestionsResponse,
} from '../../../api/recognition';
import { buildSuggestionReviewItems } from './suggestionReviewItems';

export const SUGGESTION_PAGE_SIZE = 25;

export const useSuggestionReviewQueries = () => {
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

  const assignmentSuggestions = assignmentQuery.data?.suggestions;

  return {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    assignmentSuggestions,
    assignmentDataSource: assignmentQuery.data?.data_source,
    mergeSuggestions: mergeQuery.data?.suggestions ?? [],
    nameSuggestions: nameQuery.data?.suggestions ?? [],
    nameDataSource: nameQuery.data?.data_source,
    reviewItems: buildSuggestionReviewItems(assignmentSuggestions),
  };
};

export type { PendingSuggestionsResponse };
