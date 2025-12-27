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
  const invalidateQueries = async () => {
    void queryClient.invalidateQueries({ queryKey: ['media-identities'] });
    void queryClient.invalidateQueries({ queryKey: ['cluster-labels'] });
    void queryClient.invalidateQueries({ queryKey: ['clusters'] });
    // Force immediate refetch for suggestions (per hybrid-clustering-strategy.md Phase 3)
    await queryClient.refetchQueries({ queryKey: ['identity-suggestions'] });
    await queryClient.refetchQueries({ queryKey: ['pending-suggestions'] });
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
    mutationFn: (label: string) => updateClusterLabel(clusterId!, label),
    onSuccess: (_data, updatedLabel) => {
      if (clusterId) {
        updateCachedClusterLabel(clusterId, updatedLabel);
      }
      void invalidateQueries();
      onRenameSuccess?.(updatedLabel);
    },
    onError: (err: Error) => {
      if (err.message.includes('409')) {
        onError?.(__('Label already exists. Use the dropdown to merge.', 'alt-context'));
      } else {
        onError?.(err.message);
      }
    },
  });

  // Merge mutation
  const mergeMutation = useMutation({
    mutationKey: ['merge-cluster', clusterId],
    mutationFn: ({ targetClusterId, targetLabel }: { targetClusterId: string; targetLabel?: string }) => {
      if (!clusterId) {
        return Promise.reject(new Error(__('Cannot merge: no cluster ID', 'alt-context')));
      }
      return mergeCluster(clusterId, targetClusterId, targetLabel);
    },
    onSuccess: (result) => {
      if (clusterId) {
        updateCachedClusterLabel(clusterId, result.target_label ?? '');
      }
      void invalidateQueries();
      onMergeSuccess?.(result);
    },
    onError: (err: Error) => {
      onError?.(err.message);
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
    onError: (err: Error) => {
      onError?.(err.message);
    },
  });

  // Assign identity to existing cluster (for singletons)
  const assignToClusterMutation = useMutation({
    mutationKey: ['assign-to-cluster', clusterId],
    mutationFn: async ({ identityId, targetClusterId }: { identityId: string; targetClusterId: string }) => {
      await reassignClusterIdentity({ identityId, targetClusterId });
    },
    onSuccess: () => {
      void invalidateQueries();
      onRenameSuccess?.(''); // Clear edit state
    },
    onError: (err: Error) => {
      onError?.(err.message);
    },
  });

  // Create cluster for singleton identity
  const createClusterMutation = useMutation({
    mutationKey: ['create-cluster-for-identity'],
    mutationFn: async ({ identityId, label }: { identityId: string; label: string }) => {
      return createClusterForIdentity({ identityId, label });
    },
    onSuccess: (result) => {
      void invalidateQueries();
      onRenameSuccess?.(result.label);
    },
    onError: (err: Error) => {
      if (err.message.includes('409')) {
        onError?.(__('Label already exists. Select it from the dropdown to assign.', 'alt-context'));
      } else {
        onError?.(err.message);
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
    onError: (err: Error) => {
      onError?.(err.message);
    },
  });

  const isPending =
    renameMutation.isPending ||
    mergeMutation.isPending ||
    revertMergeMutation.isPending ||
    reassignMutation.isPending ||
    assignToClusterMutation.isPending ||
    createClusterMutation.isPending ||
    splitMutation.isPending;

  return {
    // Mutations
    rename: renameMutation.mutate,
    merge: (targetClusterId: string, targetLabel?: string) => mergeMutation.mutate({ targetClusterId, targetLabel }),
    revertMerge: revertMergeMutation.mutate,
    reassign: reassignMutation.mutate,
    assignToCluster: (identityId: string, targetClusterId: string) =>
      assignToClusterMutation.mutate({ identityId, targetClusterId }),
    createClusterForIdentity: (identityId: string, label: string) =>
      createClusterMutation.mutate({ identityId, label }),
    split: (clusterId: string, nClusters = 2, anchorIdentityId?: string) =>
      splitMutation.mutate({ clusterId, nClusters, anchorIdentityId }),

    // Loading states
    isPending,
    isRenaming: renameMutation.isPending,
    isMerging: mergeMutation.isPending,
    isReverting: revertMergeMutation.isPending,
    isReassigning: reassignMutation.isPending,
    isAssigning: assignToClusterMutation.isPending,
    isCreatingCluster: createClusterMutation.isPending,
    isSplitting: splitMutation.isPending,
  };
};
