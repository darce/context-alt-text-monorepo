import React from 'react';
import { useMutation, type QueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import {
  acceptMergeSuggestion,
  acceptNameSuggestion,
  acceptSuggestion,
  bulkAcceptSuggestions,
  rejectMergeSuggestion,
  rejectNameSuggestion,
  rejectSuggestion,
  type PendingSuggestionsResponse,
} from '../../../api/recognition';

interface UseSuggestionReviewMutationsOptions {
  queryClient: QueryClient;
  bulkActionRef: React.MutableRefObject<boolean>;
}

export const useSuggestionReviewMutations = ({ queryClient, bulkActionRef }: UseSuggestionReviewMutationsOptions) => {
  const removePendingSuggestionFromCache = (suggestionId: string) => {
    queryClient.setQueryData<PendingSuggestionsResponse | undefined>(queryKeys.suggestions.pending(), (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.suggestions.filter((suggestion) => suggestion.id !== suggestionId);
      if (filtered.length === current.suggestions.length) {
        return current;
      }
      // COR-3 (rg-015): no envelope total to decrement; the loaded count follows suggestions.
      return { ...current, suggestions: filtered };
    });
  };

  const invalidateSuggestionQueries = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.pending() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  };

  const invalidateMediaIdentities = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  };

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
        invalidateMediaIdentities();
      }
    },
  });

  const acceptMergeMutation = useMutation({
    mutationFn: acceptMergeSuggestion,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.suggestions.mergePending() });
      invalidateMediaIdentities();
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

  return {
    mutations: {
      accept: acceptMutation,
      reject: rejectMutation,
      acceptMerge: acceptMergeMutation,
      rejectMerge: rejectMergeMutation,
      acceptName: acceptNameMutation,
      rejectName: rejectNameMutation,
      bulkAccept: bulkAcceptMutation,
    },
    invalidateSuggestionQueries,
    invalidateMediaIdentities,
  };
};
