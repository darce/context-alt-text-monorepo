import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  acceptMergeSuggestion,
  acceptNameSuggestion,
  acceptSuggestion,
  bulkAcceptSuggestions,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  fetchPendingSuggestions,
  rejectMergeSuggestion,
  rejectNameSuggestion,
  rejectSuggestion,
  type PendingSuggestionsResponse,
} from '../../../api/recognition';
import { getConfig } from '../../../api/config';
import { buildSuggestionReviewItems } from './suggestionReviewItems';

const SUGGESTION_PAGE_SIZE = 25;
export { SUGGESTION_PAGE_SIZE };

export const useSuggestionReviewData = () => {
  const queryClient = useQueryClient();
  const [bulkActionClusterId, setBulkActionClusterId] = React.useState<string | null>(null);
  const bulkActionRef = React.useRef(false);

  /* ------ cache helpers ------ */

  const removePendingSuggestionFromCache = React.useCallback(
    (suggestionId: string) => {
      queryClient.setQueryData<PendingSuggestionsResponse | undefined>(queryKeys.suggestions.pending(), (current) => {
        if (!current) return current;
        const filtered = current.suggestions.filter((suggestion) => suggestion.id !== suggestionId);
        if (filtered.length === current.suggestions.length) return current;
        return { ...current, suggestions: filtered, total: Math.max(0, current.total - 1) };
      });
    },
    [queryClient],
  );

  const invalidateSuggestionQueries = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  }, [queryClient]);

  const invalidateMediaIdentities = React.useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  }, [queryClient]);

  /* ------ queries ------ */

  const {
    data: assignmentData,
    isLoading: isAssignmentLoading,
    isError: isAssignmentError,
    refetch: refetchAssignment,
    failureCount: assignmentFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.pending(),
    queryFn: () => fetchPendingSuggestions(SUGGESTION_PAGE_SIZE, 0),
    refetchInterval: false,
    retry: false,
  });

  const {
    data: mergeData,
    isLoading: isMergeLoading,
    isError: isMergeError,
    refetch: refetchMerge,
    failureCount: mergeFailureCount,
  } = useQuery({
    queryKey: queryKeys.suggestions.mergePending(),
    queryFn: () => fetchPendingMergeSuggestions(10, 0),
    refetchInterval: false,
    retry: false,
  });

  const { data: nameData } = useQuery({
    queryKey: queryKeys.suggestions.namePending(),
    queryFn: () => fetchPendingNameSuggestions(0, SUGGESTION_PAGE_SIZE, 0),
    refetchInterval: false,
    retry: false,
  });

  /* ------ mutations ------ */

  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onMutate: async (suggestionId: string) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.suggestions.pending() });
      const previous = queryClient.getQueryData<PendingSuggestionsResponse>(queryKeys.suggestions.pending());
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] accept failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.suggestions.pending(), context.previous);
      }
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
        void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      }
    },
  });

  const acceptMergeMutation = useMutation({
    mutationFn: acceptMergeSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: rejectSuggestion,
    onMutate: async (suggestionId: string) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.suggestions.pending() });
      const previous = queryClient.getQueryData<PendingSuggestionsResponse>(queryKeys.suggestions.pending());
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] reject failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.suggestions.pending(), context.previous);
      }
    },
    onSuccess: (_data, suggestionId) => {
      removePendingSuggestionFromCache(suggestionId);
    },
    onSettled: () => {
      if (!bulkActionRef.current) {
        invalidateSuggestionQueries();
      }
    },
  });

  const rejectMergeMutation = useMutation({
    mutationFn: rejectMergeSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
    },
  });

  const acceptNameMutation = useMutation({
    mutationFn: acceptNameSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.namePending() });
    },
  });

  const rejectNameMutation = useMutation({
    mutationFn: rejectNameSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.namePending() });
    },
  });

  const bulkAcceptMutation = useMutation({
    mutationFn: bulkAcceptSuggestions,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.namePending() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
    },
  });

  /* ------ derived ------ */

  const assignmentSuggestions = assignmentData?.suggestions;
  const mergeSuggestions = mergeData?.suggestions ?? [];
  const nameSuggestions = nameData?.suggestions ?? [];
  const reviewItems = React.useMemo(() => buildSuggestionReviewItems(assignmentSuggestions), [assignmentSuggestions]);

  const assignmentCount = assignmentData?.total ?? 0;
  const loadedAssignmentCount = assignmentSuggestions?.length ?? 0;
  const hasNoSuggestionData = !assignmentData && !mergeData;
  const hasInitialFailure = (assignmentFailureCount > 0 || mergeFailureCount > 0) && hasNoSuggestionData;
  const isLoading = !hasInitialFailure && ((isAssignmentLoading && !assignmentData) || (isMergeLoading && !mergeData));
  const isError = isAssignmentError && isMergeError && hasNoSuggestionData;
  const failureCount = Math.max(assignmentFailureCount, mergeFailureCount);
  const tenantId = getConfig().tenant_id;
  const isAnyMutationPending =
    acceptMutation.isPending ||
    rejectMutation.isPending ||
    acceptMergeMutation.isPending ||
    rejectMergeMutation.isPending ||
    bulkActionClusterId !== null;

  return {
    assignmentSuggestions,
    mergeSuggestions,
    nameSuggestions,
    reviewItems,
    assignmentCount,
    loadedAssignmentCount,
    hasInitialFailure,
    isLoading,
    isError,
    failureCount,
    tenantId,
    isAnyMutationPending,
    bulkActionClusterId,
    setBulkActionClusterId,
    bulkActionRef,
    refetchAssignment,
    refetchMerge,
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
    mutations: {
      accept: acceptMutation,
      reject: rejectMutation,
      acceptMerge: acceptMergeMutation,
      rejectMerge: rejectMergeMutation,
      acceptName: acceptNameMutation,
      rejectName: rejectNameMutation,
      bulkAccept: bulkAcceptMutation,
    },
  };
};
