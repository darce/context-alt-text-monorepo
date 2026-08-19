/**
 * Hook for label-focused cluster mutations (rename, merge, revert).
 */

import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  acceptSuggestion,
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  type MergeClusterResponse,
} from '../../../api/recognition';
import {
  getClusterMutationErrorMessage,
  getProjectionNotReadyMessage,
  isAbortError,
  isProjectionNotReadyError,
} from './clusterMutationUtils';
import { useOptionalMergeSurvivors } from './MergeSurvivorContext';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  removePendingSuggestionFromCache,
  REVIEW_DROP_MODE,
} from './suggestionProjection';

interface UseClusterLabelMutationsOptions {
  clusterId: string | null;
  currentLabel: string | null;
  derivedLabel: string | null;
  onRenameSuccess?: (newLabel: string) => void;
  onMergeSuccess?: (result: MergeClusterResponse) => void;
  onRevertSuccess?: () => void;
  onError?: (error: string) => void;
  onAbort?: () => void;
  cancelIdentityQueries: () => Promise<void>;
  invalidateQueries: () => void;
  updateCachedClusterLabel: (targetClusterId: string, nextLabel: string) => void;
}

export const useClusterLabelMutations = ({
  clusterId,
  currentLabel,
  derivedLabel,
  onRenameSuccess,
  onMergeSuccess,
  onRevertSuccess,
  onError,
  onAbort,
  cancelIdentityQueries,
  invalidateQueries,
  updateCachedClusterLabel,
}: UseClusterLabelMutationsOptions) => {
  const queryClient = useQueryClient();
  const mergeSurvivors = useOptionalMergeSurvivors();
  const renameMutation = useMutation({
    mutationKey: ['rename-cluster', clusterId],
    mutationFn: ({ label, signal }: { label: string; signal?: AbortSignal }) =>
      updateClusterLabel(clusterId!, label, signal),
    // Don't retry on client errors like 409 Conflict (duplicate label)
    retry: false,
    onMutate: async ({ label }) => {
      if (!clusterId) {
        return;
      }
      await cancelIdentityQueries();
      updateCachedClusterLabel(clusterId, label);
    },
    onSuccess: (_data, variables) => {
      const updatedLabel = variables.label;
      if (clusterId) {
        updateCachedClusterLabel(clusterId, updatedLabel);
        dropClusterFromReviewCaches(queryClient, clusterId, { mode: REVIEW_DROP_MODE.LABEL });
      }
      invalidateReviewCachesWithoutRefetch(queryClient);
      invalidateQueries();
      onRenameSuccess?.(updatedLabel);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        invalidateQueries();
        onAbort?.();
        return;
      }
      invalidateQueries();
      const message = err instanceof Error ? err.message : String(err);
      if (isProjectionNotReadyError(message)) {
        onError?.(getProjectionNotReadyMessage());
      } else if (message.includes('409')) {
        onError?.(__('Label already exists. Use the dropdown to merge.', 'alt-context'));
      } else {
        onError?.(message);
      }
    },
  });

  const mergeMutation = useMutation({
    mutationKey: ['merge-cluster', clusterId],
    mutationFn: async ({
      targetClusterId,
      targetLabel,
      signal,
      suggestionId,
    }: {
      targetClusterId: string;
      targetLabel?: string;
      signal?: AbortSignal;
      suggestionId?: string;
    }) => {
      if (!clusterId) {
        return Promise.reject(new Error(__('Cannot merge: no cluster ID', 'alt-context')));
      }
      // Structural merge first; then resolve the pending row by id when confirm threaded it (BR-16).
      const result = await mergeCluster(clusterId, targetClusterId, targetLabel, signal);
      if (suggestionId) {
        await acceptSuggestion(suggestionId);
      }
      return result;
    },
    // Don't retry on client errors
    retry: false,
    onSuccess: (result, variables) => {
      // Authoritative survivor from MergeClusterResponse (source retired → target survives).
      if (result.source_id && result.target_id) {
        mergeSurvivors?.recordMergeSurvivor(result.source_id, result.target_id);
      }
      if (clusterId) {
        updateCachedClusterLabel(clusterId, result.target_label ?? '');
      }
      if (typeof result.source_id === 'string' && result.source_id !== '') {
        dropClusterFromReviewCaches(queryClient, result.source_id, { mode: REVIEW_DROP_MODE.MERGE });
      }
      // L1V-03: drop accepted pending row before invalidate so review queue is not stale until refetch.
      if (variables.suggestionId) {
        removePendingSuggestionFromCache(queryClient, variables.suggestionId);
      }
      invalidateReviewCachesWithoutRefetch(queryClient);
      invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: unknown, variables) => {
      // L1V-02: hop-1 merge may have committed before hop-2 accept failed — always refresh caches.
      invalidateQueries();
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      onError?.(getClusterMutationErrorMessage(err, variables.targetLabel ?? 'that label'));
    },
  });

  const revertMergeMutation = useMutation({
    mutationFn: (payload: MergeClusterResponse) =>
      revertMergeCluster({
        targetClusterId: payload.target_id,
        movedIdentityIds: payload.moved_identity_ids,
        sourceLabel: payload.source_label ?? currentLabel ?? derivedLabel ?? null,
      }),
    // Don't retry on client errors
    retry: false,
    onSuccess: () => {
      invalidateQueries();
      onRevertSuccess?.();
    },
    onError: (err: Error) => {
      onError?.(err.message);
    },
  });

  return {
    rename: (label: string, signal?: AbortSignal) => renameMutation.mutate({ label, signal }),
    merge: (
      targetClusterId: string,
      targetLabel?: string,
      signal?: AbortSignal,
      suggestionId?: string,
    ) => mergeMutation.mutate({ targetClusterId, targetLabel, signal, suggestionId }),
    revertMerge: revertMergeMutation.mutate,
    isRenaming: renameMutation.isPending,
    isMerging: mergeMutation.isPending,
    isReverting: revertMergeMutation.isPending,
  };
};
