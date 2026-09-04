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
import { getClusterMutationErrorMessage, isAbortError } from './clusterMutationUtils';
import { useOptionalMergeSurvivors } from './MergeSurvivorContext';
import {
  dropClusterFromReviewCaches,
  invalidateReviewCachesWithoutRefetch,
  removePendingSuggestionFromCache,
  REVIEW_DROP_MODE,
} from './suggestionProjection';

/**
 * FEBT1G-H-07: a suggested merge is two requests against a backend that already
 * commits the structural merge in the first one. When hop 2 (suggestion accept)
 * fails, hop 1 is durable: the caller must be told the merge landed rather than
 * be shown a plain failure while the source cluster is retired. Carries the
 * committed merge result so the error path can still apply hop-1 state.
 * The atomic fix is a backend contract change — see the lane report.
 */
class MergeSuggestionResolutionError extends Error {
  readonly mergeResult: MergeClusterResponse;

  constructor(mergeResult: MergeClusterResponse, cause: unknown) {
    super('merge_suggestion_not_resolved', { cause });
    this.name = 'MergeSuggestionResolutionError';
    this.mergeResult = mergeResult;
  }
}

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
      onError?.(getClusterMutationErrorMessage(err, currentLabel ?? derivedLabel ?? ''));
    },
  });

  // Hop-1 (structural merge) state, applied on both the clean and the
  // partial-failure path — the merge itself is committed in either case.
  const applyCommittedMerge = (result: MergeClusterResponse): void => {
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
    invalidateReviewCachesWithoutRefetch(queryClient);
  };

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
        try {
          await acceptSuggestion(suggestionId);
        } catch (err) {
          throw new MergeSuggestionResolutionError(result, err);
        }
      }
      return result;
    },
    // Don't retry on client errors
    retry: false,
    onSuccess: (result, variables) => {
      applyCommittedMerge(result);
      // L1V-03: drop accepted pending row before invalidate so review queue is not stale until refetch.
      if (variables.suggestionId) {
        removePendingSuggestionFromCache(queryClient, variables.suggestionId);
      }
      invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: unknown, variables) => {
      // L1V-02: hop-1 merge may have committed before hop-2 accept failed — always refresh caches.
      invalidateQueries();
      if (err instanceof MergeSuggestionResolutionError) {
        // The merge is durable: record the survivor so the retired source
        // rebinds instead of closing, and keep the pending suggestion row —
        // it is genuinely unresolved.
        applyCommittedMerge(err.mergeResult);
        invalidateQueries();
        onError?.(
          __(
            'Merged, but the suggestion could not be cleared. It may reappear until the next sync.',
            'alt-context',
          ),
        );
        return;
      }
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
