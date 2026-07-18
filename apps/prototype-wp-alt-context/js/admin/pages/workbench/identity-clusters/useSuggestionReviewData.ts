import React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { getConfig } from '../../../api/config';
import { SUGGESTION_PAGE_SIZE, useSuggestionReviewQueries } from './useSuggestionReviewQueries';
import {
  useSuggestionReviewMutations,
  type SuggestionCommitKind,
} from './useSuggestionReviewMutations';

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

  const {
    mutations,
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
    hold,
    holdAnnounce,
    isHoldActive,
    isCommitting,
    isCardActionsDisabled,
    retryPending,
    personCommit,
    personCommitPending,
    scheduleAccept,
    scheduleReject,
    scheduleAcceptMerge,
    scheduleRejectMerge,
    scheduleAcceptName,
    scheduleRejectName,
    schedulePersonCommit,
    retryPersonCommit,
    clearPersonCommitSuccess,
    undoHold,
    retryFailure,
    setHoldPaused,
    flushHeld,
  } = useSuggestionReviewMutations({
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

  // BR-15: do NOT fold isHoldActive into a global pending flag — that disabled every
  // card during a hold and made §3 flush-on-next-action production-dead.
  const isBulkOrMutationPending =
    bulkActionClusterId !== null ||
    mutations.accept.isPending ||
    mutations.reject.isPending ||
    mutations.acceptMerge.isPending ||
    mutations.rejectMerge.isPending ||
    mutations.acceptName.isPending ||
    mutations.rejectName.isPending;

  const isAnyMutationPending = isBulkOrMutationPending || isCommitting;

  const isCardPending = React.useCallback(
    (suggestionId: string, kinds: readonly SuggestionCommitKind[]): boolean => {
      if (isBulkOrMutationPending) {
        return true;
      }
      return isCardActionsDisabled(suggestionId, kinds);
    },
    [isBulkOrMutationPending, isCardActionsDisabled],
  );

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
    isCardPending,
    bulkActionClusterId,
    setBulkActionClusterId,
    bulkActionRef,
    refetchAssignment: () => assignmentQuery.refetch(),
    refetchMerge: () => mergeQuery.refetch(),
    refetchName: () => nameQuery.refetch(),
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
    mutations,
    hold,
    holdAnnounce,
    isHoldActive,
    isCommitting,
    retryPending,
    scheduleAccept,
    scheduleReject,
    scheduleAcceptMerge,
    scheduleRejectMerge,
    scheduleAcceptName,
    scheduleRejectName,
    personCommit,
    personCommitPending,
    schedulePersonCommit,
    retryPersonCommit,
    clearPersonCommitSuccess,
    undoHold,
    retryFailure,
    setHoldPaused,
    flushHeld,
  };
};

export { SUGGESTION_PAGE_SIZE };
