/**
 * Hook for label-focused cluster mutations (rename, merge, revert).
 */

import { __ } from '@wordpress/i18n';
import { useMutation } from '@tanstack/react-query';

import {
  mergeCluster,
  revertMergeCluster,
  updateClusterLabel,
  type MergeClusterResponse,
} from '../../../api/recognition';
import { getProjectionNotReadyMessage, isAbortError, isProjectionNotReadyError } from './clusterMutationUtils';

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
      }
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
    mutationFn: ({
      targetClusterId,
      targetLabel,
      signal,
    }: {
      targetClusterId: string;
      targetLabel?: string;
      signal?: AbortSignal;
    }) => {
      if (!clusterId) {
        return Promise.reject(new Error(__('Cannot merge: no cluster ID', 'alt-context')));
      }
      return mergeCluster(clusterId, targetClusterId, targetLabel, signal);
    },
    // Don't retry on client errors
    retry: false,
    onSuccess: (result) => {
      if (clusterId) {
        updateCachedClusterLabel(clusterId, result.target_label ?? '');
      }
      invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        onAbort?.();
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
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
    merge: (targetClusterId: string, targetLabel?: string, signal?: AbortSignal) =>
      mergeMutation.mutate({ targetClusterId, targetLabel, signal }),
    revertMerge: revertMergeMutation.mutate,
    isRenaming: renameMutation.isPending,
    isMerging: mergeMutation.isPending,
    isReverting: revertMergeMutation.isPending,
  };
};
