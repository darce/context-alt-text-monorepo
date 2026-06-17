import React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { SUGGESTION_PAGE_SIZE, useSuggestionReviewQueries } from './useSuggestionReviewQueries';
import { useSuggestionReviewMutations } from './useSuggestionReviewMutations';

export const useSuggestionReviewData = () => {
  const queryClient = useQueryClient();
  const [bulkActionClusterId, setBulkActionClusterId] = React.useState<string | null>(null);
  const bulkActionRef = React.useRef(false);

  const {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    assignmentSuggestions,
    assignmentDataSource,
    mergeSuggestions,
    nameSuggestions,
    nameDataSource,
    topUnlabeledHasClusters,
    topUnlabeledDataSource,
    reviewItems,
  } = useSuggestionReviewQueries();

  const { mutations, invalidateSuggestionQueries, invalidateMediaIdentities } = useSuggestionReviewMutations({
    queryClient,
    bulkActionRef,
  });

  // COR-3 (rg-015): no authoritative backlog total exists; count loaded suggestions.
  const assignmentCount = assignmentSuggestions?.length ?? 0;
  const hasNoSuggestionData = !assignmentQuery.data && !mergeQuery.data;
  const hasInitialFailure = (assignmentQuery.failureCount > 0 || mergeQuery.failureCount > 0) && hasNoSuggestionData;
  const isLoading =
    !hasInitialFailure &&
    ((assignmentQuery.isLoading && !assignmentQuery.data) || (mergeQuery.isLoading && !mergeQuery.data));
  const isError = assignmentQuery.isError && mergeQuery.isError && hasNoSuggestionData;
  const failureCount = Math.max(assignmentQuery.failureCount, mergeQuery.failureCount);
  const tenantId = getConfig().tenant_id;
  const isAnyMutationPending =
    mutations.accept.isPending ||
    mutations.reject.isPending ||
    mutations.acceptMerge.isPending ||
    mutations.rejectMerge.isPending ||
    bulkActionClusterId !== null;

  return {
    assignmentSuggestions,
    assignmentDataSource,
    mergeSuggestions,
    nameSuggestions,
    nameDataSource,
    topUnlabeledHasClusters,
    topUnlabeledDataSource,
    reviewItems,
    assignmentCount,
    hasInitialFailure,
    isLoading,
    isError,
    failureCount,
    tenantId,
    isAnyMutationPending,
    bulkActionClusterId,
    setBulkActionClusterId,
    bulkActionRef,
    refetchAssignment: () => assignmentQuery.refetch(),
    refetchMerge: () => mergeQuery.refetch(),
    refetchName: () => nameQuery.refetch(),
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
    mutations,
  };
};

export { SUGGESTION_PAGE_SIZE };
