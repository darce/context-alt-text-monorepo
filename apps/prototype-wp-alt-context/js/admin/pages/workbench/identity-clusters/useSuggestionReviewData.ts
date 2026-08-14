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
  /** Slice-5: ReviewQueue bulk hook assigns these for single↔bulk ordering. */
  const awaitBulkIdleOrFlushRef = React.useRef<(() => Promise<void>) | null>(null);
  const isBulkActiveRef = React.useRef(false);

  const {
    assignmentQuery,
    mergeQuery,
    nameQuery,
    topUnlabeledQuery,
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
    commitOneNow,
    isSuggestionHeld,
  } = useSuggestionReviewMutations({
    queryClient,
    bulkActionRef,
    awaitBulkIdleOrFlushRef,
    isBulkActiveRef,
  });

  // COR-3 (rg-015): no authoritative backlog total exists; count loaded suggestions.
  const assignmentCount = assignmentSuggestions?.length ?? 0;
  const hasNoSuggestionData = !assignmentQuery.data && !mergeQuery.data;
  // Global initial-failure / isError stay assignment+merge only: a top-unlabeled
  // outage must not blank the rest of the queue (partial degrade — AGT-10).
  const hasInitialFailure =
    (assignmentQuery.failureCount > 0 || mergeQuery.failureCount > 0) && hasNoSuggestionData;
  const isLoading =
    !hasInitialFailure &&
    ((assignmentQuery.isLoading && !assignmentQuery.data) ||
      (mergeQuery.isLoading && !mergeQuery.data));
  const isError = assignmentQuery.isError && mergeQuery.isError && hasNoSuggestionData;
  // Separate flag so CLUSTER cards / unlabeled section can error+retry without
  // folding into isError (which blanks every control via isErrorBranch).
  const isTopUnlabeledError = topUnlabeledQuery.isError;
  const failureCount = Math.max(
    assignmentQuery.failureCount,
    mergeQuery.failureCount,
    topUnlabeledQuery.failureCount,
  );
  const tenantId = getConfig().tenant_id;

  // BR-15: do NOT fold isHoldActive into a global pending flag — that disabled every
  // card during a hold and made §3 flush-on-next-action production-dead.
  // Slice-5 bulk pending is applied per-card in ReviewQueue via bulk.isBulkActive
  // (refs are not reactive — do not read bulkActionRef/isBulkActiveRef here).
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

  const setBulkActionActive = React.useCallback((active: boolean): void => {
    bulkActionRef.current = active;
  }, []);

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
    isTopUnlabeledError,
    failureCount,
    tenantId,
    isAnyMutationPending,
    isCardPending,
    bulkActionClusterId,
    setBulkActionClusterId,
    bulkActionRef,
    setBulkActionActive,
    awaitBulkIdleOrFlushRef,
    isBulkActiveRef,
    refetchAssignment: () => assignmentQuery.refetch(),
    refetchMerge: () => mergeQuery.refetch(),
    refetchName: () => nameQuery.refetch(),
    refetchTopUnlabeled: () => topUnlabeledQuery.refetch(),
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
    commitOneNow,
    isSuggestionHeld,
  };
};

export { SUGGESTION_PAGE_SIZE };
