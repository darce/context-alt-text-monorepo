import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import type { BatchAnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { dismissCluster, mergeCluster, reassignClusterIdentity, scanFacesBatched } from '../../../api/recognition';
import { invalidateSuggestionProjection } from '../../workbench/identity-clusters/suggestionProjection';
import { useToast } from '../../../context/ToastContext';
import { offlineActionReason, useRemoteActionGate } from '../../../hooks/useRemoteActionGate';
import { useSyncOffline } from '../../../hooks/useSyncOffline';

interface ClusterActionOptions {
  onReassignSettled?: () => void;
  onRescanSettled?: () => void;
  onCommitSettled?: () => void;
  onBulkMergeSettled?: () => void;
  onBulkDismissSettled?: () => void;
}

export const useClusterActions = ({
  onReassignSettled,
  onRescanSettled,
  onCommitSettled,
  onBulkMergeSettled,
  onBulkDismissSettled,
}: ClusterActionOptions = {}) => {
  const queryClient = useQueryClient();
  const { success, error: showToastError } = useToast();
  const [bulkMergeProgress, setBulkMergeProgress] = React.useState<{ current: number; total: number } | null>(null);
  // RES-15: gate sensitive rescan only — curation (merge/reassign/commit/dismiss) stays live offline.
  const offline = useSyncOffline();
  const rescanGate = useRemoteActionGate(offline);

  const reassignMutation = useMutation<void, Error, { faceId: string; targetClusterId: string | null }>({
    mutationFn: (variables) =>
      reassignClusterIdentity({ identityId: variables.faceId, targetClusterId: variables.targetClusterId }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Identity assignment updated.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: onReassignSettled,
  });

  const rescanMutation = useMutation<
    BatchAnalyzeResponse,
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutationFn: ({ cluster, mediaIds }) => {
      if (offline) {
        throw new Error(offlineActionReason());
      }
      return scanFacesBatched({ mediaIds, sensitivity: 'high', clusterId: cluster.id });
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      const firstJob = data.jobs[0];
      const msg = firstJob?.id
        ? data.jobs.length > 1
          ? sprintf(
              __('Started sensitive rescan (%d batches, first job %s).', 'alt-context'),
              data.jobs.length,
              firstJob.id,
            )
          : sprintf(__('Started sensitive rescan (job %s).', 'alt-context'), firstJob.id)
        : __('Started sensitive rescan.', 'alt-context');
      success(msg);
    },
    onError: (err) => showToastError(err.message),
    onSettled: onRescanSettled,
  });

  const commitMutation = useMutation<void, Error, { clusterId: string; rosterEntryId?: number; newEntryName?: string }>(
    {
      mutationFn: (variables) =>
        commitClusterToRosterEntry({
          clusterId: variables.clusterId,
          rosterEntryId: variables.rosterEntryId,
          newEntryName: variables.newEntryName,
        }),
      onSuccess: () => {
        // clusterLabelSetClear event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS):
        // committing labels a cluster, changing its suggestion eligibility everywhere.
        void invalidateSuggestionProjection(queryClient);
        void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
        void queryClient.invalidateQueries({ queryKey: queryKeys.roster.entries() });
        success(__('Cluster committed to roster entry.', 'alt-context'));
      },
      onError: (err) => showToastError(err.message),
      onSettled: onCommitSettled,
    },
  );

  const bulkMergeMutation = useMutation<void, Error, { clusterIds: string[] }>({
    mutationFn: async ({ clusterIds }) => {
      if (clusterIds.length < 2) {
        setBulkMergeProgress(null);
        return;
      }
      const targetId = clusterIds[0];
      const sourceIds = clusterIds.slice(1);
      const total = sourceIds.length;
      setBulkMergeProgress({ current: 1, total });
      for (const [index, sourceId] of sourceIds.entries()) {
        setBulkMergeProgress({ current: index + 1, total });
        await mergeCluster(sourceId, targetId);
      }
    },
    onSuccess: () => {
      // clusterMerge event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS): absorbed source
      // clusters may back pending assignment suggestions on any surface.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Clusters merged successfully.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: () => {
      setBulkMergeProgress(null);
      onBulkMergeSettled?.();
    },
  });

  const bulkDismissMutation = useMutation<void, Error, { clusterIds: string[] }>({
    mutationFn: async ({ clusterIds }) => {
      await Promise.all(clusterIds.map((id) => dismissCluster(id)));
    },
    onSuccess: () => {
      // clusterDismiss event (SUGGESTION_PROJECTION_INVALIDATION_EVENTS): dismissed
      // clusters may back pending assignment suggestions on any surface.
      void invalidateSuggestionProjection(queryClient);
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      success(__('Clusters dismissed.', 'alt-context'));
    },
    onError: (err) => showToastError(err.message),
    onSettled: onBulkDismissSettled,
  });

  const resetAll = () => {
    reassignMutation.reset();
    rescanMutation.reset();
    commitMutation.reset();
    bulkMergeMutation.reset();
    bulkDismissMutation.reset();
  };

  return {
    reassignMutation,
    rescanMutation,
    commitMutation,
    bulkMergeMutation,
    bulkDismissMutation,
    bulkMergeProgress,
    rescanGate,
    errorMessage:
      reassignMutation.error?.message ??
      rescanMutation.error?.message ??
      commitMutation.error?.message ??
      bulkMergeMutation.error?.message ??
      bulkDismissMutation.error?.message ??
      null,
    resetAll,
  };
};
