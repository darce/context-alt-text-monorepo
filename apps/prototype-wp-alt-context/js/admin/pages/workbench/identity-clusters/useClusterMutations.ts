/**
 * Hook for cluster mutation operations (rename, merge, revert, reassign, split).
 *
 * Centralizes all cluster API mutations and cache invalidation logic.
 */

import { __ } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import {
  createClusterForIdentity,
  fetchScanStatus,
  mergeCluster,
  reassignClusterIdentity,
  revertMergeCluster,
  splitCluster,
  updateClusterLabel,
  rejectSuggestion,
  type MediaIdentitiesResponse,
  type MergeClusterResponse,
} from '../../../api/recognition';

interface UseClusterMutationsOptions {
  /** Cluster ID for the mutations (null if not editable) */
  clusterId: string | null;
  /** Identity count for async split threshold checks */
  identityCount?: number;
  /** Current cluster label (for revert operations) */
  currentLabel: string | null;
  /** Derived display label */
  derivedLabel: string | null;
  /** Callback on successful rename */
  onRenameSuccess?: (newLabel: string) => void;
  /** Callback on successful merge */
  onMergeSuccess?: (result: MergeClusterResponse) => void;
  /** Callback on successful revert */
  onRevertSuccess?: () => void;
  /** Callback on any error */
  onError?: (error: string) => void;
}

const SPLIT_ASYNC_THRESHOLD = 50;
const SPLIT_POLL_INTERVAL_MS = 1500;
const SPLIT_TIMEOUT_MS = 120_000;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const isAbortError = (err: unknown): boolean =>
  Boolean(err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError');

const pollSplitJob = async (jobId: string): Promise<void> => {
  const startedAt = Date.now();
  while (Date.now() - startedAt < SPLIT_TIMEOUT_MS) {
    const status = await fetchScanStatus(jobId);
    if (status.status === 'completed') {
      return;
    }
    if (status.status === 'failed') {
      throw new Error(status.message ?? __('Split job failed.', 'alt-context'));
    }
    await delay(SPLIT_POLL_INTERVAL_MS);
  }
  throw new Error(__('Split job timed out. Please retry.', 'alt-context'));
};

/**
 * Hook providing all cluster mutation operations.
 *
 * Handles:
 * - Rename (PATCH label)
 * - Merge (POST merge into target label)
 * - Revert merge
 * - Reassign identities (remove from cluster)
 * - Split cluster
 */
export const useClusterMutations = ({
  clusterId,
  identityCount,
  currentLabel,
  derivedLabel,
  onRenameSuccess,
  onMergeSuccess,
  onRevertSuccess,
  onError,
}: UseClusterMutationsOptions) => {
  const queryClient = useQueryClient();

  // Invalidate and refetch queries after mutations
  const invalidateQueries = () => {
    void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    void queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
    void queryClient.invalidateQueries({ queryKey: ['clusters'] });
  };

  // Optimistically update cache for label changes
  const updateCachedClusterLabel = (targetClusterId: string, nextLabel: string) => {
    queryClient.setQueriesData<MediaIdentitiesResponse>({ queryKey: ['media-identities'] }, (current) => {
      if (!current) {
        return current;
      }

      let changed = false;
      const nextMap: MediaIdentitiesResponse['identities_by_media'] = {};

      for (const [mediaKey, identities] of Object.entries(current.identities_by_media)) {
        let mediaChanged = false;
        const updatedIdentities = identities.map((identity) => {
          if (identity.cluster_id !== targetClusterId) {
            return identity;
          }
          mediaChanged = true;
          changed = true;
          return {
            ...identity,
            cluster_label: nextLabel,
            is_auto_label: false,
          };
        });
        nextMap[mediaKey] = mediaChanged ? updatedIdentities : identities;
      }

      if (!changed) {
        return current;
      }
      return { identities_by_media: nextMap };
    });
  };

  // Rename mutation
  const renameMutation = useMutation({
    mutationKey: ['rename-cluster', clusterId],
    mutationFn: ({ label, signal }: { label: string; signal?: AbortSignal }) =>
      updateClusterLabel(clusterId!, label, signal),
    onMutate: async ({ label }) => {
      if (!clusterId) {
        return;
      }
      await queryClient.cancelQueries({ queryKey: ['media-identities'] });
      updateCachedClusterLabel(clusterId, label);
    },
    onSuccess: (_data, variables) => {
      const updatedLabel = variables.label;
      if (clusterId) {
        updateCachedClusterLabel(clusterId, updatedLabel);
      }
      void invalidateQueries();
      onRenameSuccess?.(updatedLabel);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        void invalidateQueries();
        return;
      }
      void invalidateQueries();
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('409')) {
        onError?.(__('Label already exists. Use the dropdown to merge.', 'alt-context'));
      } else {
        onError?.(message);
      }
    },
  });

  // Merge mutation
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
    onSuccess: (result) => {
      if (clusterId) {
        updateCachedClusterLabel(clusterId, result.target_label ?? '');
      }
      void invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  // Revert merge mutation
  const revertMergeMutation = useMutation({
    mutationFn: (payload: MergeClusterResponse) =>
      revertMergeCluster({
        targetClusterId: payload.target_id,
        movedIdentityIds: payload.moved_identity_ids,
        sourceLabel: payload.source_label ?? currentLabel ?? derivedLabel ?? null,
      }),
    onSuccess: () => {
      void invalidateQueries();
      onRevertSuccess?.();
    },
    onError: (err: Error) => {
      onError?.(err.message);
    },
  });

  // Reassign (remove from cluster) mutation
  const reassignMutation = useMutation({
    mutationKey: ['reassign-identities', clusterId],
    mutationFn: async (identityIds: string[]) => {
      for (const id of identityIds) {
        await reassignClusterIdentity({ identityId: id, targetClusterId: null, blockFromCluster: true });
      }
    },
    onSuccess: () => {
      void invalidateQueries();
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  // Assign identity to existing cluster (for singletons)
  const assignToClusterMutation = useMutation({
    mutationKey: ['assign-to-cluster', clusterId],
    mutationFn: async ({
      identityId,
      targetClusterId,
      signal,
    }: {
      identityId: string;
      targetClusterId: string;
      signal?: AbortSignal;
    }) => {
      await reassignClusterIdentity({ identityId, targetClusterId }, signal);
    },
    onSuccess: () => {
      void invalidateQueries();
      onRenameSuccess?.(''); // Clear edit state
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  // Create cluster for singleton identity
  const createClusterMutation = useMutation({
    mutationKey: ['create-cluster-for-identity'],
    mutationFn: async ({ identityId, label, signal }: { identityId: string; label: string; signal?: AbortSignal }) => {
      return createClusterForIdentity({ identityId, label }, signal);
    },
    onSuccess: (result) => {
      void invalidateQueries();
      onRenameSuccess?.(result.label);
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('409')) {
        onError?.(__('Label already exists. Select it from the dropdown to assign.', 'alt-context'));
      } else {
        onError?.(message);
      }
    },
  });

  // Split cluster mutation
  const splitMutation = useMutation({
    mutationKey: ['split-cluster', clusterId],
    mutationFn: async ({
      clusterId,
      nClusters = 2,
      anchorIdentityId,
    }: {
      clusterId: string;
      nClusters?: number;
      anchorIdentityId?: string;
    }) => {
      const mode = (identityCount ?? 0) > SPLIT_ASYNC_THRESHOLD ? 'async' : 'sync';
      const result = await splitCluster(clusterId, { nClusters, anchorIdentityId, splitMode: 'forced', mode });
      if ('job_id' in result) {
        await pollSplitJob(result.job_id);
      }
      return result;
    },
    onSuccess: () => {
      void invalidateQueries();
    },
    onError: (err: unknown) => {
      if (isAbortError(err)) {
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  // Reject suggestion mutation
  const rejectSuggestionMutation = useMutation({
    mutationKey: ['reject-suggestion'],
    mutationFn: (suggestionId: string) => rejectSuggestion(suggestionId),
    onSuccess: () => {
      void invalidateQueries();
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      onError?.(message);
    },
  });

  const isPending =
    renameMutation.isPending ||
    mergeMutation.isPending ||
    revertMergeMutation.isPending ||
    reassignMutation.isPending ||
    assignToClusterMutation.isPending ||
    createClusterMutation.isPending ||
    splitMutation.isPending ||
    rejectSuggestionMutation.isPending;

  return {
    // Mutations
    rename: (label: string, signal?: AbortSignal) => renameMutation.mutate({ label, signal }),
    merge: (targetClusterId: string, targetLabel?: string, signal?: AbortSignal) =>
      mergeMutation.mutate({ targetClusterId, targetLabel, signal }),
    revertMerge: revertMergeMutation.mutate,
    reassign: reassignMutation.mutate,
    assignToCluster: (identityId: string, targetClusterId: string, signal?: AbortSignal) =>
      assignToClusterMutation.mutate({ identityId, targetClusterId, signal }),
    createClusterForIdentity: (identityId: string, label: string, signal?: AbortSignal) =>
      createClusterMutation.mutate({ identityId, label, signal }),
    split: (clusterId: string, nClusters = 2, anchorIdentityId?: string) =>
      splitMutation.mutate({ clusterId, nClusters, anchorIdentityId }),
    rejectSuggestion: (suggestionId: string) => rejectSuggestionMutation.mutate(suggestionId),

    // Loading states
    isPending,
    isRenaming: renameMutation.isPending,
    isMerging: mergeMutation.isPending,
    isReverting: revertMergeMutation.isPending,
    isReassigning: reassignMutation.isPending,
    isAssigning: assignToClusterMutation.isPending,
    isCreatingCluster: createClusterMutation.isPending,
    isSplitting: splitMutation.isPending,
    isRejectingSuggestion: rejectSuggestionMutation.isPending,
  };
};
