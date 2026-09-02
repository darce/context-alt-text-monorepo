import React from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import { fetchPendingMergeSuggestions } from '../../../api/recognition';
import type { PendingMergeSuggestionsResponse } from '../../../api/recognition/types';
import {
  applyMergeTombstones,
  pruneReviewDropTombstones,
  REVIEW_DROP_SCOPE,
} from './suggestionProjection';
import {
  useSuggestionReviewMutations,
  type SuggestionCommitKind,
} from './useSuggestionReviewMutations';

/** Shared react-query key with the review-queue merge page so the cache is reused. */
export const PENDING_MERGE_TWIN_LIMIT = 50;

export type PendingMergeTwinPage = PendingMergeSuggestionsResponse & {
  /** Present only when the envelope still forwards an authoritative total. */
  total?: number;
};

export const isPendingMergePageTruncated = (
  page: Pick<PendingMergeTwinPage, 'suggestions' | 'total'>,
): boolean => {
  const loaded = page.suggestions.length;
  if (typeof page.total === 'number') {
    return page.total > loaded;
  }
  return loaded >= PENDING_MERGE_TWIN_LIMIT;
};

export const usePendingMergeTwins = () => {
  const queryClient = useQueryClient();
  const bulkActionRef = React.useRef(false);
  const awaitBulkIdleOrFlushRef = React.useRef<(() => Promise<void>) | null>(null);
  const isBulkActiveRef = React.useRef(false);

  const selectMerge = React.useCallback(
    (page: Awaited<ReturnType<typeof fetchPendingMergeSuggestions>>) =>
      applyMergeTombstones(queryClient, page),
    [queryClient],
  );

  // eslint-disable-next-line @tanstack/query/exhaustive-deps -- tombstone prune reads QueryClient, not a fetch key
  const mergeQuery = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: async () => {
      const page = await fetchPendingMergeSuggestions(PENDING_MERGE_TWIN_LIMIT, 0);
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

  const {
    scheduleAcceptMerge,
    scheduleRejectMerge,
    isCardActionsDisabled,
    isCommitting,
    mutations,
  } = useSuggestionReviewMutations({
    queryClient,
    bulkActionRef,
    awaitBulkIdleOrFlushRef,
    isBulkActiveRef,
  });

  const mergeSuggestions = mergeQuery.data?.suggestions ?? [];
  const truncated = mergeQuery.data != null && isPendingMergePageTruncated(mergeQuery.data);
  const acceptMergePending = mutations.acceptMerge.isPending;
  const rejectMergePending = mutations.rejectMerge.isPending;

  const isCardPending = React.useCallback(
    (suggestionId: string, kinds: readonly SuggestionCommitKind[]): boolean => {
      if (acceptMergePending || rejectMergePending || isCommitting) {
        return true;
      }
      return isCardActionsDisabled(suggestionId, kinds);
    },
    [acceptMergePending, isCardActionsDisabled, isCommitting, rejectMergePending],
  );

  return {
    mergeSuggestions,
    truncated,
    scheduleAcceptMerge,
    scheduleRejectMerge,
    isCardPending,
  };
};
