/**
 * Hook for cluster mutation operations (rename, merge, revert, reassign, split).
 *
 * Centralizes all cluster API mutations and cache invalidation logic.
 */

import { useCallback } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '../../../api/queryKeys';
import type { MediaIdentitiesResponse, MergeClusterResponse } from '../../../api/recognition';
import { useClusterActionMutations } from './useClusterActionMutations';
import { useClusterLabelMutations } from './useClusterLabelMutations';

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
  /** Callback on abort to reset UI status without error */
  onAbort?: () => void;
}

export const useClusterMutations = ({
  clusterId,
  identityCount,
  currentLabel,
  derivedLabel,
  onRenameSuccess,
  onMergeSuccess,
  onRevertSuccess,
  onError,
  onAbort,
}: UseClusterMutationsOptions) => {
  const queryClient = useQueryClient();

  const invalidateQueries = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.media.identities(), refetchType: 'none' });
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.labels(), refetchType: 'none' });
    void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all, refetchType: 'none' });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.suggestions.projection.all,
      refetchType: 'none',
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.suggestions.mergePending(),
      refetchType: 'none',
    });
  }, [queryClient]);

  const cancelIdentityQueries = useCallback(
    () => queryClient.cancelQueries({ queryKey: queryKeys.media.identities() }),
    [queryClient],
  );

  const updateCachedClusterLabel = useCallback(
    (targetClusterId: string, nextLabel: string) => {
      queryClient.setQueriesData<MediaIdentitiesResponse>({ queryKey: queryKeys.media.identities() }, (current) => {
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
    },
    [queryClient],
  );

  const labelMutations = useClusterLabelMutations({
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
  });

  const actionMutations = useClusterActionMutations({
    clusterId,
    identityCount,
    onRenameSuccess,
    onError,
    onAbort,
    invalidateQueries,
  });

  const isPending =
    labelMutations.isRenaming ||
    labelMutations.isMerging ||
    labelMutations.isReverting ||
    actionMutations.isReassigning ||
    actionMutations.isAssigning ||
    actionMutations.isCreatingCluster ||
    actionMutations.isSplitting ||
    actionMutations.isRejectingSuggestion;

  return {
    // Mutations
    rename: labelMutations.rename,
    merge: labelMutations.merge,
    revertMerge: labelMutations.revertMerge,
    reassign: actionMutations.reassign,
    assignToCluster: actionMutations.assignToCluster,
    createClusterForIdentity: actionMutations.createClusterForIdentity,
    split: actionMutations.split,
    rejectSuggestion: actionMutations.rejectSuggestion,
    pinRepresentative: actionMutations.pinRepresentative,

    // Loading states
    isPending,
    isRenaming: labelMutations.isRenaming,
    isMerging: labelMutations.isMerging,
    isReverting: labelMutations.isReverting,
    isReassigning: actionMutations.isReassigning,
    isAssigning: actionMutations.isAssigning,
    isCreatingCluster: actionMutations.isCreatingCluster,
    isSplitting: actionMutations.isSplitting,
    isRejectingSuggestion: actionMutations.isRejectingSuggestion,
    isPinningRepresentative: actionMutations.isPinningRepresentative,
    splitGate: actionMutations.splitGate,
  };
};
