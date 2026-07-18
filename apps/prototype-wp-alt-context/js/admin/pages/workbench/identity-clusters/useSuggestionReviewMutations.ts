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
} from '../../../api/recognition';
import { invalidateSuggestionProjection } from './suggestionProjection';
import type { SuggestionReviewPage } from './useSuggestionReviewQueries';

interface UseSuggestionReviewMutationsOptions {
  queryClient: QueryClient;
  bulkActionRef: React.MutableRefObject<boolean>;
}

const reviewPageKey = queryKeys.suggestions.projection.reviewPage(0);

export const useSuggestionReviewMutations = ({ queryClient, bulkActionRef }: UseSuggestionReviewMutationsOptions) => {
  const removePendingSuggestionFromCache = (suggestionId: string) => {
    queryClient.setQueryData<SuggestionReviewPage | undefined>(reviewPageKey, (current) => {
      if (!current) {
        return current;
      }
      const filtered = current.items.filter((item) => item.suggestionId !== suggestionId);
      if (filtered.length === current.items.length) {
        return current;
      }
      // COR-3 (rg-015): no envelope total to decrement; the loaded count follows items.
      return { ...current, items: filtered };
    });
  };

  const invalidateSuggestionQueries = () => {
    void invalidateSuggestionProjection(queryClient);
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
  };

  const invalidateMediaIdentities = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities() });
  };

  const acceptMutation = useMutation({
    mutationFn: acceptSuggestion,
    onMutate: async (suggestionId: string) => {
      await queryClient.cancelQueries({ queryKey: reviewPageKey });
      const previous = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] accept failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(reviewPageKey, context.previous);
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
      await queryClient.cancelQueries({ queryKey: reviewPageKey });
      const previous = queryClient.getQueryData<SuggestionReviewPage>(reviewPageKey);
      removePendingSuggestionFromCache(suggestionId);
      return { previous };
    },
    onError: (error, _suggestionId, context) => {
      console.warn('[SuggestionReviewPanel] reject failed, restoring cache:', error);
      if (context?.previous) {
        queryClient.setQueryData(reviewPageKey, context.previous);
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
      void invalidateSuggestionProjection(queryClient);
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
