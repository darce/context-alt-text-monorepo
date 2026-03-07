import React from 'react';
import { __, sprintf } from '@wordpress/i18n';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../../api/queryKeys';
import type { AnalyzeResponse } from '../../../api/recognition';
import { commitClusterToRosterEntry } from '../../../api/rosterApi';
import { dismissCluster, mergeCluster, reassignClusterIdentity, scanFacesBatched } from '../../../api/recognition';
import { useToast } from '../../../context/ToastContext';

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
    AnalyzeResponse[],
    Error,
    { cluster: { id: string; sample_identities: { media_id: number }[] }; mediaIds: number[] }
  >({
    mutationFn: ({ cluster, mediaIds }) => scanFacesBatched({ mediaIds, sensitivity: 'high', clusterId: cluster.id }),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.clusters.all });
      const firstJob = data[0];
      const msg = firstJob?.id
        ? data.length > 1
          ? sprintf(__('Started sensitive rescan (%d batches, first job %s).', 'alt-context'), data.length, firstJob.id)
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

